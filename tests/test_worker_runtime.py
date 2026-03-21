from __future__ import annotations

import os
import subprocess
from pathlib import Path

from clawteam.spawn.subprocess_backend import SubprocessBackend
from clawteam.team.mailbox import MailboxManager
from clawteam.team.manager import TeamManager
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

    def fake_run(command, cwd=None, env=None, capture_output=None, text=None):
        called["command"] = command
        called["cwd"] = cwd
        called["env"] = env
        return _Completed()

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = run_worker_iteration(team_name="demo", agent_name="qa1", base_command=["openclaw"])

    assert result["status"] == "dispatched"
    assert result["taskId"] == task.id
    assert result["messages"] == 1
    assert result["acked"] == 1
    assert called["command"][:2] == ["openclaw", "agent"]
    assert "--session-id" in called["command"]
    assert f"clawteam-demo-qa1" in called["command"]

    updated = TaskStore("demo").get(task.id)
    assert updated is not None
    assert updated.status.value == "in_progress"
    assert updated.locked_by == "qa1"

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

    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: _Completed())

    result = run_worker_iteration(team_name="demo", agent_name="qa1", base_command=["openclaw"])

    assert result["acked"] == 1
    remaining = mailbox.peek("qa1")
    assert len(remaining) == 1
    assert remaining[0].request_id == other.request_id

    acks = mailbox.receive("leader")
    assert len(acks) == 1
    assert acks[0].request_id == wake.request_id


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

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = run_worker_iteration(team_name="demo", agent_name="qa1", base_command=["openclaw"])

    assert result["status"] == "waiting_for_wake"
    assert result["acked"] == 0
    assert result["taskId"] == task.id
    assert called["ran"] is False

    updated = TaskStore("demo").get(task.id)
    assert updated is not None
    assert updated.status.value == "pending"
    assert updated.locked_by == ""

    remaining = mailbox.peek("qa1")
    assert len(remaining) == 1
    assert remaining[0].key == "note:1"


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

    monkeypatch.setattr(subprocess, "run", fake_run)

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
