from __future__ import annotations

from unittest.mock import patch

import pytest

from clawteam.runtime.orchestrator import RuntimeOrchestrator
from clawteam.services.task_update_service import (
    TaskUpdateContext,
    TaskUpdateEffects,
    TaskUpdatePlan,
    TaskUpdateRequest,
    TaskUpdateResult,
    TaskUpdateValidationError,
    execute_task_update,
    execute_task_update_effects,
)
from clawteam.team.manager import TeamManager
from clawteam.team.models import TaskStatus
from clawteam.team.tasks import TaskStore, TransitionApplyResult


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
