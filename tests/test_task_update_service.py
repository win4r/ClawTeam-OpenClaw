from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from clawteam.execution.state import WRITEBACK_APPLIED

from clawteam.runtime.orchestrator import RuntimeOrchestrator
from clawteam.services.task_update_service import (
    FailureRepairPacket,
    TaskUpdateContext,
    TaskUpdateEffects,
    TaskUpdatePlan,
    TaskUpdateRequest,
    TaskUpdateResult,
    TaskUpdateValidationError,
    _build_dependency_completion_message,
    _infer_runtime_handoff_from_setup_sections,
    execute_task_update,
    execute_task_update_effects,
)
from clawteam.team.manager import TeamManager
from clawteam.team.models import TaskStatus
from clawteam.team.tasks import TaskStore, TransitionApplyResult
from clawteam.workspace.git import probe_remote_head, resolve_remote_probe_target


def _git_run(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _init_repo_with_baseline(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git_run(repo, "init")
    _git_run(repo, "config", "user.name", "Test User")
    _git_run(repo, "config", "user.email", "test@example.com")
    (repo / "app.py").write_text("print('baseline')\n", encoding="utf-8")
    _git_run(repo, "add", "app.py")
    _git_run(repo, "commit", "-m", "baseline")
    return repo, _git_run(repo, "rev-parse", "HEAD")


def test_task_update_result_explicit_transition_case_wins_over_apply_result(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))

    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    TeamManager.add_member("demo", "dev1", "dev1-id", agent_type="general-purpose")
    task = TaskStore("demo").create("Implement fix", owner="dev1")

    result = TaskUpdateResult(
        task=task,
        plan=TaskUpdatePlan(metadata_to_apply={}, dependent_ids_to_wake=[], failed_targets_to_wake=[]),
        effects=TaskUpdateEffects(wake=None, auto_releases=[], failure_notice=None),
        transition_case="explicit_case",
        apply_result=TransitionApplyResult(
            task=task,
            accepted=True,
            case_name="reopen_task",
        ),
    )

    assert result.transition_case == "explicit_case"



def test_task_update_result_defaults_transition_case_from_apply_result(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))

    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    TeamManager.add_member("demo", "dev1", "dev1-id", agent_type="general-purpose")
    task = TaskStore("demo").create("Implement fix", owner="dev1")

    result = TaskUpdateResult(
        task=task,
        plan=TaskUpdatePlan(metadata_to_apply={}, dependent_ids_to_wake=[], failed_targets_to_wake=[]),
        effects=TaskUpdateEffects(wake=None, auto_releases=[], failure_notice=None),
        apply_result=TransitionApplyResult(
            task=task,
            accepted=True,
            case_name="reopen_task",
        ),
    )

    assert result.transition_case == "reopen_task"



def test_execute_task_update_builds_full_result_and_updates_store(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))

    notices: list[dict[str, str]] = []

    def fake_notifier(team, task, caller):
        notices.append({
            "team": team,
            "task": task.id,
            "caller": caller,
            "kind": task.metadata.get("failure_kind", "complex"),
        })
        return {
            "failureNotice": "sent",
            "failureKind": task.metadata.get("failure_kind", "complex"),
        }

    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    TeamManager.add_member("demo", "dev1", "dev1-id", agent_type="general-purpose")
    TeamManager.add_member("demo", "qa1", "qa1-id", agent_type="general-purpose")

    store = TaskStore("demo")
    impl = store.create("Implement fix", owner="dev1")
    qa = store.create("Regression QA", owner="qa1", metadata={"on_fail": [impl.id]})

    monkeypatch.setattr(
        "clawteam.services.task_update_service.wake_tasks_to_pending",
        lambda *args, **kwargs: [{"taskId": impl.id, "owner": "dev1", "respawned": False}],
    )

    result = execute_task_update(
        task_id=qa.id,
        caller="qa1",
        ctx=TaskUpdateContext(
            store=store,
            team="demo",
            runtime=RuntimeOrchestrator(team="demo"),
            release_notifier=lambda team, task, caller, message: {"messageSent": True, "message": message},
            failure_notifier=fake_notifier,
        ),
        request=TaskUpdateRequest(
            status=TaskStatus.failed,
            owner=None,
            subject=None,
            description=None,
            add_blocks=None,
            add_blocked_by=None,
            add_on_fail=None,
            failure_kind="complex",
            failure_note=None,
            failure_root_cause="ownership unclear",
            failure_evidence="cross-cutting regression",
            failure_recommended_next_owner="leader",
            failure_recommended_action="triage owner",
            execution_id=None,
            wake_owner=False,
            message="",
            force=False,
        ),
    )

    assert result.task.status == TaskStatus.failed
    assert result.apply_result is not None
    assert result.apply_result.case_name == "terminal_writeback_without_execution_scope"
    assert result.transition_case == result.apply_result.case_name
    assert result.plan.failed_targets_to_wake == []
    assert result.effects.failure_notice is not None
    assert result.effects.failure_notice["failureNotice"] == "sent"
    assert notices == [{"team": "demo", "task": qa.id, "caller": "qa1", "kind": "complex"}]


def test_execute_task_update_persists_explicit_failed_task_metadata(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))

    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    TeamManager.add_member("demo", "qa1", "qa1-id", agent_type="general-purpose")

    store = TaskStore("demo")
    task = store.create("Regression QA", owner="qa1")
    task = store.update(task.id, status=TaskStatus.in_progress, caller="qa1")

    result = execute_task_update(
        task_id=task.id,
        caller="qa1",
        ctx=TaskUpdateContext(
            store=store,
            team="demo",
            runtime=RuntimeOrchestrator(team="demo"),
            release_notifier=lambda team, task, caller, message: None,
            failure_notifier=lambda team, task, caller: None,
        ),
        request=TaskUpdateRequest(
            status=TaskStatus.failed,
            owner=None,
            subject=None,
            description=None,
            add_blocks=None,
            add_blocked_by=None,
            add_on_fail=None,
            failure_kind="complex",
            failure_note=None,
            failure_root_cause="qa found a reproducible bug",
            failure_evidence="board still renders 4 tracks",
            failure_recommended_next_owner="dev2",
            failure_recommended_action="fix board layout and rerun qa",
            qa_result_status="fail",
            qa_risk_note="main path still broken",
            failure_repair_packet=FailureRepairPacket(
                target_files=["clawteam/board/static/index.html"],
            ),
            execution_id=task.active_execution_id,
            wake_owner=False,
            message="",
            force=False,
        ),
    )

    assert result.task.metadata["qa_result_status"] == "fail"
    assert result.task.metadata["qa_risk_note"] == "main path still broken"
    assert result.task.metadata["failure_target_files"] == ["clawteam/board/static/index.html"]


def test_execute_task_update_allows_late_completed_to_recover_watchdog_failure(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))

    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    TeamManager.add_member("demo", "dev1", "dev1-id", agent_type="general-purpose")

    store = TaskStore("demo")
    task = store.create("Implement fix", owner="dev1")
    task = store.update(
        task.id,
        status=TaskStatus.failed,
        caller="dev1",
        metadata={
            "failure_kind": "complex",
            "failure_root_cause": "worker agent turn stalled without terminal task update",
            "failure_evidence": "watchdog",
            "session_key": "clawteam-demo-dev1",
            "stall_phase": "post_exit_without_terminal_task_update",
            "watchdog_decision_at": task.updated_at,
        },
    )

    result = execute_task_update(
        task_id=task.id,
        caller="dev1",
        ctx=TaskUpdateContext(
            store=store,
            team="demo",
            runtime=RuntimeOrchestrator(team="demo"),
            release_notifier=lambda team, task, caller, message: None,
            failure_notifier=lambda team, task, caller: None,
        ),
        request=TaskUpdateRequest(
            status=TaskStatus.completed,
            owner=None,
            subject=None,
            description=None,
            add_blocks=None,
            add_blocked_by=None,
            add_on_fail=None,
            failure_kind=None,
            failure_note=None,
            failure_root_cause=None,
            failure_evidence=None,
            failure_recommended_next_owner=None,
            failure_recommended_action=None,
            execution_id=None,
            wake_owner=False,
            message="",
            force=False,
        ),
    )

    assert result.task.status == TaskStatus.completed
    assert result.apply_result is not None
    assert result.apply_result.case_name == "recover_watchdog_failed_completion"
    assert result.transition_case == "recover_watchdog_failed_completion"
    assert result.task.metadata["recovered_from_watchdog_failure"] is True
    assert result.task.metadata["watchdog_recovered_by"] == "dev1"
    assert "failure_root_cause" not in result.task.metadata
    assert "failure_evidence" not in result.task.metadata



def test_execute_task_update_allows_missing_execution_id_for_manual_claim_owner(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))

    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    TeamManager.add_member("demo", "dev1", "dev1-id", agent_type="general-purpose")

    store = TaskStore("demo")
    task = store.create("Implement fix", owner="dev1")
    store.update(task.id, status=TaskStatus.in_progress, caller="dev1")

    result = execute_task_update(
        task_id=task.id,
        caller="dev1",
        ctx=TaskUpdateContext(
            store=store,
            team="demo",
            runtime=RuntimeOrchestrator(team="demo"),
            release_notifier=lambda team, task, caller, message: None,
            failure_notifier=lambda team, task, caller: None,
        ),
        request=TaskUpdateRequest(
            status=TaskStatus.completed,
            owner=None,
            subject=None,
            description=None,
            add_blocks=None,
            add_blocked_by=None,
            add_on_fail=None,
            failure_kind=None,
            failure_note=None,
            failure_root_cause=None,
            failure_evidence=None,
            failure_recommended_next_owner=None,
            failure_recommended_action=None,
            execution_id=None,
            wake_owner=False,
            message="",
            force=False,
        ),
    )

    assert result.task.status == TaskStatus.completed
    assert result.apply_result is not None
    assert result.apply_result.case_name == "terminal_writeback_without_execution_scope"



def test_execute_task_update_allows_terminal_update_without_execution_id_when_no_active_execution(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))

    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    TeamManager.add_member("demo", "dev1", "dev1-id", agent_type="general-purpose")

    store = TaskStore("demo")
    task = store.create("Implement fix", owner="dev1")

    result = execute_task_update(
        task_id=task.id,
        caller="dev1",
        ctx=TaskUpdateContext(
            store=store,
            team="demo",
            runtime=RuntimeOrchestrator(team="demo"),
            release_notifier=lambda team, task, caller, message: None,
            failure_notifier=lambda team, task, caller: None,
        ),
        request=TaskUpdateRequest(
            status=TaskStatus.completed,
            owner=None,
            subject=None,
            description=None,
            add_blocks=None,
            add_blocked_by=None,
            add_on_fail=None,
            failure_kind=None,
            failure_note=None,
            failure_root_cause=None,
            failure_evidence=None,
            failure_recommended_next_owner=None,
            failure_recommended_action=None,
            execution_id=None,
            wake_owner=False,
            message="",
            force=False,
        ),
    )

    assert result.task.status == TaskStatus.completed
    assert result.apply_result is not None
    assert result.apply_result.case_name == "terminal_writeback_without_execution_scope"



def test_execute_task_update_execution_scoped_completion_persists_writeback_applied(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))

    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    TeamManager.add_member("demo", "dev1", "dev1-id", agent_type="general-purpose")

    store = TaskStore("demo")
    task = store.create("Implement fix", owner="dev1")
    claimed = store.claim_execution(task.id, caller="dev1")
    assert claimed is not None

    result = execute_task_update(
        task_id=task.id,
        caller="dev1",
        ctx=TaskUpdateContext(
            store=store,
            team="demo",
            runtime=RuntimeOrchestrator(team="demo"),
            release_notifier=lambda team, task, caller, message: None,
            failure_notifier=lambda team, task, caller: None,
        ),
        request=TaskUpdateRequest(
            status=TaskStatus.completed,
            owner=None,
            subject=None,
            description=None,
            add_blocks=None,
            add_blocked_by=None,
            add_on_fail=None,
            failure_kind=None,
            failure_note=None,
            failure_root_cause=None,
            failure_evidence=None,
            failure_recommended_next_owner=None,
            failure_recommended_action=None,
            execution_id=claimed.task.active_execution_id,
            wake_owner=False,
            message="",
            force=False,
        ),
    )

    assert result.apply_result is not None
    assert result.apply_result.case_name == "execution_scoped_terminal_writeback"
    assert result.task.metadata["execution"]["state"] == WRITEBACK_APPLIED


def test_execute_task_update_effects_preserves_execution_metadata_when_adding_setup_runtime_handoff(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))

    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    TeamManager.add_member("demo", "config1", "config1-id", agent_type="general-purpose")
    TeamManager.add_member("demo", "dev1", "dev1-id", agent_type="general-purpose")

    store = TaskStore("demo")
    setup = store.create(
        "Prepare repo, branch, env, and runnable baseline",
        owner="config1",
        metadata={"message_type": "SETUP_RESULT"},
    )
    claimed = store.claim_execution(setup.id, caller="config1")
    assert claimed is not None
    result = execute_task_update(
        task_id=setup.id,
        caller="config1",
        ctx=TaskUpdateContext(
            store=store,
            team="demo",
            runtime=RuntimeOrchestrator(team="demo"),
            release_notifier=lambda team, task, caller, message: None,
            failure_notifier=lambda team, task, caller: None,
        ),
        request=TaskUpdateRequest(
            status=TaskStatus.completed,
            owner=None,
            subject=None,
            description=(
                "SETUP_RESULT\n"
                "status: completed\n"
                "remote_status: cached_only\n"
                "remote_head: 03bdc8f\n"
                "detached_worktree: /tmp/demo/.worktrees/setup-123\n"
                "detached_head: 9e8f87f\n"
                "install:\n"
                "- python3 -m venv .venv && source .venv/bin/activate && python -m pip install -e '.[dev]' -> success\n"
                "baseline_validation:\n"
                "- source .venv/bin/activate && pytest -q -> 336 passed in 2.30s\n"
                "known_limitations:\n"
                "- none\n"
                "next_action: handoff to implement"
            ),
            add_blocks=None,
            add_blocked_by=None,
            add_on_fail=None,
            failure_kind=None,
            failure_note=None,
            failure_root_cause=None,
            failure_evidence=None,
            failure_recommended_next_owner=None,
            failure_recommended_action=None,
            execution_id=claimed.task.active_execution_id,
            wake_owner=False,
            message="",
            force=False,
        ),
    )
    setup = result.task
    impl = store.create("Implement fix", owner="dev1", description="Original implement brief")

    monkeypatch.setattr(
        "clawteam.services.task_update_service.wake_tasks_to_pending",
        lambda *args, **kwargs: [{"taskId": impl.id, "owner": "dev1", "respawned": False}],
    )

    execute_task_update_effects(
        ctx=TaskUpdateContext(
            store=store,
            team="demo",
            runtime=RuntimeOrchestrator(team="demo"),
            release_notifier=lambda team, task, caller, message: {"messageSent": True, "message": message},
            failure_notifier=lambda team, task, caller: None,
        ),
        task=setup,
        caller="config1",
        wake_owner=False,
        message="",
        dependent_ids_to_wake=[impl.id],
        failed_targets_to_wake=[],
    )

    updated_setup = store.get(setup.id)
    assert updated_setup is not None
    assert updated_setup.metadata["execution"]["state"] == WRITEBACK_APPLIED
    assert updated_setup.metadata["runtime_handoff"]["detached_worktree"] == "/tmp/demo/.worktrees/setup-123"


def test_execute_task_update_rejects_stale_execution_writeback(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))

    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    TeamManager.add_member("demo", "dev1", "dev1-id", agent_type="general-purpose")

    store = TaskStore("demo")
    task = store.create("Implement fix", owner="dev1")
    first_claim = store.update(task.id, status=TaskStatus.in_progress, caller="dev1")
    stale_execution_id = first_claim.active_execution_id
    store.update(task.id, status=TaskStatus.pending, caller="dev1")
    store.update(task.id, status=TaskStatus.in_progress, caller="dev1")

    try:
        execute_task_update(
            task_id=task.id,
            caller="dev1",
            ctx=TaskUpdateContext(
                store=store,
                team="demo",
                runtime=RuntimeOrchestrator(team="demo"),
                release_notifier=lambda team, task, caller, message: None,
                failure_notifier=lambda team, task, caller: None,
            ),
            request=TaskUpdateRequest(
                status=TaskStatus.completed,
                owner=None,
                subject=None,
                description=None,
                add_blocks=None,
                add_blocked_by=None,
                add_on_fail=None,
                failure_kind=None,
                failure_note=None,
                failure_root_cause=None,
                failure_evidence=None,
                failure_recommended_next_owner=None,
                failure_recommended_action=None,
                execution_id=stale_execution_id,
                wake_owner=False,
                message="",
                force=False,
            ),
        )
    except RuntimeError as exc:
        assert "stale_execution" in str(exc)
    else:
        raise AssertionError("expected stale execution writeback to be rejected")

    rejected = store.get(task.id)
    assert rejected is not None
    assert rejected.metadata["transition_log"][-1]["case"] == "execution_scoped_terminal_writeback"
    assert rejected.metadata["transition_log"][-1]["accepted"] is False
    assert rejected.metadata["transition_log"][-1]["rejectionReason"] == "stale_execution"



def test_execute_task_update_rejects_setup_completion_without_setup_result_header(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))

    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    TeamManager.add_member("demo", "config1", "config1-id", agent_type="general-purpose")

    store = TaskStore("demo")
    task = store.create(
        "Prepare repo, branch, env, and runnable baseline",
        owner="config1",
        metadata={
            "template_stage": "setup",
            "message_type": "SETUP_RESULT",
            "required_sections": [
                "status",
                "remote_status",
                "remote_head",
                "detached_worktree",
                "detached_head",
                "install",
                "baseline_validation",
                "known_limitations",
                "next_action",
            ],
        },
    )
    claimed = store.update(task.id, status=TaskStatus.in_progress, caller="config1")

    try:
        execute_task_update(
            task_id=task.id,
            caller="config1",
            ctx=TaskUpdateContext(
                store=store,
                team="demo",
                runtime=RuntimeOrchestrator(team="demo"),
                release_notifier=lambda team, task, caller, message: None,
                failure_notifier=lambda team, task, caller: None,
            ),
            request=TaskUpdateRequest(
                status=TaskStatus.completed,
                owner=None,
                subject=None,
                description="status: completed",
                add_blocks=None,
                add_blocked_by=None,
                add_on_fail=None,
                failure_kind=None,
                failure_note=None,
                failure_root_cause=None,
                failure_evidence=None,
                failure_recommended_next_owner=None,
                failure_recommended_action=None,
                execution_id=claimed.active_execution_id,
                wake_owner=False,
                message="",
                force=False,
            ),
        )
    except Exception as exc:
        assert "SETUP_RESULT header" in str(exc)
    else:
        raise AssertionError("expected setup completion header rejection")


def test_execute_task_update_rejects_setup_completion_with_invalid_remote_head(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))

    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    TeamManager.add_member("demo", "config1", "config1-id", agent_type="general-purpose")

    store = TaskStore("demo")
    task = store.create(
        "Prepare repo, branch, env, and runnable baseline",
        owner="config1",
        metadata={
            "template_stage": "setup",
            "message_type": "SETUP_RESULT",
            "required_sections": [
                "status", "remote_status", "remote_head", "detached_worktree", "detached_head",
                "install", "baseline_validation", "known_limitations", "next_action",
            ],
        },
    )
    claimed = store.update(task.id, status=TaskStatus.in_progress, caller="config1")

    bad = """SETUP_RESULT
status: completed
remote_status: cached_only
remote_head: not-a-sha
detached_worktree: /tmp/demo-detached
detached_head: 51a0127
install:
- python -m pip install -e .[dev] -> success
baseline_validation:
- pytest tests/test_config.py -q -> 10 passed
known_limitations:
- none
next_action: handoff
"""

    try:
        execute_task_update(
            task_id=task.id,
            caller="config1",
            ctx=TaskUpdateContext(store=store, team="demo", runtime=RuntimeOrchestrator(team="demo"), release_notifier=lambda *a, **k: None, failure_notifier=lambda *a, **k: None),
            request=TaskUpdateRequest(status=TaskStatus.completed, owner=None, subject=None, description=bad, add_blocks=None, add_blocked_by=None, add_on_fail=None, failure_kind=None, failure_note=None, failure_root_cause=None, failure_evidence=None, failure_recommended_next_owner=None, failure_recommended_action=None, execution_id=claimed.active_execution_id, wake_owner=False, message="", force=False),
        )
    except Exception as exc:
        assert "remote_head" in str(exc)
    else:
        raise AssertionError("expected setup remote_head rejection")


def test_execute_task_update_rejects_setup_completion_without_ls_remote_evidence_for_confirmed_latest(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))

    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    TeamManager.add_member("demo", "config1", "config1-id", agent_type="general-purpose")

    store = TaskStore("demo")
    task = store.create(
        "Prepare repo, branch, env, and runnable baseline",
        owner="config1",
        metadata={
            "template_stage": "setup",
            "message_type": "SETUP_RESULT",
            "required_sections": [
                "status", "remote_status", "remote_head", "detached_worktree", "detached_head",
                "install", "baseline_validation", "known_limitations", "next_action",
            ],
        },
    )
    claimed = store.update(task.id, status=TaskStatus.in_progress, caller="config1")

    bad = """SETUP_RESULT
status: completed
remote_status: confirmed_latest
remote_head: 51a0127
detached_worktree: /tmp/demo-detached
detached_head: 51a0127
install:
- python -m pip install -e .[dev] -> success
baseline_validation:
- pytest tests/test_config.py -q -> 10 passed
known_limitations:
- none
next_action: handoff
"""

    try:
        execute_task_update(
            task_id=task.id,
            caller="config1",
            ctx=TaskUpdateContext(store=store, team="demo", runtime=RuntimeOrchestrator(team="demo"), release_notifier=lambda *a, **k: None, failure_notifier=lambda *a, **k: None),
            request=TaskUpdateRequest(status=TaskStatus.completed, owner=None, subject=None, description=bad, add_blocks=None, add_blocked_by=None, add_on_fail=None, failure_kind=None, failure_note=None, failure_root_cause=None, failure_evidence=None, failure_recommended_next_owner=None, failure_recommended_action=None, execution_id=claimed.active_execution_id, wake_owner=False, message="", force=False),
        )
    except Exception as exc:
        assert "ls-remote" in str(exc)
    else:
        raise AssertionError("expected setup ls-remote rejection")


def test_execute_task_update_rejects_setup_completion_when_confirmed_remote_head_differs_from_detached_head(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))

    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    TeamManager.add_member("demo", "config1", "config1-id", agent_type="general-purpose")

    store = TaskStore("demo")
    task = store.create(
        "Prepare repo, branch, env, and runnable baseline",
        owner="config1",
        metadata={
            "template_stage": "setup",
            "message_type": "SETUP_RESULT",
            "required_sections": [
                "status", "remote_status", "remote_head", "detached_worktree", "detached_head",
                "install", "baseline_validation", "known_limitations", "next_action",
            ],
        },
    )
    claimed = store.update(task.id, status=TaskStatus.in_progress, caller="config1")

    bad = """SETUP_RESULT
status: completed
remote_status: confirmed_latest
remote_head: 51a0127
detached_worktree: /tmp/demo-detached
detached_head: 41b9910
install:
- python -m pip install -e .[dev] -> success
baseline_validation:
- git ls-remote --heads flyzorro main -> 51a0127 refs/heads/main
- pytest tests/test_config.py -q -> 10 passed
known_limitations:
- none
next_action: handoff
"""

    with pytest.raises(TaskUpdateValidationError, match="detached_head to equal confirmed remote_head"):
        execute_task_update(
            task_id=task.id,
            caller="config1",
            ctx=TaskUpdateContext(store=store, team="demo", runtime=RuntimeOrchestrator(team="demo"), release_notifier=lambda *a, **k: None, failure_notifier=lambda *a, **k: None),
            request=TaskUpdateRequest(status=TaskStatus.completed, owner=None, subject=None, description=bad, add_blocks=None, add_blocked_by=None, add_on_fail=None, failure_kind=None, failure_note=None, failure_root_cause=None, failure_evidence=None, failure_recommended_next_owner=None, failure_recommended_action=None, execution_id=claimed.active_execution_id, wake_owner=False, message="", force=False),
        )



def test_execute_task_update_rejects_setup_completion_without_command_like_baseline_evidence(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))

    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    TeamManager.add_member("demo", "config1", "config1-id", agent_type="general-purpose")

    store = TaskStore("demo")
    task = store.create(
        "Prepare repo, branch, env, and runnable baseline",
        owner="config1",
        metadata={
            "template_stage": "setup",
            "message_type": "SETUP_RESULT",
            "required_sections": [
                "status", "remote_status", "remote_head", "detached_worktree", "detached_head",
                "install", "baseline_validation", "known_limitations", "next_action",
            ],
        },
    )
    claimed = store.update(task.id, status=TaskStatus.in_progress, caller="config1")

    bad = """SETUP_RESULT
status: completed
remote_status: cached_only
remote_head: 51a0127
detached_worktree: /tmp/demo-detached
detached_head: 51a0127
install:
- python -m pip install -e .[dev] -> success
baseline_validation:
looks runnable enough
known_limitations:
- none
next_action: handoff
"""

    try:
        execute_task_update(
            task_id=task.id,
            caller="config1",
            ctx=TaskUpdateContext(store=store, team="demo", runtime=RuntimeOrchestrator(team="demo"), release_notifier=lambda *a, **k: None, failure_notifier=lambda *a, **k: None),
            request=TaskUpdateRequest(status=TaskStatus.completed, owner=None, subject=None, description=bad, add_blocks=None, add_blocked_by=None, add_on_fail=None, failure_kind=None, failure_note=None, failure_root_cause=None, failure_evidence=None, failure_recommended_next_owner=None, failure_recommended_action=None, execution_id=claimed.active_execution_id, wake_owner=False, message="", force=False),
        )
    except Exception as exc:
        assert "baseline_validation evidence" in str(exc)
    else:
        raise AssertionError("expected setup baseline evidence rejection")


def test_execute_task_update_accepts_valid_setup_completion(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))

    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    TeamManager.add_member("demo", "config1", "config1-id", agent_type="general-purpose")

    store = TaskStore("demo")
    task = store.create(
        "Prepare repo, branch, env, and runnable baseline",
        owner="config1",
        metadata={
            "template_stage": "setup",
            "message_type": "SETUP_RESULT",
            "required_sections": [
                "status",
                "remote_status",
                "remote_head",
                "detached_worktree",
                "detached_head",
                "install",
                "baseline_validation",
                "known_limitations",
                "next_action",
            ],
        },
    )
    claimed = store.update(task.id, status=TaskStatus.in_progress, caller="config1")

    valid = """SETUP_RESULT
status: completed
remote_status: confirmed_latest
remote_head: 51a0127
detached_worktree: /tmp/demo-detached
detached_head: 51a0127
install:
- python -m pip install -e .[dev] -> success
baseline_validation:
- git ls-remote --heads flyzorro main -> 51a0127 refs/heads/main
- pytest tests/test_config.py tests/test_models.py -q -> 29 passed
known_limitations:
- none
next_action: handoff to implement
"""

    result = execute_task_update(
        task_id=task.id,
        caller="config1",
        ctx=TaskUpdateContext(
            store=store,
            team="demo",
            runtime=RuntimeOrchestrator(team="demo"),
            release_notifier=lambda team, task, caller, message: None,
            failure_notifier=lambda team, task, caller: None,
        ),
        request=TaskUpdateRequest(
            status=TaskStatus.completed,
            owner=None,
            subject=None,
            description=valid,
            add_blocks=None,
            add_blocked_by=None,
            add_on_fail=None,
            failure_kind=None,
            failure_note=None,
            failure_root_cause=None,
            failure_evidence=None,
            failure_recommended_next_owner=None,
            failure_recommended_action=None,
            execution_id=claimed.active_execution_id,
            wake_owner=False,
            message="",
            force=False,
        ),
    )

    assert result.task.status == TaskStatus.completed
    assert result.task.description.startswith("SETUP_RESULT")


def test_execute_task_update_rejects_dev_completion_without_substantive_repo_change(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))

    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    TeamManager.add_member("demo", "dev1", "dev1-id", agent_type="general-purpose")

    repo, detached_head = _init_repo_with_baseline(tmp_path)
    store = TaskStore("demo")
    task = store.create(
        "Implement assigned change slice A with real validation",
        owner="dev1",
        metadata={
            "template_stage": "implement",
            "message_type": "DEV_RESULT",
            "required_sections": ["status", "summary", "changed_files", "validation", "known_issues", "next_action"],
            "setup_runtime_handoff": {
                "detached_worktree": str(repo),
                "detached_head": detached_head,
            },
        },
    )
    claimed = store.update(task.id, status=TaskStatus.in_progress, caller="dev1")

    bad = """DEV_RESULT
status: completed
summary: rechecked the repo and baseline
changed_files:
- app.py
validation:
- pytest -q -> baseline still passes
known_issues:
- none
next_action: handoff to qa
"""

    with pytest.raises(TaskUpdateValidationError, match="declared changed_file"):
        execute_task_update(
            task_id=task.id,
            caller="dev1",
            ctx=TaskUpdateContext(store=store, team="demo", runtime=RuntimeOrchestrator(team="demo"), release_notifier=lambda *a, **k: None, failure_notifier=lambda *a, **k: None),
            request=TaskUpdateRequest(status=TaskStatus.completed, owner=None, subject=None, description=bad, add_blocks=None, add_blocked_by=None, add_on_fail=None, failure_kind=None, failure_note=None, failure_root_cause=None, failure_evidence=None, failure_recommended_next_owner=None, failure_recommended_action=None, execution_id=claimed.active_execution_id, wake_owner=False, message="", force=False),
        )


def test_execute_task_update_accepts_dev_completion_with_real_repo_change(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))

    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    TeamManager.add_member("demo", "dev1", "dev1-id", agent_type="general-purpose")

    repo, detached_head = _init_repo_with_baseline(tmp_path)
    (repo / "app.py").write_text("print('implemented change')\n", encoding="utf-8")
    _git_run(repo, "commit", "-am", "implement change")

    store = TaskStore("demo")
    task = store.create(
        "Implement assigned change slice A with real validation",
        owner="dev1",
        metadata={
            "template_stage": "implement",
            "message_type": "DEV_RESULT",
            "required_sections": ["status", "summary", "changed_files", "validation", "known_issues", "next_action"],
            "setup_runtime_handoff": {
                "detached_worktree": str(repo),
                "detached_head": detached_head,
            },
        },
    )
    claimed = store.update(task.id, status=TaskStatus.in_progress, caller="dev1")

    good = """DEV_RESULT
status: completed
summary: implemented the backend change
changed_files:
- app.py
validation:
- python app.py -> implemented change
known_issues:
- none
next_action: handoff to qa
"""

    result = execute_task_update(
        task_id=task.id,
        caller="dev1",
        ctx=TaskUpdateContext(store=store, team="demo", runtime=RuntimeOrchestrator(team="demo"), release_notifier=lambda *a, **k: None, failure_notifier=lambda *a, **k: None),
        request=TaskUpdateRequest(status=TaskStatus.completed, owner=None, subject=None, description=good, add_blocks=None, add_blocked_by=None, add_on_fail=None, failure_kind=None, failure_note=None, failure_root_cause=None, failure_evidence=None, failure_recommended_next_owner=None, failure_recommended_action=None, execution_id=claimed.active_execution_id, wake_owner=False, message="", force=False),
    )

    assert result.task.status == TaskStatus.completed
    assert result.task.description.startswith("DEV_RESULT")


def test_resolve_remote_probe_target_prefers_current_branch_mapping(tmp_path):
    repo, _ = _init_repo_with_baseline(tmp_path)
    _git_run(repo, "remote", "add", "origin", "https://example.com/origin.git")
    _git_run(repo, "remote", "add", "flyzorro", "https://example.com/flyzorro.git")
    _git_run(repo, "config", "branch.main.remote", "origin")
    _git_run(repo, "config", "branch.main.merge", "refs/heads/main")

    target = resolve_remote_probe_target(repo)

    assert target.remote == "origin"
    assert target.branch == "main"
    assert "branch.main.remote/merge -> origin/main" in target.evidence


def test_resolve_remote_probe_target_prefers_launch_time_mapping_over_branch_mapping(tmp_path):
    repo, _ = _init_repo_with_baseline(tmp_path)
    _git_run(repo, "remote", "add", "origin", "https://example.com/origin.git")
    _git_run(repo, "remote", "add", "flyzorro", "https://example.com/flyzorro.git")
    _git_run(repo, "config", "branch.main.remote", "origin")
    _git_run(repo, "config", "branch.main.merge", "refs/heads/main")
    _git_run(repo, "config", "clawteam.targetRemote", "flyzorro")
    _git_run(repo, "config", "clawteam.targetBranch", "refs/heads/release")

    target = resolve_remote_probe_target(repo)

    assert target.remote == "flyzorro"
    assert target.branch == "release"
    assert "clawteam.targetRemote/clawteam.targetBranch" in target.evidence


def test_resolve_remote_probe_target_fails_closed_on_ambiguous_remotes(tmp_path):
    repo, _ = _init_repo_with_baseline(tmp_path)
    _git_run(repo, "remote", "add", "origin", "https://example.com/origin.git")
    _git_run(repo, "remote", "add", "flyzorro", "https://example.com/flyzorro.git")

    with pytest.raises(Exception) as exc:
        resolve_remote_probe_target(repo)

    assert "unable to resolve setup probe target unambiguously" in str(exc.value)


def test_probe_remote_head_classifies_timeout_as_cached_only(monkeypatch, tmp_path):
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=kwargs.get("args", args[0] if args else ["git"]), timeout=30)

    import subprocess

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = probe_remote_head(tmp_path, remote="flyzorro", branch="main", timeout_seconds=30)

    assert result.remote_status == "cached_only"
    assert result.remote_head == "none"
    assert "timed out after 30s" in result.evidence
    assert "git ls-remote --heads flyzorro main" in result.evidence


def test_probe_remote_head_classifies_command_failure_as_unreachable(monkeypatch, tmp_path):
    def fake_run(*args, **kwargs):
        raise subprocess.CalledProcessError(returncode=128, cmd=["git"], stderr="Could not resolve host")

    import subprocess

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = probe_remote_head(tmp_path, remote="flyzorro", branch="main", timeout_seconds=30)

    assert result.remote_status == "unreachable"
    assert result.remote_head == "none"
    assert "Could not resolve host" in result.evidence


def test_probe_remote_head_classifies_success_as_confirmed_latest(monkeypatch, tmp_path):
    class Completed:
        def __init__(self):
            self.stdout = "51a0127\trefs/heads/main\n"

    def fake_run(*args, **kwargs):
        return Completed()

    import subprocess

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = probe_remote_head(tmp_path, remote="flyzorro", branch="main", timeout_seconds=30)

    assert result.remote_status == "confirmed_latest"
    assert result.remote_head == "51a0127"
    assert "51a0127\trefs/heads/main" in result.evidence


def test_execute_task_update_reopen_with_patch_preserves_transition_result(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))

    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    TeamManager.add_member("demo", "dev1", "dev1-id", agent_type="general-purpose")

    store = TaskStore("demo")
    task = store.create("Implement fix", owner="dev1")
    task = store.update(task.id, status=TaskStatus.failed, caller="dev1")

    result = execute_task_update(
        task_id=task.id,
        caller="dev1",
        ctx=TaskUpdateContext(
            store=store,
            team="demo",
            runtime=RuntimeOrchestrator(team="demo"),
            release_notifier=lambda team, task, caller, message: None,
            failure_notifier=lambda team, task, caller: None,
        ),
        request=TaskUpdateRequest(
            status=TaskStatus.pending,
            owner=None,
            subject="Implement fix retry",
            description="retry with narrowed scope",
            add_blocks=None,
            add_blocked_by=None,
            add_on_fail=None,
            failure_kind=None,
            failure_note=None,
            failure_root_cause=None,
            failure_evidence=None,
            failure_recommended_next_owner=None,
            failure_recommended_action=None,
            execution_id=None,
            wake_owner=False,
            message="",
            force=False,
        ),
    )

    assert result.apply_result is not None
    assert result.apply_result.case_name == "reopen_task"
    assert result.transition_case == "reopen_task"
    assert result.task.status == TaskStatus.pending
    assert result.task.subject == "Implement fix retry"
    assert result.task.description == "retry with narrowed scope"
    assert result.task.metadata["transition_log"][-1]["case"] == "reopen_task"



def test_execute_task_update_uses_generic_status_update_without_transition_result(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))

    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    TeamManager.add_member("demo", "dev1", "dev1-id", agent_type="general-purpose")

    store = TaskStore("demo")
    task = store.create("Implement fix", owner="dev1")

    result = execute_task_update(
        task_id=task.id,
        caller="dev1",
        ctx=TaskUpdateContext(
            store=store,
            team="demo",
            runtime=RuntimeOrchestrator(team="demo"),
            release_notifier=lambda team, task, caller, message: None,
            failure_notifier=lambda team, task, caller: None,
        ),
        request=TaskUpdateRequest(
            status=TaskStatus.in_progress,
            owner="dev1",
            subject="Implement fix in progress",
            description="started execution",
            add_blocks=None,
            add_blocked_by=None,
            add_on_fail=None,
            failure_kind=None,
            failure_note=None,
            failure_root_cause=None,
            failure_evidence=None,
            failure_recommended_next_owner=None,
            failure_recommended_action=None,
            execution_id=None,
            wake_owner=False,
            message="",
            force=False,
        ),
    )

    assert result.apply_result is None
    assert result.transition_case is None
    assert result.task.status == TaskStatus.in_progress
    assert result.task.subject == "Implement fix in progress"
    assert result.task.description == "started execution"



def test_execute_task_update_uses_generic_patch_for_non_transition_updates(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))

    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    TeamManager.add_member("demo", "dev1", "dev1-id", agent_type="general-purpose")

    store = TaskStore("demo")
    task = store.create("Implement fix", owner="dev1")

    result = execute_task_update(
        task_id=task.id,
        caller="dev1",
        ctx=TaskUpdateContext(
            store=store,
            team="demo",
            runtime=RuntimeOrchestrator(team="demo"),
            release_notifier=lambda team, task, caller, message: None,
            failure_notifier=lambda team, task, caller: None,
        ),
        request=TaskUpdateRequest(
            status=None,
            owner=None,
            subject="Implement fix v2",
            description="narrowed scope",
            add_blocks=None,
            add_blocked_by=None,
            add_on_fail=None,
            failure_kind=None,
            failure_note=None,
            failure_root_cause=None,
            failure_evidence=None,
            failure_recommended_next_owner=None,
            failure_recommended_action=None,
            execution_id=None,
            wake_owner=False,
            message="",
            force=False,
        ),
    )

    assert result.apply_result is None
    assert result.transition_case is None
    assert result.task.subject == "Implement fix v2"
    assert result.task.description == "narrowed scope"
    assert result.task.metadata.get("transition_log") is None



def test_execute_task_update_effects_handles_failure_notice_and_reopen_release(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))

    notices: list[dict[str, str]] = []

    def fake_notifier(team, task, caller):
        notices.append({
            "team": team,
            "task": task.id,
            "caller": caller,
            "kind": task.metadata.get("failure_kind", "complex"),
        })
        return {
            "failureNotice": "sent",
            "failureKind": task.metadata.get("failure_kind", "complex"),
            "failureLeader": "leader",
        }

    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    TeamManager.add_member("demo", "dev1", "dev1-id", agent_type="general-purpose")
    TeamManager.add_member("demo", "qa1", "qa1-id", agent_type="general-purpose")

    store = TaskStore("demo")
    impl = store.create("Implement fix", owner="dev1")
    qa = store.create("Regression QA", owner="qa1", metadata={"on_fail": [impl.id]})
    with patch("clawteam.spawn.registry.is_agent_alive", return_value=None):
        task = store.update(
            qa.id,
            status=TaskStatus.failed,
            caller="qa1",
            metadata={
                "failure_kind": "complex",
                "failure_root_cause": "ownership unclear",
                "failure_evidence": "cross-cutting regression",
                "failure_recommended_next_owner": "leader",
                "failure_recommended_action": "triage owner",
            },
        )

    monkeypatch.setattr(
        "clawteam.services.task_update_service.wake_tasks_to_pending",
        lambda *args, **kwargs: [{"taskId": impl.id, "owner": "dev1", "respawned": False}],
    )

    class FakeRuntime:
        def release_to_owner(self, task, *, caller, message, respawn, release_notifier):
            return {"taskId": task.id, "owner": task.owner, "message": message, "respawned": False}

    effects = execute_task_update_effects(
        ctx=TaskUpdateContext(
            store=store,
            team="demo",
            runtime=FakeRuntime(),
            release_notifier=lambda team, task, caller, message: {"messageSent": True, "message": message},
            failure_notifier=fake_notifier,
        ),
        task=task,
        caller="qa1",
        wake_owner=False,
        message="",
        dependent_ids_to_wake=[],
        failed_targets_to_wake=[impl.id],
    )

    assert effects.wake is None
    assert len(effects.auto_releases) == 1
    assert effects.auto_releases[0]["taskId"] == impl.id
    assert effects.failure_notice is not None
    assert effects.failure_notice["failureNotice"] == "sent"
    assert effects.failure_notice["failureLeader"] == "leader"
    assert effects.triage_release is not None
    triage_id = store.get(qa.id).metadata.get("triage_followup_task_id")
    triage = store.get(str(triage_id))
    assert triage is not None
    assert triage.owner == "leader"
    assert triage.status.value == "pending"
    assert triage.metadata["triage_source_task_id"] == qa.id
    assert "triage owner" in triage.description
    assert notices == [{"team": "demo", "task": qa.id, "caller": "qa1", "kind": "complex"}]


def test_execute_task_update_effects_auto_creates_blocked_triage_followup(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))

    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    TeamManager.add_member("demo", "qa1", "qa1-id", agent_type="general-purpose")

    store = TaskStore("demo")
    blocked = store.create("Regression QA", owner="qa1")

    class FakeRuntime:
        def release_to_owner(self, task, *, caller, message, respawn, release_notifier):
            return {"taskId": task.id, "owner": task.owner, "message": message, "respawned": False}

    result = execute_task_update(
        task_id=blocked.id,
        caller="qa1",
        ctx=TaskUpdateContext(
            store=store,
            team="demo",
            runtime=FakeRuntime(),
            release_notifier=lambda team, task, caller, message: {"messageSent": True, "message": message},
            failure_notifier=lambda *args, **kwargs: None,
        ),
        request=TaskUpdateRequest(
            status=TaskStatus.blocked,
            owner=None,
            subject=None,
            description=None,
            add_blocks=None,
            add_blocked_by=None,
            add_on_fail=None,
            failure_kind=None,
            failure_note=None,
            failure_root_cause="unable to reproduce upstream failure",
            failure_evidence="timeout only",
            failure_recommended_next_owner="leader",
            failure_recommended_action="define repro path",
            execution_id=None,
            wake_owner=False,
            message="",
            force=False,
        ),
    )

    assert result.effects.triage_release is not None
    blocked_after = store.get(blocked.id)
    assert blocked_after.metadata["blocked_root_cause"] == "unable to reproduce upstream failure"
    assert blocked_after.metadata["blocked_recommended_action"] == "define repro path"
    triage_id = blocked_after.metadata.get("triage_followup_task_id")
    triage = store.get(str(triage_id))
    assert triage is not None
    assert triage.owner == "leader"
    assert triage.subject.startswith("Triage blocked task:")




def test_execute_task_update_effects_does_not_recurse_triage_followups(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))

    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    TeamManager.add_member("demo", "qa1", "qa1-id", agent_type="general-purpose")
    TeamManager.add_member("demo", "dev1", "dev1-id", agent_type="general-purpose")

    store = TaskStore("demo")
    source = store.create("Regression QA", owner="qa1")

    class FakeRuntime:
        def release_to_owner(self, task, *, caller, message, respawn, release_notifier):
            return {"taskId": task.id, "owner": task.owner, "message": message, "respawned": False}

    ctx = TaskUpdateContext(
        store=store,
        team="demo",
        runtime=FakeRuntime(),
        release_notifier=lambda team, task, caller, message: {"messageSent": True, "message": message},
        failure_notifier=lambda *args, **kwargs: None,
    )

    execute_task_update(
        task_id=source.id,
        caller="qa1",
        ctx=ctx,
        request=TaskUpdateRequest(
            status=TaskStatus.failed,
            owner=None,
            subject=None,
            description=None,
            add_blocks=None,
            add_blocked_by=None,
            add_on_fail=None,
            failure_kind="complex",
            failure_note=None,
            failure_root_cause="ownership unclear",
            failure_evidence="cross-cutting regression",
            failure_recommended_next_owner="dev1",
            failure_recommended_action="fix and re-run qa",
            execution_id=None,
            wake_owner=False,
            message="",
            force=False,
        ),
    )

    triage_id = store.get(source.id).metadata.get("triage_followup_task_id")
    triage = store.get(str(triage_id))
    assert triage is not None
    assert triage.metadata["triage_followup"] == "true"

    result = execute_task_update(
        task_id=triage.id,
        caller="dev1",
        ctx=ctx,
        request=TaskUpdateRequest(
            status=TaskStatus.blocked,
            owner=None,
            subject=None,
            description=None,
            add_blocks=None,
            add_blocked_by=None,
            add_on_fail=None,
            failure_kind=None,
            failure_note=None,
            failure_root_cause="need more routing",
            failure_evidence="still unclear",
            failure_recommended_next_owner="leader",
            failure_recommended_action="decide owner",
            execution_id=None,
            wake_owner=False,
            message="",
            force=False,
        ),
    )

    triage_after = store.get(triage.id)
    assert triage_after is not None
    assert triage_after.status == TaskStatus.blocked
    assert triage_after.metadata["blocked_recommended_action"] == "decide owner"
    assert "triage_followup_task_id" not in triage_after.metadata
    assert result.effects.triage_release is None


def test_execute_task_update_applies_triage_followup_resolution(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))

    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    TeamManager.add_member("demo", "qa1", "qa1-id", agent_type="general-purpose")
    TeamManager.add_member("demo", "dev1", "dev1-id", agent_type="general-purpose")

    store = TaskStore("demo")
    qa = store.create("Regression QA", owner="qa1")

    class FakeRuntime:
        def release_to_owner(self, task, *, caller, message, respawn, release_notifier):
            return {"taskId": task.id, "owner": task.owner, "message": message, "respawned": False}

    execute_task_update(
        task_id=qa.id,
        caller="qa1",
        ctx=TaskUpdateContext(
            store=store,
            team="demo",
            runtime=FakeRuntime(),
            release_notifier=lambda team, task, caller, message: {"messageSent": True, "message": message},
            failure_notifier=lambda *args, **kwargs: None,
        ),
        request=TaskUpdateRequest(
            status=TaskStatus.failed,
            owner=None,
            subject=None,
            description=None,
            add_blocks=None,
            add_blocked_by=None,
            add_on_fail=None,
            failure_kind="complex",
            failure_note=None,
            failure_root_cause="ownership unclear",
            failure_evidence="cross-cutting regression",
            failure_recommended_next_owner="dev1",
            failure_recommended_action="fix and re-run qa",
            execution_id=None,
            wake_owner=False,
            message="",
            force=False,
        ),
    )

    triage_id = store.get(qa.id).metadata.get("triage_followup_task_id")
    triage = store.get(str(triage_id))
    assert triage is not None

    wake_calls: list[list[str]] = []

    def fake_wake(team, target_ids, caller, message_builder, repo, store, runtime, release_notifier):
        wake_calls.append(target_ids)
        return [{"taskId": target_ids[0], "owner": store.get(target_ids[0]).owner}]

    monkeypatch.setattr("clawteam.services.task_update_service.wake_tasks_to_pending", fake_wake)

    execute_task_update(
        task_id=triage.id,
        caller="leader",
        ctx=TaskUpdateContext(
            store=store,
            team="demo",
            runtime=FakeRuntime(),
            release_notifier=lambda team, task, caller, message: {"messageSent": True, "message": message},
            failure_notifier=lambda *args, **kwargs: None,
        ),
        request=TaskUpdateRequest(
            status=TaskStatus.completed,
            owner=None,
            subject=None,
            description=None,
            add_blocks=None,
            add_blocked_by=None,
            add_on_fail=None,
            failure_kind=None,
            failure_note=None,
            failure_root_cause=None,
            failure_evidence=None,
            failure_recommended_next_owner=None,
            failure_recommended_action=None,
            triage_resolution_owner="dev1",
            triage_resolution_action="fix and re-run qa",
            triage_resolution_note="owner confirmed in triage",
            execution_id=None,
            wake_owner=False,
            message="",
            force=False,
        ),
    )

    updated_source = store.get(qa.id)
    assert updated_source is not None
    assert updated_source.status == TaskStatus.pending
    assert updated_source.owner == "dev1"
    assert updated_source.metadata["triage_followup_resolution_id"] == triage.id
    assert updated_source.metadata["triage_followup_resolution_action"] == "fix and re-run qa"
    assert len(wake_calls) == 1

    execute_task_update(
        task_id=triage.id,
        caller="leader",
        ctx=TaskUpdateContext(
            store=store,
            team="demo",
            runtime=FakeRuntime(),
            release_notifier=lambda team, task, caller, message: {"messageSent": True, "message": message},
            failure_notifier=lambda *args, **kwargs: None,
        ),
        request=TaskUpdateRequest(
            status=TaskStatus.completed,
            owner=None,
            subject=None,
            description=None,
            add_blocks=None,
            add_blocked_by=None,
            add_on_fail=None,
            failure_kind=None,
            failure_note=None,
            failure_root_cause=None,
            failure_evidence=None,
            failure_recommended_next_owner=None,
            failure_recommended_action=None,
            execution_id=None,
            wake_owner=False,
            message="",
            force=False,
        ),
    )

    assert len(wake_calls) == 1


def test_execute_task_update_triage_completion_requires_resolution(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))

    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    TeamManager.add_member("demo", "qa1", "qa1-id", agent_type="general-purpose")
    TeamManager.add_member("demo", "dev1", "dev1-id", agent_type="general-purpose")

    store = TaskStore("demo")
    qa = store.create("Regression QA", owner="qa1")

    class FakeRuntime:
        def release_to_owner(self, task, *, caller, message, respawn, release_notifier):
            return {"taskId": task.id, "owner": task.owner, "message": message, "respawned": False}

    execute_task_update(
        task_id=qa.id,
        caller="qa1",
        ctx=TaskUpdateContext(
            store=store,
            team="demo",
            runtime=FakeRuntime(),
            release_notifier=lambda team, task, caller, message: {"messageSent": True, "message": message},
            failure_notifier=lambda *args, **kwargs: None,
        ),
        request=TaskUpdateRequest(
            status=TaskStatus.failed,
            owner=None,
            subject=None,
            description=None,
            add_blocks=None,
            add_blocked_by=None,
            add_on_fail=None,
            failure_kind="complex",
            failure_note=None,
            failure_root_cause="ownership unclear",
            failure_evidence="cross-cutting regression",
            failure_recommended_next_owner="dev1",
            failure_recommended_action="fix and re-run qa",
            execution_id=None,
            wake_owner=False,
            message="",
            force=False,
        ),
    )

    triage_id = store.get(qa.id).metadata.get("triage_followup_task_id")
    triage = store.get(str(triage_id))
    assert triage is not None

    wake_calls: list[list[str]] = []

    def fake_wake(team, target_ids, caller, message_builder, repo, store, runtime, release_notifier):
        wake_calls.append(target_ids)
        return [{"taskId": target_ids[0], "owner": store.get(target_ids[0]).owner}]

    monkeypatch.setattr("clawteam.services.task_update_service.wake_tasks_to_pending", fake_wake)

    execute_task_update(
        task_id=triage.id,
        caller="leader",
        ctx=TaskUpdateContext(
            store=store,
            team="demo",
            runtime=FakeRuntime(),
            release_notifier=lambda team, task, caller, message: {"messageSent": True, "message": message},
            failure_notifier=lambda *args, **kwargs: None,
        ),
        request=TaskUpdateRequest(
            status=TaskStatus.completed,
            owner=None,
            subject=None,
            description=None,
            add_blocks=None,
            add_blocked_by=None,
            add_on_fail=None,
            failure_kind=None,
            failure_note=None,
            failure_root_cause=None,
            failure_evidence=None,
            failure_recommended_next_owner=None,
            failure_recommended_action=None,
            execution_id=None,
            wake_owner=False,
            message="",
            force=False,
        ),
    )

    updated_source = store.get(qa.id)
    assert updated_source is not None
    assert updated_source.status == TaskStatus.failed
    assert len(wake_calls) == 0


def test_build_dependency_completion_message_includes_structured_qa_context(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))

    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    store = TaskStore("demo")
    qa = store.create(
        "Regression QA",
        owner="qa1",
        metadata={
            "qa_result": {
                "status": "pass_with_risk",
                "summary": "Main goal validated",
                "risk": "- failed branch remains unvalidated",
            }
        },
    )
    review = store.create("Review", owner="review1")

    message = _build_dependency_completion_message(qa, review)
    assert "Dependency QA context:" in message
    assert "- status: pass_with_risk" in message
    assert "- summary: Main goal validated" in message
    assert "- risk: - failed branch remains unvalidated" in message


def test_infer_runtime_handoff_from_setup_sections_extracts_venv_and_baseline_commands():
    payload = _infer_runtime_handoff_from_setup_sections(
        {
            "remote_status": "cached_only",
            "remote_head": "03bdc8f",
            "detached_worktree": "/tmp/demo/.worktrees/setup-123",
            "detached_head": "9e8f87f",
            "install": (
                "- python3 -m pip install -e '.[dev]' -> failed: PEP 668\n"
                "- python3 -m venv .venv && source .venv/bin/activate && python -m pip install -e '.[dev]' -> success"
            ),
            "baseline_validation": "- source .venv/bin/activate && pytest -q -> 336 passed in 2.30s",
        }
    )

    assert payload["version"] == 1
    assert payload["source_task_stage"] == "setup"
    assert payload["venv_path"] == ".venv"
    assert payload["detached_worktree"] == "/tmp/demo/.worktrees/setup-123"
    assert payload["detached_worktree_name"] == "setup-123"
    assert payload["activation_commands"] == [
        "source .venv/bin/activate",
        "cd /tmp/demo/.worktrees/setup-123 && source .venv/bin/activate",
    ]
    assert payload["baseline_commands"] == ["source .venv/bin/activate && pytest -q -> 336 passed in 2.30s"]


def test_execute_task_update_effects_propagates_setup_runtime_handoff_to_dependents(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))

    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    TeamManager.add_member("demo", "config1", "config1-id", agent_type="general-purpose")
    TeamManager.add_member("demo", "dev1", "dev1-id", agent_type="general-purpose")

    store = TaskStore("demo")
    setup = store.create(
        "Prepare repo, branch, env, and runnable baseline",
        owner="config1",
        metadata={"message_type": "SETUP_RESULT"},
    )
    setup = store.update(
        setup.id,
        status=TaskStatus.completed,
        caller="config1",
        description=(
            "SETUP_RESULT\n"
            "status: completed\n"
            "remote_status: cached_only\n"
            "remote_head: 03bdc8f\n"
            "detached_worktree: /tmp/demo/.worktrees/setup-123\n"
            "detached_head: 9e8f87f\n"
            "install:\n"
            "- python3 -m venv .venv && source .venv/bin/activate && python -m pip install -e '.[dev]' -> success\n"
            "baseline_validation:\n"
            "- source .venv/bin/activate && pytest -q -> 336 passed in 2.30s\n"
            "known_limitations:\n"
            "- none\n"
            "next_action: handoff to implement"
        ),
    )
    assert setup is not None
    impl = store.create("Implement fix", owner="dev1", description="Original implement brief")

    monkeypatch.setattr(
        "clawteam.services.task_update_service.wake_tasks_to_pending",
        lambda *args, **kwargs: [{"taskId": impl.id, "owner": "dev1", "respawned": False}],
    )

    execute_task_update_effects(
        ctx=TaskUpdateContext(
            store=store,
            team="demo",
            runtime=RuntimeOrchestrator(team="demo"),
            release_notifier=lambda team, task, caller, message: {"messageSent": True, "message": message},
            failure_notifier=lambda team, task, caller: None,
        ),
        task=setup,
        caller="config1",
        wake_owner=False,
        message="",
        dependent_ids_to_wake=[impl.id],
        failed_targets_to_wake=[],
    )

    updated_setup = store.get(setup.id)
    updated_impl = store.get(impl.id)
    assert updated_setup is not None and updated_impl is not None
    assert updated_setup.metadata["runtime_handoff"]["venv_path"] == ".venv"
    assert updated_impl.metadata["setup_runtime_handoff"]["detached_worktree"] == "/tmp/demo/.worktrees/setup-123"
    assert updated_impl.metadata["setup_runtime_handoff"]["baseline_commands"] == [
        "source .venv/bin/activate && pytest -q -> 336 passed in 2.30s"
    ]
    assert "## Setup Runtime Handoff" in updated_impl.description
    assert "Treat this handoff as runtime contract" in updated_impl.description


def test_execute_task_update_rejects_scope_completion_without_structured_description(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))

    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    store = TaskStore("demo")
    scope = store.create(
        "Scope the task into a minimal deliverable",
        owner="leader",
        metadata={
            "template_stage": "scope",
            "launch_brief": {
                "format": "structured_sections",
                "sections": {
                    "source_request": "Ship the feature safely",
                    "scoped_brief": "",
                    "unknowns": [],
                    "leader_assumptions": [],
                    "out_of_scope": [],
                },
            },
        },
    )

    with pytest.raises(TaskUpdateValidationError, match="scope task completion must include the final structured brief"):
        execute_task_update(
            task_id=scope.id,
            caller="leader",
            ctx=TaskUpdateContext(
                store=store,
                team="demo",
                runtime=RuntimeOrchestrator(team="demo"),
                release_notifier=lambda team, task, caller, message: None,
                failure_notifier=lambda team, task, caller: None,
            ),
            request=TaskUpdateRequest(
                status=TaskStatus.completed,
                owner=None,
                subject=None,
                description=None,
                add_blocks=None,
                add_blocked_by=None,
                add_on_fail=None,
                failure_kind=None,
                failure_note=None,
                failure_root_cause=None,
                failure_evidence=None,
                failure_recommended_next_owner=None,
                failure_recommended_action=None,
                execution_id=None,
                wake_owner=False,
                message="",
                force=False,
            ),
        )


def test_execute_task_update_allows_scope_completion_after_prior_description_update(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))

    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    store = TaskStore("demo")
    scope = store.create(
        "Scope the task into a minimal deliverable",
        owner="leader",
        metadata={
            "template_stage": "scope",
            "launch_brief": {
                "format": "structured_sections",
                "sections": {
                    "source_request": "Validate latest flyzorro/main from a clean detached worktree using real evidence only; do not mock; fail closed on uncertainty.",
                    "scoped_brief": "",
                    "unknowns": [],
                    "leader_assumptions": [],
                    "out_of_scope": [],
                },
            },
        },
    )

    final_description = """## Source Request
Validate latest flyzorro/main from a clean detached worktree using real evidence only; do not mock; fail closed on uncertainty.

## Scoped Brief
Validate latest flyzorro/main from a clean detached worktree using real evidence only; do not mock; fail closed on uncertainty.

## Unknowns
- The exact validation commands are not yet confirmed.

## Leader Assumptions
- `flyzorro/main` is available from this machine.

## Out of Scope
- Any mocked result.
"""

    updated = execute_task_update(
        task_id=scope.id,
        caller="leader",
        ctx=TaskUpdateContext(
            store=store,
            team="demo",
            runtime=RuntimeOrchestrator(team="demo"),
            release_notifier=lambda team, task, caller, message: None,
            failure_notifier=lambda team, task, caller: None,
        ),
        request=TaskUpdateRequest(
            status=None,
            owner=None,
            subject=None,
            description=final_description,
            add_blocks=None,
            add_blocked_by=None,
            add_on_fail=None,
            failure_kind=None,
            failure_note=None,
            failure_root_cause=None,
            failure_evidence=None,
            failure_recommended_next_owner=None,
            failure_recommended_action=None,
            execution_id=None,
            wake_owner=False,
            message="",
            force=False,
        ),
    )
    assert updated.task.description == final_description

    completed = execute_task_update(
        task_id=scope.id,
        caller="leader",
        ctx=TaskUpdateContext(
            store=store,
            team="demo",
            runtime=RuntimeOrchestrator(team="demo"),
            release_notifier=lambda team, task, caller, message: None,
            failure_notifier=lambda team, task, caller: None,
        ),
        request=TaskUpdateRequest(
            status=TaskStatus.completed,
            owner=None,
            subject=None,
            description=None,
            add_blocks=None,
            add_blocked_by=None,
            add_on_fail=None,
            failure_kind=None,
            failure_note=None,
            failure_root_cause=None,
            failure_evidence=None,
            failure_recommended_next_owner=None,
            failure_recommended_action=None,
            execution_id=None,
            wake_owner=False,
            message="",
            force=False,
        ),
    )
    assert completed.task.status is TaskStatus.completed
    resolved_scope = completed.task.metadata.get("resolved_scope")
    assert isinstance(resolved_scope, dict)
    assert resolved_scope.get("sections", {}).get("scoped_brief") == (
        "Validate latest flyzorro/main from a clean detached worktree using real evidence only; do not mock; fail closed on uncertainty."
    )


def test_execute_task_update_accepts_and_persists_feature_scope_for_feature_delivery(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr("clawteam.services.task_update_service.wake_tasks_to_pending", lambda *args, **kwargs: [])

    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    store = TaskStore("demo")
    scope = store.create(
        "Scope the task into a minimal deliverable",
        owner="leader",
        metadata={
            "template_stage": "scope",
            "feature_scope_required": True,
            "launch_brief": {
                "format": "structured_sections",
                "sections": {
                    "source_request": "Ship the feature safely",
                    "scoped_brief": "",
                    "unknowns": [],
                    "leader_assumptions": [],
                    "out_of_scope": [],
                },
            },
        },
    )
    setup = store.create("Prepare environment", owner="config1", blocked_by=[scope.id], metadata={"template_stage": "setup"})

    final_description = '''## Source Request
Ship the feature safely

## Scoped Brief
Ship the feature safely.

## Unknowns
- none

## Leader Assumptions
- existing delivery lanes remain valid for phase 1

## Out of Scope
- workflow redesign

## FEATURE_SCOPE
{"source_request":"Ship the feature safely","scoped_brief":"Ship the feature safely.","in_scope":["Ship the feature safely."],"unknowns":["none"],"leader_assumptions":["existing delivery lanes remain valid for phase 1"],"out_of_scope":["workflow redesign"],"risks_blockers":["feature_scope_required consumers must fail closed on malformed scope"],"recommended_next_step":"Deliver strictly against this scoped brief without workflow redesign.","execution_shape":"backend-only","change_budget":{"allowed_layers":["backend","api"],"allowed_operations":["edit-existing","add-backend-module"],"allowed_roots":["server/"],"forbidden_layers":["web-ui","mobile-ui"]},"initial_targets":[{"kind":"api-handler","path":"server/src/routes/member.ts","exists":true,"why_in_scope":"member API change required by scoped brief","evidence":["rg hit: server/src/routes/member.ts"]}]}
'''

    result = execute_task_update(
        task_id=scope.id,
        caller="leader",
        ctx=TaskUpdateContext(
            store=store,
            team="demo",
            runtime=RuntimeOrchestrator(team="demo"),
            release_notifier=lambda team, task, caller, message: None,
            failure_notifier=lambda team, task, caller: None,
        ),
        request=TaskUpdateRequest(
            status=TaskStatus.completed,
            owner=None,
            subject=None,
            description=final_description,
            add_blocks=None,
            add_blocked_by=None,
            add_on_fail=None,
            failure_kind=None,
            failure_note=None,
            failure_root_cause=None,
            failure_evidence=None,
            failure_recommended_next_owner=None,
            failure_recommended_action=None,
            execution_id=None,
            wake_owner=False,
            message="",
            force=False,
        ),
    )

    assert result.task.status is TaskStatus.completed
    assert result.task.metadata["feature_scope"] == {
        "version": "v1",
        "source_request": "Ship the feature safely",
        "scoped_brief": "Ship the feature safely.",
        "in_scope": ["Ship the feature safely."],
        "unknowns": ["none"],
        "leader_assumptions": ["existing delivery lanes remain valid for phase 1"],
        "out_of_scope": ["workflow redesign"],
        "risks_blockers": ["feature_scope_required consumers must fail closed on malformed scope"],
        "recommended_next_step": "Deliver strictly against this scoped brief without workflow redesign.",
        "execution_shape": "backend-only",
        "change_budget": {
            "allowed_layers": ["backend", "api"],
            "allowed_operations": ["edit-existing", "add-backend-module"],
            "allowed_roots": ["server/"],
            "forbidden_layers": ["web-ui", "mobile-ui"],
        },
        "initial_targets": [{
            "kind": "api-handler",
            "path": "server/src/routes/member.ts",
            "exists": True,
            "why_in_scope": "member API change required by scoped brief",
            "evidence": ["rg hit: server/src/routes/member.ts"],
        }],
    }
    refreshed_setup = store.get(setup.id)
    assert refreshed_setup.metadata["feature_scope"]["scoped_brief"] == "Ship the feature safely."


def test_execute_task_update_rejects_feature_delivery_scope_completion_without_feature_scope(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))

    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    store = TaskStore("demo")
    scope = store.create(
        "Scope the task into a minimal deliverable",
        owner="leader",
        metadata={
            "template_stage": "scope",
            "feature_scope_required": True,
            "launch_brief": {
                "format": "structured_sections",
                "sections": {
                    "source_request": "Ship the feature safely",
                    "scoped_brief": "",
                    "unknowns": [],
                    "leader_assumptions": [],
                    "out_of_scope": [],
                },
            },
        },
    )

    final_description = '''## Source Request
Ship the feature safely

## Scoped Brief
Ship the feature safely.

## Unknowns
- none

## Leader Assumptions
- existing delivery lanes remain valid for phase 1

## Out of Scope
- workflow redesign
'''

    with pytest.raises(TaskUpdateValidationError, match="must include a valid FEATURE_SCOPE block"):
        execute_task_update(
            task_id=scope.id,
            caller="leader",
            ctx=TaskUpdateContext(
                store=store,
                team="demo",
                runtime=RuntimeOrchestrator(team="demo"),
                release_notifier=lambda team, task, caller, message: None,
                failure_notifier=lambda team, task, caller: None,
            ),
            request=TaskUpdateRequest(
                status=TaskStatus.completed,
                owner=None,
                subject=None,
                description=final_description,
                add_blocks=None,
                add_blocked_by=None,
                add_on_fail=None,
                failure_kind=None,
                failure_note=None,
                failure_root_cause=None,
                failure_evidence=None,
                failure_recommended_next_owner=None,
                failure_recommended_action=None,
                execution_id=None,
                wake_owner=False,
                message="",
                force=False,
            ),
        )


def test_execute_task_update_rejects_malformed_feature_scope_for_feature_delivery(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))

    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    store = TaskStore("demo")
    scope = store.create(
        "Scope the task into a minimal deliverable",
        owner="leader",
        metadata={
            "template_stage": "scope",
            "feature_scope_required": True,
            "launch_brief": {
                "format": "structured_sections",
                "sections": {
                    "source_request": "Ship the feature safely",
                    "scoped_brief": "",
                    "unknowns": [],
                    "leader_assumptions": [],
                    "out_of_scope": [],
                },
            },
        },
    )

    malformed_description = '''## Source Request
Ship the feature safely

## Scoped Brief
Ship the feature safely.

## Unknowns
- none

## Leader Assumptions
- existing delivery lanes remain valid for phase 1

## Out of Scope
- workflow redesign

## FEATURE_SCOPE
{"source_request":"Ship the feature safely","scoped_brief":"Ship the feature safely.","in_scope":["Ship the feature safely."],"unknowns":["none"],"leader_assumptions":["existing delivery lanes remain valid for phase 1"],"out_of_scope":["workflow redesign"],"execution_shape":"backend-only","change_budget":{"allowed_layers":["backend","api"],"allowed_operations":["edit-existing","add-backend-module"],"allowed_roots":["server/"],"forbidden_layers":["web-ui","mobile-ui"]},"initial_targets":[{"kind":"api-handler","path":"server/src/routes/member.ts","exists":true,"why_in_scope":"member API change required by scoped brief","evidence":["rg hit: server/src/routes/member.ts"]}]}
'''

    with pytest.raises(TaskUpdateValidationError, match="recommended_next_step value"):
        execute_task_update(
            task_id=scope.id,
            caller="leader",
            ctx=TaskUpdateContext(
                store=store,
                team="demo",
                runtime=RuntimeOrchestrator(team="demo"),
                release_notifier=lambda team, task, caller, message: None,
                failure_notifier=lambda team, task, caller: None,
            ),
            request=TaskUpdateRequest(
                status=TaskStatus.completed,
                owner=None,
                subject=None,
                description=malformed_description,
                add_blocks=None,
                add_blocked_by=None,
                add_on_fail=None,
                failure_kind=None,
                failure_note=None,
                failure_root_cause=None,
                failure_evidence=None,
                failure_recommended_next_owner=None,
                failure_recommended_action=None,
                execution_id=None,
                wake_owner=False,
                message="",
                force=False,
            ),
        )


def test_execute_task_update_rejects_feature_delivery_scope_completion_without_execution_shape(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))

    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    store = TaskStore("demo")
    scope = store.create(
        "Scope the task into a minimal deliverable",
        owner="leader",
        metadata={
            "template_stage": "scope",
            "feature_scope_required": True,
            "launch_brief": {
                "format": "structured_sections",
                "sections": {
                    "source_request": "Ship the feature safely",
                    "scoped_brief": "",
                    "unknowns": [],
                    "leader_assumptions": [],
                    "out_of_scope": [],
                },
            },
        },
    )

    missing_shape_description = '''## Source Request
Ship the feature safely

## Scoped Brief
Ship the feature safely.

## Unknowns
- none

## Leader Assumptions
- existing delivery lanes remain valid for phase 1

## Out of Scope
- workflow redesign

## FEATURE_SCOPE
{"source_request":"Ship the feature safely","scoped_brief":"Ship the feature safely.","in_scope":["Ship the feature safely."],"unknowns":["none"],"leader_assumptions":["existing delivery lanes remain valid for phase 1"],"out_of_scope":["workflow redesign"],"risks_blockers":["feature_scope_required consumers must fail closed on malformed scope"],"recommended_next_step":"Deliver strictly against this scoped brief without workflow redesign.","change_budget":{"allowed_layers":["backend","api"],"allowed_operations":["edit-existing","add-backend-module"],"allowed_roots":["server/"],"forbidden_layers":["web-ui","mobile-ui"]},"initial_targets":[{"kind":"api-handler","path":"server/src/routes/member.ts","exists":true,"why_in_scope":"member API change required by scoped brief","evidence":["rg hit: server/src/routes/member.ts"]}]}
'''

    with pytest.raises(TaskUpdateValidationError, match=r"FEATURE_SCOPE\.execution_shape"):
        execute_task_update(
            task_id=scope.id,
            caller="leader",
            ctx=TaskUpdateContext(
                store=store,
                team="demo",
                runtime=RuntimeOrchestrator(team="demo"),
                release_notifier=lambda team, task, caller, message: None,
                failure_notifier=lambda team, task, caller: None,
            ),
            request=TaskUpdateRequest(
                status=TaskStatus.completed,
                owner=None,
                subject=None,
                description=missing_shape_description,
                add_blocks=None,
                add_blocked_by=None,
                add_on_fail=None,
                failure_kind=None,
                failure_note=None,
                failure_root_cause=None,
                failure_evidence=None,
                failure_recommended_next_owner=None,
                failure_recommended_action=None,
                execution_id=None,
                wake_owner=False,
                message="",
                force=False,
            ),
        )


def test_execute_task_update_rejects_ui_scope_completion_without_validated_initial_target(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))

    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    store = TaskStore("demo")
    scope = store.create(
        "Scope the task into a minimal deliverable",
        owner="leader",
        metadata={
            "template_stage": "scope",
            "feature_scope_required": True,
            "launch_brief": {
                "format": "structured_sections",
                "sections": {
                    "source_request": "Polish the member list page UI only",
                    "scoped_brief": "",
                    "unknowns": [],
                    "leader_assumptions": [],
                    "out_of_scope": ["backend changes"],
                },
            },
        },
    )

    missing_target_description = '''## Source Request
Polish the member list page UI only

## Scoped Brief
Polish the member list page UI only.

## Unknowns
- none

## Leader Assumptions
- existing web route should already exist

## Out of Scope
- backend changes

## FEATURE_SCOPE
{"source_request":"Polish the member list page UI only","scoped_brief":"Polish the member list page UI only.","in_scope":["member list UI update"],"unknowns":["none"],"leader_assumptions":["existing web route should already exist"],"out_of_scope":["backend changes"],"risks_blockers":["none"],"recommended_next_step":"setup","execution_shape":"ui-only","change_budget":{"allowed_layers":["web-ui"],"allowed_operations":["edit-existing","add-ui-component"],"allowed_roots":["dashboard/"],"forbidden_layers":["backend","api","schema","db","crawler","auth","mobile-ui"]},"initial_targets":[]}
'''

    with pytest.raises(TaskUpdateValidationError, match="validated frontend target"):
        execute_task_update(
            task_id=scope.id,
            caller="leader",
            ctx=TaskUpdateContext(
                store=store,
                team="demo",
                runtime=RuntimeOrchestrator(team="demo"),
                release_notifier=lambda team, task, caller, message: None,
                failure_notifier=lambda team, task, caller: None,
            ),
            request=TaskUpdateRequest(
                status=TaskStatus.completed,
                owner=None,
                subject=None,
                description=missing_target_description,
                add_blocks=None,
                add_blocked_by=None,
                add_on_fail=None,
                failure_kind=None,
                failure_note=None,
                failure_root_cause=None,
                failure_evidence=None,
                failure_recommended_next_owner=None,
                failure_recommended_action=None,
                execution_id=None,
                wake_owner=False,
                message="",
                force=False,
            ),
        )


def test_execute_task_update_rejects_malformed_scope_completion_as_task_validation(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))

    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    store = TaskStore("demo")
    scope = store.create(
        "Scope the task into a minimal deliverable",
        owner="leader",
        metadata={
            "template_stage": "scope",
            "launch_brief": {
                "format": "structured_sections",
                "sections": {
                    "source_request": "Ship the feature safely",
                    "scoped_brief": "",
                    "unknowns": [],
                    "leader_assumptions": [],
                    "out_of_scope": [],
                },
            },
        },
    )

    malformed_description = """## Source Request
Ship the feature safely

## Unknowns
- none

## Leader Assumptions
- existing tests are representative

## Out of Scope
- dashboard rewrite
"""

    with pytest.raises(TaskUpdateValidationError, match="missing a non-empty Scoped Brief"):
        execute_task_update(
            task_id=scope.id,
            caller="leader",
            ctx=TaskUpdateContext(
                store=store,
                team="demo",
                runtime=RuntimeOrchestrator(team="demo"),
                release_notifier=lambda team, task, caller, message: None,
                failure_notifier=lambda team, task, caller: None,
            ),
            request=TaskUpdateRequest(
                status=TaskStatus.completed,
                owner=None,
                subject=None,
                description=malformed_description,
                add_blocks=None,
                add_blocked_by=None,
                add_on_fail=None,
                failure_kind=None,
                failure_note=None,
                failure_root_cause=None,
                failure_evidence=None,
                failure_recommended_next_owner=None,
                failure_recommended_action=None,
                execution_id=None,
                wake_owner=False,
                message="",
                force=False,
            ),
        )


def test_execute_task_update_rejects_scope_invention_as_task_validation(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))

    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    store = TaskStore("demo")
    scope = store.create(
        "Scope the task into a minimal deliverable",
        owner="leader",
        metadata={
            "template_stage": "scope",
            "launch_brief": {
                "format": "structured_sections",
                "sections": {
                    "source_request": "Polish the member list UI.",
                    "scoped_brief": "",
                    "unknowns": [],
                    "leader_assumptions": [],
                    "out_of_scope": [],
                },
            },
        },
    )

    invented_description = """## Source Request
Polish the member list UI.

## Scoped Brief
Add a new API endpoint and schema for the member list.

## Unknowns
- none

## Leader Assumptions
- existing tests are representative

## Out of Scope
- dashboard rewrite
"""

    with pytest.raises(TaskUpdateValidationError, match="invents new scope entities"):
        execute_task_update(
            task_id=scope.id,
            caller="leader",
            ctx=TaskUpdateContext(
                store=store,
                team="demo",
                runtime=RuntimeOrchestrator(team="demo"),
                release_notifier=lambda team, task, caller, message: None,
                failure_notifier=lambda team, task, caller: None,
            ),
            request=TaskUpdateRequest(
                status=TaskStatus.completed,
                owner=None,
                subject=None,
                description=invented_description,
                add_blocks=None,
                add_blocked_by=None,
                add_on_fail=None,
                failure_kind=None,
                failure_note=None,
                failure_root_cause=None,
                failure_evidence=None,
                failure_recommended_next_owner=None,
                failure_recommended_action=None,
                execution_id=None,
                wake_owner=False,
                message="",
                force=False,
            ),
        )


def test_execute_task_update_rejects_scope_tightening_as_task_validation(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))

    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    store = TaskStore("demo")
    scope = store.create(
        "Scope the task into a minimal deliverable",
        owner="leader",
        metadata={
            "template_stage": "scope",
            "launch_brief": {
                "format": "structured_sections",
                "sections": {
                    "source_request": "Polish the member list UI.",
                    "scoped_brief": "",
                    "unknowns": [],
                    "leader_assumptions": [],
                    "out_of_scope": [],
                },
            },
        },
    )

    tightened_description = """## Source Request
Polish the member list UI.

## Scoped Brief
Polish the member list UI and it must be production-ready with no regressions.

## Unknowns
- none

## Leader Assumptions
- existing tests are representative

## Out of Scope
- dashboard rewrite
"""

    with pytest.raises(TaskUpdateValidationError, match="adds stricter requirements"):
        execute_task_update(
            task_id=scope.id,
            caller="leader",
            ctx=TaskUpdateContext(
                store=store,
                team="demo",
                runtime=RuntimeOrchestrator(team="demo"),
                release_notifier=lambda team, task, caller, message: None,
                failure_notifier=lambda team, task, caller: None,
            ),
            request=TaskUpdateRequest(
                status=TaskStatus.completed,
                owner=None,
                subject=None,
                description=tightened_description,
                add_blocks=None,
                add_blocked_by=None,
                add_on_fail=None,
                failure_kind=None,
                failure_note=None,
                failure_root_cause=None,
                failure_evidence=None,
                failure_recommended_next_owner=None,
                failure_recommended_action=None,
                execution_id=None,
                wake_owner=False,
                message="",
                force=False,
            ),
        )


def test_execute_task_update_allows_quality_wording_without_hard_requirement_upgrade(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))

    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    TeamManager.add_member("demo", "config1", "config1-id", agent_type="general-purpose")

    store = TaskStore("demo")
    scope = store.create(
        "Scope the task into a minimal deliverable",
        owner="leader",
        metadata={
            "template_stage": "scope",
            "launch_brief": {
                "format": "structured_sections",
                "sections": {
                    "source_request": "Polish the member list UI.",
                    "scoped_brief": "Initial scope",
                    "unknowns": [],
                    "leader_assumptions": [],
                    "out_of_scope": [],
                },
            },
        },
    )
    setup = store.create(
        "Prepare repo, branch, env, and runnable baseline",
        owner="config1",
        blocked_by=[scope.id],
        metadata={"template_stage": "setup"},
        description="Original setup brief",
    )

    monkeypatch.setattr(
        "clawteam.services.task_update_service.wake_tasks_to_pending",
        lambda team, target_ids, caller, message_builder, repo, store, runtime, release_notifier: [
            {"taskId": target_ids[0], "message": message_builder(store.get(target_ids[0]))}
        ],
    )

    result = execute_task_update(
        task_id=scope.id,
        caller="leader",
        ctx=TaskUpdateContext(
            store=store,
            team="demo",
            runtime=RuntimeOrchestrator(team="demo"),
            release_notifier=lambda team, task, caller, message: {"messageSent": True, "message": message},
            failure_notifier=lambda team, task, caller: None,
        ),
        request=TaskUpdateRequest(
            status=TaskStatus.completed,
            owner=None,
            subject=None,
            description="""## Source Request
Polish the member list UI.

## Scoped Brief
Polish the member list UI and ensure it is production-ready with no regressions.

## Unknowns
- none

## Leader Assumptions
- existing tests are representative

## Out of Scope
- dashboard rewrite
""",
            add_blocks=None,
            add_blocked_by=None,
            add_on_fail=None,
            failure_kind=None,
            failure_note=None,
            failure_root_cause=None,
            failure_evidence=None,
            failure_recommended_next_owner=None,
            failure_recommended_action=None,
            execution_id=None,
            wake_owner=False,
            message="",
            force=False,
        ),
    )

    refreshed_scope = store.get(scope.id)
    refreshed_setup = store.get(setup.id)

    assert result.task.status == TaskStatus.completed
    assert refreshed_scope.metadata["resolved_scope"]["sections"]["scoped_brief"] == (
        "Polish the member list UI and ensure it is production-ready with no regressions."
    )
    assert refreshed_setup.status == TaskStatus.pending
    assert "## Resolved Scope Context" in refreshed_setup.description


def test_execute_task_update_allows_scope_clarification_without_additive_intent(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))

    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    TeamManager.add_member("demo", "config1", "config1-id", agent_type="general-purpose")

    store = TaskStore("demo")
    scope = store.create(
        "Scope the task into a minimal deliverable",
        owner="leader",
        metadata={
            "template_stage": "scope",
            "launch_brief": {
                "format": "structured_sections",
                "sections": {
                    "source_request": "Polish the member list UI.",
                    "scoped_brief": "Initial scope",
                    "unknowns": [],
                    "leader_assumptions": [],
                    "out_of_scope": [],
                },
            },
        },
    )
    setup = store.create(
        "Prepare repo, branch, env, and runnable baseline",
        owner="config1",
        blocked_by=[scope.id],
        metadata={"template_stage": "setup"},
        description="Original setup brief",
    )

    monkeypatch.setattr(
        "clawteam.services.task_update_service.wake_tasks_to_pending",
        lambda team, target_ids, caller, message_builder, repo, store, runtime, release_notifier: [
            {"taskId": target_ids[0], "message": message_builder(store.get(target_ids[0]))}
        ],
    )

    result = execute_task_update(
        task_id=scope.id,
        caller="leader",
        ctx=TaskUpdateContext(
            store=store,
            team="demo",
            runtime=RuntimeOrchestrator(team="demo"),
            release_notifier=lambda team, task, caller, message: {"messageSent": True, "message": message},
            failure_notifier=lambda team, task, caller: None,
        ),
        request=TaskUpdateRequest(
            status=TaskStatus.completed,
            owner=None,
            subject=None,
            description="""## Source Request
Polish the member list UI.

## Scoped Brief
Clarify the API behavior used by the current member list UI without adding new endpoints.

## Unknowns
- none

## Leader Assumptions
- existing tests are representative

## Out of Scope
- dashboard rewrite
""",
            add_blocks=None,
            add_blocked_by=None,
            add_on_fail=None,
            failure_kind=None,
            failure_note=None,
            failure_root_cause=None,
            failure_evidence=None,
            failure_recommended_next_owner=None,
            failure_recommended_action=None,
            execution_id=None,
            wake_owner=False,
            message="",
            force=False,
        ),
    )

    updated_setup = store.get(setup.id)
    assert result.task.status == TaskStatus.completed
    assert updated_setup is not None
    assert updated_setup.metadata["resolved_scope"]["sections"]["scoped_brief"].startswith("Clarify the API behavior")


def test_execute_task_update_propagates_validated_scope_to_unblocked_tasks(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))

    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    TeamManager.add_member("demo", "config1", "config1-id", agent_type="general-purpose")

    store = TaskStore("demo")
    scope = store.create(
        "Scope the task into a minimal deliverable",
        owner="leader",
        metadata={
            "template_stage": "scope",
            "launch_brief": {
                "format": "structured_sections",
                "sections": {
                    "source_request": "Ship the feature safely",
                    "scoped_brief": "Initial scope",
                    "unknowns": [],
                    "leader_assumptions": [],
                    "out_of_scope": [],
                },
            },
        },
    )
    setup = store.create(
        "Prepare repo, branch, env, and runnable baseline",
        owner="config1",
        blocked_by=[scope.id],
        metadata={"template_stage": "setup"},
        description="Original setup brief",
    )

    captured_messages = []

    monkeypatch.setattr(
        "clawteam.services.task_update_service.wake_tasks_to_pending",
        lambda team, target_ids, caller, message_builder, repo, store, runtime, release_notifier: [
            {"taskId": target_ids[0], "message": message_builder(store.get(target_ids[0]))}
        ],
    )

    result = execute_task_update(
        task_id=scope.id,
        caller="leader",
        ctx=TaskUpdateContext(
            store=store,
            team="demo",
            runtime=RuntimeOrchestrator(team="demo"),
            release_notifier=lambda team, task, caller, message: captured_messages.append(message) or {"messageSent": True, "message": message},
            failure_notifier=lambda team, task, caller: None,
        ),
        request=TaskUpdateRequest(
            status=TaskStatus.completed,
            owner=None,
            subject=None,
            description="""## Source Request
Ship the feature safely

## Scoped Brief
Deliver only the minimal safe fix.

## Unknowns
- none

## Leader Assumptions
- existing tests are representative

## Out of Scope
- dashboard rewrite

## Risks/Blockers
- none

## Recommended Next Step
- setup
""",
            add_blocks=None,
            add_blocked_by=None,
            add_on_fail=None,
            failure_kind=None,
            failure_note=None,
            failure_root_cause=None,
            failure_evidence=None,
            failure_recommended_next_owner=None,
            failure_recommended_action=None,
            execution_id=None,
            wake_owner=False,
            message="",
            force=False,
        ),
    )

    updated_setup = store.get(setup.id)
    assert result.task.metadata["resolved_scope"]["sections"]["scoped_brief"] == "Deliver only the minimal safe fix."
    assert updated_setup is not None
    assert updated_setup.status == TaskStatus.pending
    assert updated_setup.metadata["resolved_scope"]["sections"]["source_request"] == "Ship the feature safely"
    assert "## Resolved Scope Context" in updated_setup.description
    assert "Deliver only the minimal safe fix." in updated_setup.description


def _five_step_workflow_definition() -> dict[str, object]:
    return {
        "template_name": "five-step-delivery",
        "preserved_definition": True,
        "materialized_subjects": ["Scope the task into a minimal deliverable"],
        "deferred_subjects": [
            "Prepare repo, branch, env, and runnable baseline",
            "Implement assigned change slice A with real validation",
            "Implement assigned change slice B with real validation",
            "Run scoped QA pass A on the real change",
            "Run scoped QA pass B on the real change",
            "Review code quality, maintainability, and release readiness",
            "Prepare final delivery package and human decision summary",
        ],
        "authored_task_order": [
            "Scope the task into a minimal deliverable",
            "Prepare repo, branch, env, and runnable baseline",
            "Implement assigned change slice A with real validation",
            "Implement assigned change slice B with real validation",
            "Run scoped QA pass A on the real change",
            "Run scoped QA pass B on the real change",
            "Review code quality, maintainability, and release readiness",
            "Prepare final delivery package and human decision summary",
        ],
        "tasks": [
            {"subject": "Scope the task into a minimal deliverable", "owner": "leader", "stage": "scope", "blocked_by": [], "on_fail": [], "message_type": "", "required_sections": [], "description": "scope"},
            {"subject": "Prepare repo, branch, env, and runnable baseline", "owner": "config1", "stage": "setup", "blocked_by": ["Scope the task into a minimal deliverable"], "on_fail": [], "message_type": "SETUP_RESULT", "required_sections": ["status"], "description": "setup brief"},
            {"subject": "Implement assigned change slice A with real validation", "owner": "dev1", "stage": "implement", "blocked_by": ["Prepare repo, branch, env, and runnable baseline"], "on_fail": [], "message_type": "DEV_RESULT", "required_sections": ["status"], "description": "impl A brief"},
            {"subject": "Implement assigned change slice B with real validation", "owner": "dev2", "stage": "implement", "blocked_by": ["Prepare repo, branch, env, and runnable baseline"], "on_fail": [], "message_type": "DEV_RESULT", "required_sections": ["status"], "description": "impl B brief"},
            {"subject": "Run scoped QA pass A on the real change", "owner": "qa1", "stage": "qa", "blocked_by": ["Implement assigned change slice A with real validation", "Implement assigned change slice B with real validation"], "on_fail": ["Implement assigned change slice A with real validation", "Implement assigned change slice B with real validation"], "message_type": "QA_RESULT", "required_sections": ["status"], "description": "qa A brief"},
            {"subject": "Run scoped QA pass B on the real change", "owner": "qa2", "stage": "qa", "blocked_by": ["Implement assigned change slice A with real validation", "Implement assigned change slice B with real validation"], "on_fail": ["Implement assigned change slice A with real validation", "Implement assigned change slice B with real validation"], "message_type": "QA_RESULT", "required_sections": ["status"], "description": "qa B brief"},
            {"subject": "Review code quality, maintainability, and release readiness", "owner": "review1", "stage": "review", "blocked_by": ["Run scoped QA pass A on the real change", "Run scoped QA pass B on the real change"], "on_fail": ["Implement assigned change slice A with real validation", "Implement assigned change slice B with real validation"], "message_type": "REVIEW_RESULT", "required_sections": ["decision"], "description": "review brief"},
            {"subject": "Prepare final delivery package and human decision summary", "owner": "leader", "stage": "deliver", "blocked_by": ["Review code quality, maintainability, and release readiness"], "on_fail": [], "message_type": "", "required_sections": [], "description": "deliver brief"},
        ],
    }


def _post_scope_context(store: TaskStore) -> tuple[TaskItem, TaskUpdateContext]:
    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    for name in ["config1", "dev1", "dev2", "qa1", "qa2", "review1"]:
        TeamManager.add_member("demo", name, f"{name}-id", agent_type="general-purpose")

    scope = store.create(
        "Scope the task into a minimal deliverable",
        owner="leader",
        metadata={
            "template_stage": "scope",
            "feature_scope_required": True,
            "materialization_mode": "post-scope",
            "deferred_materialization_state": "pending_scope_completion",
            "workflow_definition": _five_step_workflow_definition(),
            "launch_brief": {
                "format": "structured_sections",
                "sections": {
                    "source_request": "Ship the feature safely",
                    "scoped_brief": "Initial scope",
                    "unknowns": [],
                    "leader_assumptions": [],
                    "out_of_scope": [],
                },
            },
        },
    )
    ctx = TaskUpdateContext(
        store=store,
        team="demo",
        runtime=RuntimeOrchestrator(team="demo"),
        release_notifier=lambda team, task, caller, message: {"messageSent": True, "taskId": task.id, "message": message},
        failure_notifier=lambda team, task, caller: None,
    )
    return scope, ctx


def test_execute_task_update_materializes_full_stack_downstream_on_real_scope_completion(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))
    store = TaskStore("demo")
    scope, ctx = _post_scope_context(store)

    wake_calls: list[list[str]] = []
    monkeypatch.setattr(
        "clawteam.services.task_update_service.wake_tasks_to_pending",
        lambda team, target_ids, caller, message_builder, repo, store, runtime, release_notifier: wake_calls.append(list(target_ids)) or [{"taskId": target_ids[0]}],
    )

    result = execute_task_update(
        task_id=scope.id,
        caller="leader",
        ctx=ctx,
        request=TaskUpdateRequest(
            status=TaskStatus.completed,
            owner=None,
            subject=None,
            description="""## Source Request
Ship the feature safely

## Scoped Brief
Deliver the backend API update and the member list UI update.

## Unknowns
- none

## Leader Assumptions
- existing tests are representative

## Out of Scope
- dashboard rewrite

## Risks/Blockers
- none

## Recommended Next Step
- explicit post-scope materialization

## FEATURE_SCOPE
{"source_request":"Ship the feature safely","scoped_brief":"Deliver the backend API update and the member list UI update.","in_scope":["backend API update","member list UI update"],"unknowns":["none"],"leader_assumptions":["existing tests are representative"],"out_of_scope":["dashboard rewrite"],"risks_blockers":["none"],"recommended_next_step":"explicit post-scope materialization","execution_shape":"full-stack","change_budget":{"allowed_layers":["web-ui","backend","api"],"allowed_operations":["edit-existing","add-ui-component","add-backend-module"],"allowed_roots":["dashboard/","server/"],"forbidden_layers":["mobile-ui"]},"initial_targets":[{"kind":"web-page","path":"dashboard/src/pages/members.tsx","exists":true,"why_in_scope":"member list UI exists","evidence":["rg hit: dashboard/src/pages/members.tsx"]},{"kind":"api-handler","path":"server/src/routes/member.ts","exists":true,"why_in_scope":"member API exists","evidence":["rg hit: server/src/routes/member.ts"]}]}
""",
            add_blocks=None,
            add_blocked_by=None,
            add_on_fail=None,
            failure_kind=None,
            failure_note=None,
            failure_root_cause=None,
            failure_evidence=None,
            failure_recommended_next_owner=None,
            failure_recommended_action=None,
            execution_id=None,
            wake_owner=False,
            message="",
            force=False,
        ),
    )

    tasks = {task.subject: task for task in store.list_tasks()}
    assert set(tasks) == {
        "Scope the task into a minimal deliverable",
        "Prepare repo, branch, env, and runnable baseline",
        "Implement assigned change slice A with real validation",
        "Implement assigned change slice B with real validation",
        "Run scoped QA pass A on the real change",
        "Run scoped QA pass B on the real change",
        "Review code quality, maintainability, and release readiness",
        "Prepare final delivery package and human decision summary",
    }
    assert tasks["Prepare repo, branch, env, and runnable baseline"].status == TaskStatus.pending
    assert tasks["Implement assigned change slice A with real validation"].status == TaskStatus.blocked
    assert tasks["Implement assigned change slice B with real validation"].status == TaskStatus.blocked
    assert tasks["Run scoped QA pass A on the real change"].metadata["on_fail"] == [
        tasks["Implement assigned change slice A with real validation"].id,
        tasks["Implement assigned change slice B with real validation"].id,
    ]
    assert tasks["Prepare repo, branch, env, and runnable baseline"].metadata["feature_scope"]["execution_shape"] == "full-stack"
    assert "## Resolved Scope Context" in tasks["Prepare repo, branch, env, and runnable baseline"].description
    assert result.effects.deferred_materialization["status"] == "materialized"
    assert result.effects.deferred_materialization["execution_shape"] == "full-stack"
    assert result.effects.deferred_materialization["lane_materialization"] == "dual_lane"
    assert tasks["Implement assigned change slice A with real validation"].metadata["lane_slice_authority"]["lane"] == "backend"
    assert tasks["Implement assigned change slice B with real validation"].metadata["lane_slice_authority"]["lane"] == "frontend"
    assert "## Lane Authority" in tasks["Implement assigned change slice A with real validation"].description
    assert wake_calls == [[tasks["Prepare repo, branch, env, and runnable baseline"].id]]


def test_execute_task_update_materializes_backend_only_subset(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))
    store = TaskStore("demo")
    scope, ctx = _post_scope_context(store)
    monkeypatch.setattr(
        "clawteam.services.task_update_service.wake_tasks_to_pending",
        lambda team, target_ids, caller, message_builder, repo, store, runtime, release_notifier: [],
    )

    execute_task_update(
        task_id=scope.id,
        caller="leader",
        ctx=ctx,
        request=TaskUpdateRequest(
            status=TaskStatus.completed,
            owner=None,
            subject=None,
            description="""## Source Request
Ship the feature safely

## Scoped Brief
Deliver only the backend API update.

## Unknowns
- none

## Leader Assumptions
- existing tests are representative

## Out of Scope
- dashboard rewrite

## Risks/Blockers
- none

## Recommended Next Step
- explicit post-scope materialization

## FEATURE_SCOPE
{"source_request":"Ship the feature safely","scoped_brief":"Deliver only the backend API update.","in_scope":["backend API update"],"unknowns":["none"],"leader_assumptions":["existing tests are representative"],"out_of_scope":["dashboard rewrite"],"risks_blockers":["none"],"recommended_next_step":"explicit post-scope materialization","execution_shape":"backend-only","change_budget":{"allowed_layers":["backend","api"],"allowed_operations":["edit-existing","add-backend-module"],"allowed_roots":["server/"],"forbidden_layers":["web-ui","mobile-ui"]},"initial_targets":[{"kind":"api-handler","path":"server/src/routes/member.ts","exists":true,"why_in_scope":"member API change required by scoped brief","evidence":["rg hit: server/src/routes/member.ts"]}]}
""",
            add_blocks=None,
            add_blocked_by=None,
            add_on_fail=None,
            failure_kind=None,
            failure_note=None,
            failure_root_cause=None,
            failure_evidence=None,
            failure_recommended_next_owner=None,
            failure_recommended_action=None,
            execution_id=None,
            wake_owner=False,
            message="",
            force=False,
        ),
    )

    subjects = {task.subject for task in store.list_tasks()}
    assert "Implement assigned change slice A with real validation" in subjects
    assert "Run scoped QA pass A on the real change" in subjects
    assert "Implement assigned change slice B with real validation" not in subjects
    assert "Run scoped QA pass B on the real change" not in subjects


def test_execute_task_update_materializes_ui_only_subset(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))
    store = TaskStore("demo")
    scope, ctx = _post_scope_context(store)
    monkeypatch.setattr(
        "clawteam.services.task_update_service.wake_tasks_to_pending",
        lambda team, target_ids, caller, message_builder, repo, store, runtime, release_notifier: [],
    )

    execute_task_update(
        task_id=scope.id,
        caller="leader",
        ctx=ctx,
        request=TaskUpdateRequest(
            status=TaskStatus.completed,
            owner=None,
            subject=None,
            description="""## Source Request
Ship the feature safely

## Scoped Brief
Deliver only the member list UI update.

## Unknowns
- none

## Leader Assumptions
- existing tests are representative

## Out of Scope
- dashboard rewrite

## Risks/Blockers
- none

## Recommended Next Step
- explicit post-scope materialization

## FEATURE_SCOPE
{"source_request":"Ship the feature safely","scoped_brief":"Deliver only the member list UI update.","in_scope":["member list UI update"],"unknowns":["none"],"leader_assumptions":["existing tests are representative"],"out_of_scope":["dashboard rewrite"],"risks_blockers":["none"],"recommended_next_step":"explicit post-scope materialization","execution_shape":"ui-only","change_budget":{"allowed_layers":["web-ui"],"allowed_operations":["edit-existing","add-ui-component","add-ui-style-file"],"allowed_roots":["dashboard/"],"forbidden_layers":["backend","api","schema","db","crawler","auth","mobile-ui"]},"initial_targets":[{"kind":"web-page","path":"dashboard/src/pages/members.tsx","exists":true,"why_in_scope":"member list UI exists","evidence":["rg hit: dashboard/src/pages/members.tsx"]}]}
""",
            add_blocks=None,
            add_blocked_by=None,
            add_on_fail=None,
            failure_kind=None,
            failure_note=None,
            failure_root_cause=None,
            failure_evidence=None,
            failure_recommended_next_owner=None,
            failure_recommended_action=None,
            execution_id=None,
            wake_owner=False,
            message="",
            force=False,
        ),
    )

    subjects = {task.subject for task in store.list_tasks()}
    assert "Implement assigned change slice B with real validation" in subjects
    assert "Run scoped QA pass B on the real change" in subjects
    assert "Implement assigned change slice A with real validation" not in subjects
    assert "Run scoped QA pass A on the real change" not in subjects


def test_execute_task_update_materializes_full_stack_mobile_and_backend_scope(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))
    store = TaskStore("demo")
    scope, ctx = _post_scope_context(store)
    monkeypatch.setattr(
        "clawteam.services.task_update_service.wake_tasks_to_pending",
        lambda team, target_ids, caller, message_builder, repo, store, runtime, release_notifier: [],
    )

    result = execute_task_update(
        task_id=scope.id,
        caller="leader",
        ctx=ctx,
        request=TaskUpdateRequest(
            status=TaskStatus.completed,
            owner=None,
            subject=None,
            description="""## Source Request
Ship the feature safely

## Scoped Brief
Deliver the mobile company directory UI update and the backend company directory API update.

## Unknowns
- none

## Leader Assumptions
- existing tests are representative

## Out of Scope
- web portal rewrite

## Risks/Blockers
- none

## Recommended Next Step
- explicit post-scope materialization

## FEATURE_SCOPE
{"source_request":"Ship the feature safely","scoped_brief":"Deliver the mobile company directory UI update and the backend company directory API update.","in_scope":["mobile company directory UI update","backend company directory API update"],"unknowns":["none"],"leader_assumptions":["existing tests are representative"],"out_of_scope":["web portal rewrite"],"risks_blockers":["none"],"recommended_next_step":"explicit post-scope materialization","execution_shape":"full-stack","change_budget":{"allowed_layers":["mobile-ui","backend","api"],"allowed_operations":["edit-existing","add-ui-component","add-backend-module"],"allowed_roots":["mobile/app/","server/"],"forbidden_layers":["web-ui"]},"initial_targets":[{"kind":"mobile-screen","path":"mobile/app/companies.tsx","exists":true,"why_in_scope":"company directory screen already exists","evidence":["rg hit: mobile/app/companies.tsx"]},{"kind":"api-handler","path":"server/src/routes/companies.ts","exists":true,"why_in_scope":"company directory API already exists","evidence":["rg hit: server/src/routes/companies.ts"]}]}
""",
            add_blocks=None,
            add_blocked_by=None,
            add_on_fail=None,
            failure_kind=None,
            failure_note=None,
            failure_root_cause=None,
            failure_evidence=None,
            failure_recommended_next_owner=None,
            failure_recommended_action=None,
            execution_id=None,
            wake_owner=False,
            message="",
            force=False,
        ),
    )

    tasks = {task.subject: task for task in store.list_tasks()}
    assert result.effects.deferred_materialization["execution_shape"] == "full-stack"
    assert tasks["Prepare repo, branch, env, and runnable baseline"].metadata["feature_scope"]["change_budget"]["allowed_layers"] == ["mobile-ui", "backend", "api"]
    assert "Implement assigned change slice A with real validation" in tasks
    assert "Implement assigned change slice B with real validation" in tasks


def test_execute_task_update_materializes_single_lane_when_full_stack_scope_lacks_disjoint_lane_authority(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))
    store = TaskStore("demo")
    scope, ctx = _post_scope_context(store)
    monkeypatch.setattr(
        "clawteam.services.task_update_service.wake_tasks_to_pending",
        lambda team, target_ids, caller, message_builder, repo, store, runtime, release_notifier: [],
    )

    result = execute_task_update(
        task_id=scope.id,
        caller="leader",
        ctx=ctx,
        request=TaskUpdateRequest(
            status=TaskStatus.completed,
            owner=None,
            subject=None,
            description="""## Source Request
Ship the members login feature safely

## Scoped Brief
Deliver the members login backend API update and the existing members login UI update.

## Unknowns
- none

## Leader Assumptions
- existing tests are representative

## Out of Scope
- workflow redesign

## Risks/Blockers
- none

## Recommended Next Step
- explicit post-scope materialization

## FEATURE_SCOPE
{"source_request":"Ship the members login feature safely","scoped_brief":"Deliver the members login backend API update and the existing members login UI update.","in_scope":["members login backend API update","members login UI update"],"unknowns":["none"],"leader_assumptions":["existing tests are representative"],"out_of_scope":["workflow redesign"],"risks_blockers":["none"],"recommended_next_step":"explicit post-scope materialization","execution_shape":"full-stack","change_budget":{"allowed_layers":["web-ui","backend","api"],"allowed_operations":["edit-existing","add-ui-component","add-backend-module"],"allowed_roots":["src/"],"forbidden_layers":["mobile-ui"]},"initial_targets":[{"kind":"web-flow","path":"frontend/src/features/members/login.tsx","exists":true,"why_in_scope":"existing members login UI requires update","evidence":["rg hit: frontend/src/features/members/login.tsx"]},{"kind":"api-handler","path":"server/src/routes/member-login.ts","exists":true,"why_in_scope":"existing members login API requires update","evidence":["rg hit: server/src/routes/member-login.ts"]}]}
""",
            add_blocks=None,
            add_blocked_by=None,
            add_on_fail=None,
            failure_kind=None,
            failure_note=None,
            failure_root_cause=None,
            failure_evidence=None,
            failure_recommended_next_owner=None,
            failure_recommended_action=None,
            execution_id=None,
            wake_owner=False,
            message="",
            force=False,
        ),
    )

    tasks = {task.subject: task for task in store.list_tasks()}
    assert result.effects.deferred_materialization["execution_shape"] == "full-stack"
    assert result.effects.deferred_materialization["lane_materialization"] == "single_lane_fail_closed"
    assert "Implement assigned change slice A with real validation" in tasks
    assert "Run scoped QA pass A on the real change" in tasks
    assert "Implement assigned change slice B with real validation" not in tasks
    assert "Run scoped QA pass B on the real change" not in tasks
    assert tasks["Implement assigned change slice A with real validation"].metadata["lane_slice_authority"]["lane"] == "combined"
    assert tasks["Implement assigned change slice A with real validation"].metadata["lane_slice_authority"]["meaningful"] is True
    assert tasks["Implement assigned change slice A with real validation"].metadata["lane_slice_authority"]["allowed_roots"] == ["src/"]
    assert set(tasks["Implement assigned change slice A with real validation"].metadata["lane_slice_authority"]["allowed_layers"]) == {"web-ui", "backend", "api"}


def test_execute_task_update_post_scope_mode_fails_closed_when_feature_scope_shape_is_missing(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))
    store = TaskStore("demo")
    scope, ctx = _post_scope_context(store)
    monkeypatch.setattr(
        "clawteam.services.task_update_service.wake_tasks_to_pending",
        lambda team, target_ids, caller, message_builder, repo, store, runtime, release_notifier: [],
    )

    with pytest.raises(TaskUpdateValidationError, match=r"FEATURE_SCOPE\.execution_shape"):
        execute_task_update(
            task_id=scope.id,
            caller="leader",
            ctx=ctx,
            request=TaskUpdateRequest(
                status=TaskStatus.completed,
                owner=None,
                subject=None,
                description="""## Source Request
Ship the feature safely

## Scoped Brief
Deliver only the minimal safe fix.

## Unknowns
- none

## Leader Assumptions
- existing tests are representative

## Out of Scope
- dashboard rewrite

## Risks/Blockers
- none

## Recommended Next Step
- explicit post-scope materialization

## FEATURE_SCOPE
{"source_request":"Ship the feature safely","scoped_brief":"Deliver only the minimal safe fix.","in_scope":["minimal safe fix"],"unknowns":["none"],"leader_assumptions":["existing tests are representative"],"out_of_scope":["dashboard rewrite"],"risks_blockers":["none"],"recommended_next_step":"explicit post-scope materialization"}
""",
                add_blocks=None,
                add_blocked_by=None,
                add_on_fail=None,
                failure_kind=None,
                failure_note=None,
                failure_root_cause=None,
                failure_evidence=None,
                failure_recommended_next_owner=None,
                failure_recommended_action=None,
                execution_id=None,
                wake_owner=False,
                message="",
                force=False,
            ),
        )
    assert {task.subject for task in store.list_tasks()} == {"Scope the task into a minimal deliverable"}


def test_execute_task_update_post_scope_mode_fails_closed_when_feature_scope_shape_is_invalid(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))
    store = TaskStore("demo")
    scope, ctx = _post_scope_context(store)
    monkeypatch.setattr(
        "clawteam.services.task_update_service.wake_tasks_to_pending",
        lambda team, target_ids, caller, message_builder, repo, store, runtime, release_notifier: [],
    )

    with pytest.raises(TaskUpdateValidationError, match=r"FEATURE_SCOPE\.execution_shape"):
        execute_task_update(
            task_id=scope.id,
            caller="leader",
            ctx=ctx,
            request=TaskUpdateRequest(
                status=TaskStatus.completed,
                owner=None,
                subject=None,
                description="""## Source Request
Ship the feature safely

## Scoped Brief
Deliver only the backend API update.

## Unknowns
- none

## Leader Assumptions
- existing tests are representative

## Out of Scope
- dashboard rewrite

## Risks/Blockers
- none

## Recommended Next Step
- explicit post-scope materialization

## FEATURE_SCOPE
{"source_request":"Ship the feature safely","scoped_brief":"Deliver only the backend API update.","in_scope":["backend API update"],"unknowns":["none"],"leader_assumptions":["existing tests are representative"],"out_of_scope":["dashboard rewrite"],"risks_blockers":["none"],"recommended_next_step":"explicit post-scope materialization","execution_shape":"frontend-only","change_budget":{"allowed_layers":["web-ui"],"allowed_operations":["edit-existing"],"allowed_roots":["dashboard/"],"forbidden_layers":["backend"]}}
""",
                add_blocks=None,
                add_blocked_by=None,
                add_on_fail=None,
                failure_kind=None,
                failure_note=None,
                failure_root_cause=None,
                failure_evidence=None,
                failure_recommended_next_owner=None,
                failure_recommended_action=None,
                execution_id=None,
                wake_owner=False,
                message="",
                force=False,
            ),
        )
    assert {task.subject for task in store.list_tasks()} == {"Scope the task into a minimal deliverable"}


def test_execute_task_update_records_and_propagates_scope_audit_warnings(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))

    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    TeamManager.add_member("demo", "config1", "config1-id", agent_type="general-purpose")

    store = TaskStore("demo")
    scope = store.create(
        "Scope the task into a minimal deliverable",
        owner="leader",
        metadata={
            "template_stage": "scope",
            "launch_brief": {
                "format": "structured_sections",
                "sections": {
                    "source_request": "Polish the member list UI.",
                    "scoped_brief": "Initial scope",
                    "unknowns": [],
                    "leader_assumptions": [],
                    "out_of_scope": [],
                },
            },
        },
    )
    setup = store.create(
        "Prepare repo, branch, env, and runnable baseline",
        owner="config1",
        blocked_by=[scope.id],
        metadata={"template_stage": "setup"},
        description="Original setup brief",
    )

    monkeypatch.setattr(
        "clawteam.services.task_update_service.wake_tasks_to_pending",
        lambda team, target_ids, caller, message_builder, repo, store, runtime, release_notifier: [
            {"taskId": target_ids[0], "message": message_builder(store.get(target_ids[0]))}
        ],
    )

    result = execute_task_update(
        task_id=scope.id,
        caller="leader",
        ctx=TaskUpdateContext(
            store=store,
            team="demo",
            runtime=RuntimeOrchestrator(team="demo"),
            release_notifier=lambda team, task, caller, message: {"messageSent": True, "message": message},
            failure_notifier=lambda team, task, caller: None,
        ),
        request=TaskUpdateRequest(
            status=TaskStatus.completed,
            owner=None,
            subject=None,
            description="""## Source Request
Polish the member list UI.

## Scoped Brief
Polish the member list UI using the existing tests are representative assumption while final prod env remains required for rollout.

## Unknowns
- final prod env

## Leader Assumptions
- existing tests are representative

## Out of Scope
- dashboard rewrite
""",
            add_blocks=None,
            add_blocked_by=None,
            add_on_fail=None,
            failure_kind=None,
            failure_note=None,
            failure_root_cause=None,
            failure_evidence=None,
            failure_recommended_next_owner=None,
            failure_recommended_action=None,
            execution_id=None,
            wake_owner=False,
            message="",
            force=False,
        ),
    )

    refreshed_scope = store.get(scope.id)
    refreshed_setup = store.get(setup.id)

    assert result.task.status == TaskStatus.completed
    assert [warning["code"] for warning in refreshed_scope.metadata["scope_audit_warnings"]] == [
        "unknowns_promoted_to_scope",
        "assumptions_promoted_to_scope",
    ]
    assert [warning["code"] for warning in refreshed_setup.metadata["scope_audit_warnings"]] == [
        "unknowns_promoted_to_scope",
        "assumptions_promoted_to_scope",
    ]
    assert "### Scope Audit Warnings" in refreshed_setup.description
    assert "[unknowns_promoted_to_scope]" in refreshed_setup.description
    assert "final prod env" in refreshed_setup.description
    assert "[assumptions_promoted_to_scope]" in refreshed_setup.description
    assert "existing tests are representative" in refreshed_setup.description


def test_execute_task_update_preserves_empty_scope_audit_warnings_as_empty_list(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))

    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")

    store = TaskStore("demo")
    scope = store.create(
        "Scope the task into a minimal deliverable",
        owner="leader",
        metadata={
            "template_stage": "scope",
            "launch_brief": {
                "format": "structured_sections",
                "sections": {
                    "source_request": "Ship the feature safely",
                    "scoped_brief": "Initial scope",
                    "unknowns": [],
                    "leader_assumptions": [],
                    "out_of_scope": [],
                },
            },
        },
    )

    result = execute_task_update(
        task_id=scope.id,
        caller="leader",
        ctx=TaskUpdateContext(
            store=store,
            team="demo",
            runtime=RuntimeOrchestrator(team="demo"),
            release_notifier=lambda team, task, caller, message: None,
            failure_notifier=lambda team, task, caller: None,
        ),
        request=TaskUpdateRequest(
            status=TaskStatus.completed,
            owner=None,
            subject=None,
            description="""## Source Request
Ship the feature safely

## Scoped Brief
Deliver only the minimal safe fix.

## Unknowns
- none

## Leader Assumptions
- existing tests are representative

## Out of Scope
- dashboard rewrite
""",
            add_blocks=None,
            add_blocked_by=None,
            add_on_fail=None,
            failure_kind=None,
            failure_note=None,
            failure_root_cause=None,
            failure_evidence=None,
            failure_recommended_next_owner=None,
            failure_recommended_action=None,
            execution_id=None,
            wake_owner=False,
            message="",
            force=False,
        ),
    )

    assert result.task.metadata["scope_audit_warnings"] == []
