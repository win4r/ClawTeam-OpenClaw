from __future__ import annotations

from unittest.mock import patch

from clawteam.runtime.orchestrator import RuntimeOrchestrator
from clawteam.services.task_update_service import (
    TaskUpdateContext,
    TaskUpdateRequest,
    execute_task_update,
    execute_task_update_effects,
)
from clawteam.team.manager import TeamManager
from clawteam.team.models import TaskStatus
from clawteam.team.tasks import TaskStore


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
    assert result.plan.failed_targets_to_wake == []
    assert result.effects.failure_notice is not None
    assert result.effects.failure_notice["failureNotice"] == "sent"
    assert notices == [{"team": "demo", "task": qa.id, "caller": "qa1", "kind": "complex"}]


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
    assert result.transition_case == "recover_watchdog_failed_completion"
    assert result.task.metadata["recovered_from_watchdog_failure"] is True
    assert result.task.metadata["watchdog_recovered_by"] == "dev1"
    assert "failure_root_cause" not in result.task.metadata
    assert "failure_evidence" not in result.task.metadata



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

    effects = execute_task_update_effects(
        ctx=TaskUpdateContext(
            store=store,
            team="demo",
            runtime=RuntimeOrchestrator(team="demo"),
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
    assert notices == [{"team": "demo", "task": qa.id, "caller": "qa1", "kind": "complex"}]
