from __future__ import annotations

import os
import subprocess
from pathlib import Path

import clawteam.worker_runtime as worker_runtime
from clawteam.spawn.subprocess_backend import SubprocessBackend
from clawteam.team.mailbox import MailboxManager
from clawteam.team.manager import TeamManager
from clawteam.team.models import TaskStatus
from clawteam.team.tasks import TaskStore
from clawteam.worker_runtime import (
    build_openclaw_agent_command,
    build_worker_task_prompt,
    run_worker_iteration,
)


class _Completed:
    def __init__(self, returncode=0, stdout="ok", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _seed_team(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))
    TeamManager.create_team("demo", "leader", "leader-1")
    TeamManager.add_member("demo", "qa1", "qa1-id")


def test_build_openclaw_agent_command_uses_headless_agent_mode():
    cmd = build_openclaw_agent_command(
        base_command=["openclaw"],
        session_key="clawteam-demo-qa1",
        prompt="hello",
        timeout_seconds=123,
    )
    assert cmd[:2] == ["openclaw", "agent"]
    assert "--session-id" in cmd
    assert "clawteam-demo-qa1" in cmd
    assert "--message" in cmd
    assert "hello" in cmd


def test_build_worker_task_prompt_uses_shell_safe_identity_bootstrap(monkeypatch, tmp_path):
    _seed_team(tmp_path, monkeypatch)
    monkeypatch.setenv("CLAWTEAM_AGENT_ID", "qa 1-id")
    monkeypatch.setenv("CLAWTEAM_AGENT_TYPE", "general purpose")
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data dir"))

    task = TaskStore("demo").create(subject="Fix thing", description="Real task", owner="qa1")
    prompt = build_worker_task_prompt(
        team_name="demo team",
        agent_name="qa 1",
        leader_name="leader",
        task=task,
    )

    expected_bootstrap = (
        "`eval $(clawteam identity set --agent-name 'qa 1' --agent-id 'qa 1-id' "
        "--agent-type 'general purpose' --team 'demo team' "
        f"--data-dir '{tmp_path / 'data dir'}' --shell)`"
    )

    assert expected_bootstrap in prompt
    assert "clawteam identity set" in prompt
    assert "--shell" in prompt
    assert f"- Active Execution ID: {task.active_execution_id}" not in prompt
    assert "Workflow routing is owned by the leader/template/state machine" in prompt
    assert "Do not create repair/retry/review tasks or mutate blocked_by/on_fail edges" in prompt
    assert "Use structured result blocks instead of free-form prose" in prompt
    assert "QA_RESULT must include exactly these headings" in prompt


def test_build_worker_task_prompt_includes_active_execution_when_claimed(monkeypatch, tmp_path):
    _seed_team(tmp_path, monkeypatch)
    task = TaskStore("demo").create(subject="Fix thing", description="Real task", owner="qa1")
    claimed = TaskStore("demo").update(task.id, status=TaskStatus.in_progress, caller="qa1")

    prompt = build_worker_task_prompt(
        team_name="demo",
        agent_name="qa1",
        leader_name="leader",
        task=claimed,
    )

    assert f"- Active Execution ID: {claimed.active_execution_id}" in prompt



def test_run_worker_iteration_claims_and_dispatches_openclaw(monkeypatch, tmp_path):
    _seed_team(tmp_path, monkeypatch)
    monkeypatch.setenv("CLAWTEAM_AGENT_NAME", "qa1")
    monkeypatch.setenv("CLAWTEAM_TEAM_NAME", "demo")
    monkeypatch.setenv("CLAWTEAM_AGENT_ID", "qa1-id")
    monkeypatch.setenv("CLAWTEAM_WORKSPACE_DIR", str(tmp_path / "ws"))

    mailbox = MailboxManager("demo")
    task = TaskStore("demo").create(subject="Fix thing", description="Real task", owner="qa1")
    wake = mailbox.send("leader", "qa1", "start now", key=f"task-wake:{task.id}", last_task=task.id)

    called = {}

    def fake_run(command, cwd=None, env=None, session_key=None, total_timeout_seconds=None, progress_stall_timeout_seconds=None, progress_poll_interval_seconds=None):
        called["command"] = command
        called["cwd"] = cwd
        called["env"] = env
        TaskStore("demo").update(task.id, status=TaskStatus.completed, caller="qa1")
        return _Completed()

    monkeypatch.setattr(worker_runtime, "_run_agent_with_progress_watchdog", fake_run)

    result = run_worker_iteration(team_name="demo", agent_name="qa1", base_command=["openclaw"])

    assert result["status"] == "dispatched"
    assert result["taskId"] == task.id
    assert result["messages"] == 1
    assert result["acked"] == 1
    assert result["executionId"].startswith(f"{task.id}-exec-")
    assert result["executionSeq"] == 1
    assert result["claimCase"] == "claim_execution"
    assert called["command"][:2] == ["openclaw", "agent"]
    assert "--session-id" in called["command"]
    assert f"clawteam-demo-qa1" in called["command"]
    assert called["env"]["CLAWTEAM_TASK_ID"] == task.id
    assert called["env"]["CLAWTEAM_TASK_EXECUTION_ID"] == result["executionId"]
    assert called["env"]["CLAWTEAM_TASK_EXECUTION_SEQ"] == "1"

    updated = TaskStore("demo").get(task.id)
    assert updated is not None
    assert updated.status.value == "completed"
    assert updated.locked_by == ""
    assert updated.execution_seq == 1
    assert updated.active_execution_id == ""
    assert updated.last_terminal_execution_id == result["executionId"]
    assert updated.last_terminal_status == "completed"
    assert updated.metadata["transition_log"][0]["case"] == "claim_execution"
    assert updated.metadata["transition_log"][-1]["accepted"] is True

    acks = mailbox.receive("leader")
    assert len(acks) == 1
    assert acks[0].request_id == wake.request_id
    assert acks[0].type.value == "ack"


def test_run_worker_iteration_acks_matching_wake_without_consuming_other_messages(monkeypatch, tmp_path):
    _seed_team(tmp_path, monkeypatch)
    monkeypatch.setenv("CLAWTEAM_AGENT_NAME", "qa1")
    monkeypatch.setenv("CLAWTEAM_TEAM_NAME", "demo")
    monkeypatch.setenv("CLAWTEAM_AGENT_ID", "qa1-id")

    mailbox = MailboxManager("demo")
    task = TaskStore("demo").create(subject="Fix thing", description="Real task", owner="qa1")
    other = mailbox.send("leader", "qa1", "unrelated", key="note:1")
    wake = mailbox.send("leader", "qa1", "start now", key=f"task-wake:{task.id}", last_task=task.id)

    def fake_run(*args, **kwargs):
        TaskStore("demo").update(task.id, status=TaskStatus.completed, caller="qa1")
        return _Completed()

    monkeypatch.setattr(worker_runtime, "_run_agent_with_progress_watchdog", fake_run)

    result = run_worker_iteration(team_name="demo", agent_name="qa1", base_command=["openclaw"])

    assert result["acked"] == 1
    remaining = mailbox.peek("qa1")
    assert len(remaining) == 1
    assert remaining[0].request_id == other.request_id

    acks = mailbox.receive("leader")
    assert len(acks) == 1
    assert acks[0].request_id == wake.request_id


def test_run_worker_iteration_selects_woken_task_not_first_pending(monkeypatch, tmp_path):
    _seed_team(tmp_path, monkeypatch)
    monkeypatch.setenv("CLAWTEAM_AGENT_NAME", "qa1")
    monkeypatch.setenv("CLAWTEAM_TEAM_NAME", "demo")
    monkeypatch.setenv("CLAWTEAM_AGENT_ID", "qa1-id")

    mailbox = MailboxManager("demo")
    first = TaskStore("demo").create(subject="Task A", description="A", owner="qa1")
    second = TaskStore("demo").create(subject="Task B", description="B", owner="qa1")
    wake = mailbox.send("leader", "qa1", "start task b", key=f"task-wake:{second.id}", last_task=second.id)

    def fake_run(*args, **kwargs):
        TaskStore("demo").update(second.id, status=TaskStatus.completed, caller="qa1")
        return _Completed()

    monkeypatch.setattr(worker_runtime, "_run_agent_with_progress_watchdog", fake_run)

    result = run_worker_iteration(team_name="demo", agent_name="qa1", base_command=["openclaw"])

    assert result["status"] == "dispatched"
    assert result["taskId"] == second.id
    assert TaskStore("demo").get(first.id).status.value == "pending"
    assert TaskStore("demo").get(second.id).status.value == "completed"

    acks = mailbox.receive("leader")
    assert len(acks) == 1
    assert acks[0].request_id == wake.request_id


def test_run_worker_iteration_uses_oldest_matching_wake_order(monkeypatch, tmp_path):
    _seed_team(tmp_path, monkeypatch)
    monkeypatch.setenv("CLAWTEAM_AGENT_NAME", "qa1")
    monkeypatch.setenv("CLAWTEAM_TEAM_NAME", "demo")
    monkeypatch.setenv("CLAWTEAM_AGENT_ID", "qa1-id")

    mailbox = MailboxManager("demo")
    first = TaskStore("demo").create(subject="Task A", description="A", owner="qa1")
    second = TaskStore("demo").create(subject="Task B", description="B", owner="qa1")
    first_wake = mailbox.send("leader", "qa1", "start task b", key=f"task-wake:{second.id}", last_task=second.id)
    mailbox.send("leader", "qa1", "note", key="note:1")
    second_wake = mailbox.send("leader", "qa1", "start task a", key=f"task-wake:{first.id}", last_task=first.id)

    def fake_run(*args, **kwargs):
        TaskStore("demo").update(second.id, status=TaskStatus.completed, caller="qa1")
        return _Completed()

    monkeypatch.setattr(worker_runtime, "_run_agent_with_progress_watchdog", fake_run)

    result = run_worker_iteration(team_name="demo", agent_name="qa1", base_command=["openclaw"])

    assert result["taskId"] == second.id
    remaining = mailbox.peek("qa1")
    assert [msg.request_id for msg in remaining if msg.key and msg.key.startswith("task-wake:")] == [second_wake.request_id]

    acks = mailbox.receive("leader")
    assert len(acks) == 1
    assert acks[0].request_id == first_wake.request_id


def test_run_worker_iteration_does_not_claim_pending_task_without_matching_wake(monkeypatch, tmp_path):
    _seed_team(tmp_path, monkeypatch)
    monkeypatch.setenv("CLAWTEAM_AGENT_NAME", "qa1")
    monkeypatch.setenv("CLAWTEAM_TEAM_NAME", "demo")
    monkeypatch.setenv("CLAWTEAM_AGENT_ID", "qa1-id")

    mailbox = MailboxManager("demo")
    task = TaskStore("demo").create(subject="Fix thing", description="Real task", owner="qa1")
    mailbox.send("leader", "qa1", "unrelated", key="note:1")

    called = {"ran": False}

    def fake_run(*args, **kwargs):
        called["ran"] = True
        return _Completed()

    monkeypatch.setattr(worker_runtime, "_run_agent_with_progress_watchdog", fake_run)

    result = run_worker_iteration(team_name="demo", agent_name="qa1", base_command=["openclaw"])

    assert result["status"] == "waiting_for_wake"
    assert result["acked"] == 0
    assert result["taskId"] == task.id
    assert called["ran"] is False



def test_run_worker_iteration_reports_contended_when_claim_rejected_under_lock(monkeypatch, tmp_path):
    _seed_team(tmp_path, monkeypatch)
    monkeypatch.setenv("CLAWTEAM_AGENT_NAME", "qa1")
    monkeypatch.setenv("CLAWTEAM_TEAM_NAME", "demo")
    monkeypatch.setenv("CLAWTEAM_AGENT_ID", "qa1-id")

    mailbox = MailboxManager("demo")
    store = TaskStore("demo")
    task = store.create(subject="Fix thing", description="Real task", owner="qa1")
    mailbox.send("leader", "qa1", "start now", key=f"task-wake:{task.id}", last_task=task.id)

    called = {"ran": False, "raced": False}
    original_claim = TaskStore.claim_execution

    def racing_claim(self, task_id, *, caller, force=False):
        if not called["raced"]:
            called["raced"] = True
            other_store = TaskStore("demo")
            first = original_claim(other_store, task_id, caller=caller, force=force)
            assert first is not None and first.accepted is True
        return original_claim(self, task_id, caller=caller, force=force)

    def fake_run(*args, **kwargs):
        called["ran"] = True
        return _Completed()

    monkeypatch.setattr(TaskStore, "claim_execution", racing_claim)
    monkeypatch.setattr(worker_runtime, "_run_agent_with_progress_watchdog", fake_run)

    result = run_worker_iteration(team_name="demo", agent_name="qa1", base_command=["openclaw"])

    assert result["status"] == "contended"
    assert result["acked"] == 1
    assert result["taskId"] == task.id
    assert result["rejectionReason"] == "claim_requires_pending_or_blocked_task"
    assert called["ran"] is False
    assert called["raced"] is True

    updated = store.get(task.id)
    assert updated is not None
    assert updated.metadata["transition_log"][-1]["case"] == "claim_execution"
    assert updated.metadata["transition_log"][-1]["accepted"] is False
    assert updated.metadata["transition_log"][-1]["rejectionReason"] == "claim_requires_pending_or_blocked_task"

    updated = TaskStore("demo").get(task.id)
    assert updated is not None
    assert updated.status.value == "in_progress"
    assert updated.locked_by == "qa1"

    remaining = mailbox.peek("qa1")
    assert remaining == []


def test_run_worker_iteration_keeps_pending_task_idle_until_explicit_wake(monkeypatch, tmp_path):
    _seed_team(tmp_path, monkeypatch)
    monkeypatch.setenv("CLAWTEAM_AGENT_NAME", "qa1")
    monkeypatch.setenv("CLAWTEAM_TEAM_NAME", "demo")
    monkeypatch.setenv("CLAWTEAM_AGENT_ID", "qa1-id")

    task = TaskStore("demo").create(subject="Fix thing", description="Real task", owner="qa1")

    called = {"ran": False}

    def fake_run(*args, **kwargs):
        called["ran"] = True
        return _Completed()

    monkeypatch.setattr(worker_runtime, "_run_agent_with_progress_watchdog", fake_run)

    result = run_worker_iteration(team_name="demo", agent_name="qa1", base_command=["openclaw"])

    assert result == {
        "status": "waiting_for_wake",
        "messages": 0,
        "acked": 0,
        "taskId": task.id,
    }
    assert called["ran"] is False

    updated = TaskStore("demo").get(task.id)
    assert updated is not None
    assert updated.status.value == "pending"
    assert updated.locked_by == ""


def test_run_worker_iteration_fails_closed_on_nonzero_agent_exit(monkeypatch, tmp_path):
    _seed_team(tmp_path, monkeypatch)
    monkeypatch.setenv("CLAWTEAM_AGENT_NAME", "qa1")
    monkeypatch.setenv("CLAWTEAM_TEAM_NAME", "demo")
    monkeypatch.setenv("CLAWTEAM_AGENT_ID", "qa1-id")

    mailbox = MailboxManager("demo")
    task = TaskStore("demo").create(subject="Fix thing", description="Real task", owner="qa1")
    mailbox.send("leader", "qa1", "start now", key=f"task-wake:{task.id}", last_task=task.id)

    monkeypatch.setattr(
        worker_runtime,
        "_run_agent_with_progress_watchdog",
        lambda *args, **kwargs: _Completed(returncode=1, stdout="", stderr="502 Upstream request failed"),
    )

    result = run_worker_iteration(team_name="demo", agent_name="qa1", base_command=["openclaw"])

    assert result["status"] == "failed_closed"
    assert result["taskId"] == task.id
    assert result["reason"] == "worker agent turn failed"
    assert result["returncode"] == 1

    updated = TaskStore("demo").get(task.id)
    assert updated is not None
    assert updated.status.value == "failed"
    assert updated.locked_by == ""
    assert updated.metadata["failure_kind"] == "complex"
    assert updated.metadata["failure_root_cause"] == "worker agent turn failed"
    assert "502 Upstream request failed" in updated.metadata["failure_evidence"]


def test_task_store_rejects_stale_execution_terminal_writeback(monkeypatch, tmp_path):
    _seed_team(tmp_path, monkeypatch)
    store = TaskStore("demo")
    task = store.create(subject="Fix thing", description="Real task", owner="qa1")
    first = store.claim_execution(task.id, caller="qa1")
    stale_execution_id = first.task.active_execution_id
    assert first.case_name == "claim_execution"
    store.reopen_task(task.id, caller="qa1")
    store.claim_execution(task.id, caller="qa1")

    try:
        store.accept_terminal_writeback(
            task.id,
            status=TaskStatus.completed,
            caller="qa1",
            execution_id=stale_execution_id,
        )
        assert False, "expected stale execution rejection"
    except Exception as exc:
        assert "active execution" in str(exc)



def test_task_store_reopen_clears_active_execution(monkeypatch, tmp_path):
    _seed_team(tmp_path, monkeypatch)
    store = TaskStore("demo")
    task = store.create(subject="Fix thing", description="Real task", owner="qa1")
    claimed = store.claim_execution(task.id, caller="qa1")

    reopened = store.reopen_task(task.id, caller="qa1")

    assert claimed.task.active_execution_id != ""
    assert claimed.case_name == "claim_execution"
    assert reopened.case_name == "reopen_task"
    assert reopened.task.status == TaskStatus.pending
    assert reopened.task.active_execution_id == ""
    assert reopened.task.active_execution_owner == ""
    assert reopened.task.metadata["transition_log"][-1]["case"] == "reopen_task"
    assert reopened.task.metadata["transition_log"][-1]["accepted"] is True



def test_task_store_claim_execution_rejects_in_progress_snapshot_under_lock(monkeypatch, tmp_path):
    _seed_team(tmp_path, monkeypatch)
    store = TaskStore("demo")
    task = store.create(subject="Fix thing", description="Real task", owner="qa1")

    first = store.claim_execution(task.id, caller="qa1")
    second = store.claim_execution(task.id, caller="qa1")

    assert first is not None and first.accepted is True
    assert second is not None
    assert second.accepted is False
    assert second.case_name == "claim_execution"
    assert second.rejection_reason == "claim_requires_pending_or_blocked_task"
    assert second.task.metadata["transition_log"][-1]["accepted"] is False
    assert second.task.metadata["transition_log"][-1]["rejectionReason"] == "claim_requires_pending_or_blocked_task"



def test_task_store_rejects_duplicate_same_status_terminal_writeback(monkeypatch, tmp_path):
    _seed_team(tmp_path, monkeypatch)
    store = TaskStore("demo")
    task = store.create(subject="Fix thing", description="Real task", owner="qa1")
    claimed = store.claim_execution(task.id, caller="qa1")
    execution_id = claimed.task.active_execution_id

    first = store.accept_terminal_writeback(
        task.id,
        status=TaskStatus.completed,
        caller="qa1",
        execution_id=execution_id,
    )
    assert first is not None
    assert first.case_name == "execution_scoped_terminal_writeback"

    try:
        store.accept_terminal_writeback(
            task.id,
            status=TaskStatus.completed,
            caller="qa1",
            execution_id=execution_id,
        )
        assert False, "expected duplicate same-status rejection"
    except Exception as exc:
        assert "duplicate_terminal_same_status" in str(exc)



def test_task_store_rejects_duplicate_conflicting_status_terminal_writeback(monkeypatch, tmp_path):
    _seed_team(tmp_path, monkeypatch)
    store = TaskStore("demo")
    task = store.create(subject="Fix thing", description="Real task", owner="qa1")
    claimed = store.claim_execution(task.id, caller="qa1")
    execution_id = claimed.task.active_execution_id

    first = store.accept_terminal_writeback(
        task.id,
        status=TaskStatus.completed,
        caller="qa1",
        execution_id=execution_id,
    )
    assert first is not None

    try:
        store.accept_terminal_writeback(
            task.id,
            status=TaskStatus.failed,
            caller="qa1",
            execution_id=execution_id,
        )
        assert False, "expected duplicate conflicting-status rejection"
    except Exception as exc:
        assert "duplicate_terminal_conflicting_status" in str(exc)



def test_run_worker_iteration_fails_closed_when_dispatch_raises(monkeypatch, tmp_path):
    _seed_team(tmp_path, monkeypatch)
    monkeypatch.setenv("CLAWTEAM_AGENT_NAME", "qa1")
    monkeypatch.setenv("CLAWTEAM_TEAM_NAME", "demo")
    monkeypatch.setenv("CLAWTEAM_AGENT_ID", "qa1-id")

    mailbox = MailboxManager("demo")
    task = TaskStore("demo").create(subject="Fix thing", description="Real task", owner="qa1")
    mailbox.send("leader", "qa1", "start now", key=f"task-wake:{task.id}", last_task=task.id)

    def boom(*args, **kwargs):
        raise RuntimeError("stream_read_error")

    monkeypatch.setattr(worker_runtime, "_run_agent_with_progress_watchdog", boom)

    result = run_worker_iteration(team_name="demo", agent_name="qa1", base_command=["openclaw"])

    assert result["status"] == "failed_closed"
    assert result["taskId"] == task.id
    assert result["reason"] == "worker runtime dispatch failed"
    assert "stream_read_error" in result["evidence"]

    updated = TaskStore("demo").get(task.id)
    assert updated is not None
    assert updated.status.value == "failed"
    assert updated.locked_by == ""
    assert updated.metadata["failure_kind"] == "complex"
    assert updated.metadata["failure_root_cause"] == "worker runtime dispatch failed"
    assert "stream_read_error" in updated.metadata["failure_evidence"]


def test_run_worker_iteration_reports_already_terminal_for_duplicate_same_status_failure(monkeypatch, tmp_path):
    _seed_team(tmp_path, monkeypatch)
    monkeypatch.setenv("CLAWTEAM_AGENT_NAME", "qa1")
    monkeypatch.setenv("CLAWTEAM_TEAM_NAME", "demo")
    monkeypatch.setenv("CLAWTEAM_AGENT_ID", "qa1-id")

    mailbox = MailboxManager("demo")
    task = TaskStore("demo").create(subject="Fix thing", description="Real task", owner="qa1")
    mailbox.send("leader", "qa1", "start now", key=f"task-wake:{task.id}", last_task=task.id)

    def fake_run(command, cwd=None, env=None, session_key=None, total_timeout_seconds=None, progress_stall_timeout_seconds=None, progress_poll_interval_seconds=None):
        TaskStore("demo").update(task.id, status=TaskStatus.failed, caller="qa1")
        return _Completed(returncode=1, stdout="", stderr="502 Upstream request failed")

    monkeypatch.setattr(worker_runtime, "_run_agent_with_progress_watchdog", fake_run)

    result = run_worker_iteration(team_name="demo", agent_name="qa1", base_command=["openclaw"])

    assert result["status"] == "already_terminal"
    assert result["taskId"] == task.id
    assert result["rejectionReason"] == "duplicate_terminal_same_status"
    assert result["terminalStatus"] == "failed"

    updated = TaskStore("demo").get(task.id)
    assert updated is not None
    assert updated.status.value == "failed"
    assert updated.metadata["transition_log"][-1]["accepted"] is False
    assert updated.metadata["transition_log"][-1]["rejectionReason"] == "duplicate_terminal_same_status"


def test_run_worker_iteration_reports_duplicate_terminal_for_conflicting_terminal(monkeypatch, tmp_path):
    _seed_team(tmp_path, monkeypatch)
    monkeypatch.setenv("CLAWTEAM_AGENT_NAME", "qa1")
    monkeypatch.setenv("CLAWTEAM_TEAM_NAME", "demo")
    monkeypatch.setenv("CLAWTEAM_AGENT_ID", "qa1-id")

    mailbox = MailboxManager("demo")
    task = TaskStore("demo").create(subject="Fix thing", description="Real task", owner="qa1")
    mailbox.send("leader", "qa1", "start now", key=f"task-wake:{task.id}", last_task=task.id)

    def fake_run(command, cwd=None, env=None, session_key=None, total_timeout_seconds=None, progress_stall_timeout_seconds=None, progress_poll_interval_seconds=None):
        TaskStore("demo").update(task.id, status=TaskStatus.completed, caller="qa1")
        return _Completed(returncode=1, stdout="", stderr="502 Upstream request failed")

    monkeypatch.setattr(worker_runtime, "_run_agent_with_progress_watchdog", fake_run)

    result = run_worker_iteration(team_name="demo", agent_name="qa1", base_command=["openclaw"])

    assert result["status"] == "duplicate_terminal"
    assert result["taskId"] == task.id
    assert result["rejectionReason"] == "duplicate_terminal_conflicting_status"
    assert result["terminalStatus"] == "completed"

    updated = TaskStore("demo").get(task.id)
    assert updated is not None
    assert updated.status.value == "completed"
    assert updated.metadata["transition_log"][-1]["accepted"] is False
    assert updated.metadata["transition_log"][-1]["rejectionReason"] == "duplicate_terminal_conflicting_status"


def test_run_worker_iteration_fails_closed_when_agent_returns_success_without_terminal_task_update(monkeypatch, tmp_path):
    _seed_team(tmp_path, monkeypatch)
    monkeypatch.setenv("CLAWTEAM_AGENT_NAME", "qa1")
    monkeypatch.setenv("CLAWTEAM_TEAM_NAME", "demo")
    monkeypatch.setenv("CLAWTEAM_AGENT_ID", "qa1-id")
    monkeypatch.setenv("HOME", str(tmp_path))

    mailbox = MailboxManager("demo")
    task = TaskStore("demo").create(subject="Fix thing", description="Real task", owner="qa1")
    mailbox.send("leader", "qa1", "start now", key=f"task-wake:{task.id}", last_task=task.id)

    transcript_dir = tmp_path / ".openclaw" / "agents" / "main" / "sessions"
    transcript_dir.mkdir(parents=True, exist_ok=True)
    (transcript_dir / "clawteam-demo-qa1.jsonl").write_text(
        '{"type":"message","message":{"role":"tool","content":"ok"}}\n',
        encoding="utf-8",
    )

    monkeypatch.setattr(worker_runtime, "_run_agent_with_progress_watchdog", lambda *args, **kwargs: _Completed(returncode=0, stdout="", stderr=""))
    monkeypatch.setattr(
        worker_runtime,
        "_wait_for_post_exit_settle",
        lambda **kwargs: (TaskStore("demo").get(task.id), False),
    )

    result = run_worker_iteration(team_name="demo", agent_name="qa1", base_command=["openclaw"])

    assert result["status"] == "failed_closed"
    assert result["taskId"] == task.id
    assert result["reason"] == "worker agent turn stalled without terminal task update"
    assert result["sessionKey"] == "clawteam-demo-qa1"

    updated = TaskStore("demo").get(task.id)
    assert updated is not None
    assert updated.status.value == "failed"
    assert updated.locked_by == ""
    assert updated.metadata["failure_kind"] == "complex"
    assert updated.metadata["failure_root_cause"] == "worker agent turn stalled without terminal task update"
    assert "task remained in_progress" in updated.metadata["failure_evidence"]
    assert "transcript_tail:" in updated.metadata["failure_evidence"]


def test_progress_watchdog_raises_when_transcript_stalls(monkeypatch, tmp_path):
    _seed_team(tmp_path, monkeypatch)
    monkeypatch.setenv("HOME", str(tmp_path))

    timeline = iter([0.0, 0.0, 0.6, 1.2])
    monkeypatch.setattr(worker_runtime.time, "monotonic", lambda: next(timeline))
    monkeypatch.setattr(worker_runtime.time, "sleep", lambda _: None)
    monkeypatch.setattr(worker_runtime, "_transcript_progress_marker", lambda session_key: (0, 0))

    killed = {"value": False}

    class DummyProc:
        def __init__(self):
            self.returncode = None

        def poll(self):
            return self.returncode

        def kill(self):
            killed["value"] = True
            self.returncode = -9

        def communicate(self):
            return ("", "")

    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: DummyProc())

    try:
        worker_runtime._run_agent_with_progress_watchdog(
            command=["openclaw", "agent"],
            cwd=None,
            env=os.environ.copy(),
            session_key="clawteam-demo-qa1",
            total_timeout_seconds=900,
            progress_stall_timeout_seconds=1.0,
            progress_poll_interval_seconds=0.01,
        )
        assert False, "expected TimeoutError"
    except TimeoutError as exc:
        assert "stalled without transcript progress" in str(exc)
        assert killed["value"] is True



def test_progress_watchdog_allows_running_process_when_transcript_keeps_growing(monkeypatch, tmp_path):
    _seed_team(tmp_path, monkeypatch)
    monkeypatch.setenv("HOME", str(tmp_path))

    poll_count = {"value": 0}

    class DummyProc:
        def __init__(self):
            self.returncode = None

        def poll(self):
            poll_count["value"] += 1
            if poll_count["value"] >= 3:
                self.returncode = 0
            return self.returncode

        def kill(self):
            self.returncode = -9

        def communicate(self):
            return ("ok", "")

    markers = iter([(0, 0), (1, 10), (2, 20)])
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **kwargs: DummyProc())
    monkeypatch.setattr(worker_runtime, "_transcript_progress_marker", lambda session_key: next(markers, (2, 20)))
    monkeypatch.setattr(worker_runtime.time, "monotonic", lambda: 0.0)
    monkeypatch.setattr(worker_runtime.time, "sleep", lambda _: None)

    result = worker_runtime._run_agent_with_progress_watchdog(
        command=["openclaw", "agent"],
        cwd=None,
        env=os.environ.copy(),
        session_key="clawteam-demo-qa1",
        total_timeout_seconds=900,
        progress_stall_timeout_seconds=1.0,
        progress_poll_interval_seconds=0.01,
    )

    assert result.returncode == 0
    assert result.stdout == "ok"



def test_post_exit_settle_detects_terminal_update_after_success(monkeypatch, tmp_path):
    _seed_team(tmp_path, monkeypatch)
    monkeypatch.setenv("CLAWTEAM_AGENT_NAME", "qa1")
    monkeypatch.setenv("CLAWTEAM_TEAM_NAME", "demo")
    monkeypatch.setenv("CLAWTEAM_AGENT_ID", "qa1-id")

    mailbox = MailboxManager("demo")
    task = TaskStore("demo").create(subject="Fix thing", description="Real task", owner="qa1")
    mailbox.send("leader", "qa1", "start now", key=f"task-wake:{task.id}", last_task=task.id)

    monkeypatch.setattr(
        worker_runtime,
        "_run_agent_with_progress_watchdog",
        lambda *args, **kwargs: _Completed(returncode=0, stdout="", stderr=""),
    )

    def fake_wait_for_post_exit_settle(**kwargs):
        TaskStore("demo").update(task.id, status=TaskStatus.completed, caller="qa1")
        return TaskStore("demo").get(task.id), True

    monkeypatch.setattr(worker_runtime, "_wait_for_post_exit_settle", fake_wait_for_post_exit_settle)

    result = run_worker_iteration(team_name="demo", agent_name="qa1", base_command=["openclaw"])

    assert result["status"] == "dispatched"
    updated = TaskStore("demo").get(task.id)
    assert updated is not None
    assert updated.status == TaskStatus.completed



def test_wait_for_post_exit_settle_returns_false_when_session_goes_silent(monkeypatch, tmp_path):
    _seed_team(tmp_path, monkeypatch)
    task = TaskStore("demo").create(subject="Fix thing", description="Real task", owner="qa1")
    TaskStore("demo").update(task.id, status=TaskStatus.in_progress, caller="qa1")

    timeline = iter([0.0, 0.0, 0.5, 1.1])
    monkeypatch.setattr(worker_runtime.time, "monotonic", lambda: next(timeline))
    monkeypatch.setattr(worker_runtime.time, "sleep", lambda _: None)
    monkeypatch.setattr(worker_runtime, "_transcript_progress_marker", lambda session_key: (0, 0))

    refreshed, settled = worker_runtime._wait_for_post_exit_settle(
        team_name="demo",
        task_id=task.id,
        agent_name="qa1",
        session_key="clawteam-demo-qa1",
        settle_timeout_seconds=5.0,
        poll_interval_seconds=0.01,
        progress_grace_seconds=1.0,
    )

    assert settled is False
    assert refreshed is not None
    assert refreshed.status == TaskStatus.in_progress



def test_subprocess_backend_wraps_openclaw_in_worker_runtime(monkeypatch, tmp_path):
    _seed_team(tmp_path, monkeypatch)
    monkeypatch.setenv("CLAWTEAM_AGENT_NAME", "leader")
    monkeypatch.setenv("CLAWTEAM_TEAM_NAME", "demo")
    monkeypatch.setenv("CLAWTEAM_AGENT_ID", "leader-1")

    captured = {}

    class DummyProc:
        pid = 43210

        def poll(self):
            return None

    def fake_popen(shell_cmd, shell=None, env=None, stdout=None, stderr=None, cwd=None):
        captured["shell_cmd"] = shell_cmd
        captured["env"] = env
        captured["cwd"] = cwd
        return DummyProc()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    backend = SubprocessBackend()
    message = backend.spawn(
        command=["openclaw"],
        agent_name="qa1",
        agent_id="qa1-id",
        agent_type="general-purpose",
        team_name="demo",
        prompt="startup rules",
        cwd=str(tmp_path / "ws"),
    )

    assert "spawned as subprocess" in message
    assert "worker run demo --agent qa1 --command openclaw" in captured["shell_cmd"]
    assert "--startup-prompt-file" in captured["shell_cmd"]
