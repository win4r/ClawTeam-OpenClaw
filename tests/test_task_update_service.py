from __future__ import annotations

from unittest.mock import patch

from clawteam.services.task_update_service import (
    TaskUpdateRequest,
    TaskUpdateValidationError,
    build_failure_metadata,
    execute_task_update,
    execute_task_update_effects,
    merge_update_metadata,
    plan_task_update,
    plan_task_update_followups,
)
from clawteam.team.mailbox import MailboxManager
from clawteam.team.manager import TeamManager
from clawteam.team.models import TaskItem, TaskStatus
from clawteam.team.tasks import TaskStore


def test_build_failure_metadata_rejects_failure_options_without_failed_status():
    try:
        build_failure_metadata(
            status=TaskStatus.pending,
            failure_kind=None,
            failure_note="still broken",
            failure_root_cause=None,
            failure_evidence=None,
            failure_recommended_next_owner=None,
            failure_recommended_action=None,
        )
    except TaskUpdateValidationError as exc:
        assert "failure options require --status failed" in str(exc)
    else:
        raise AssertionError("expected TaskUpdateValidationError")


def test_build_failure_metadata_requires_structured_fields_for_complex_failures():
    try:
        build_failure_metadata(
            status=TaskStatus.failed,
            failure_kind="complex",
            failure_note=None,
            failure_root_cause="owner unclear",
            failure_evidence=None,
            failure_recommended_next_owner=None,
            failure_recommended_action=None,
        )
    except TaskUpdateValidationError as exc:
        assert "complex fail requires" in str(exc)
        assert "--failure-evidence" in str(exc)
    else:
        raise AssertionError("expected TaskUpdateValidationError")


def test_merge_update_metadata_merges_on_fail_without_duplicates():
    existing = TaskItem(subject="review", metadata={"on_fail": ["task-a"]})

    merged = merge_update_metadata(
        existing,
        {"failure_kind": "regular", "failure_note": "repro ready"},
        ["task-b", "task-a"],
    )

    assert merged == {
        "failure_kind": "regular",
        "failure_note": "repro ready",
        "on_fail": ["task-a", "task-b"],
    }


def test_plan_task_update_followups_wakes_unblocked_dependents():
    existing = TaskItem(id="task-1", subject="impl")
    blocked = TaskItem(id="task-2", subject="qa", status=TaskStatus.blocked, blocked_by=["task-1"])
    already_pending = TaskItem(id="task-3", subject="docs", status=TaskStatus.pending, blocked_by=["task-1"])

    plan = plan_task_update_followups(
        existing=existing,
        status=TaskStatus.completed,
        all_tasks=[blocked, already_pending],
        failure_metadata=None,
    )

    assert plan["dependent_ids_to_wake"] == ["task-2"]
    assert plan["failed_targets_to_wake"] == []


def test_plan_task_update_followups_reopens_regular_fail_targets_only_after_actual_start():
    existing = TaskItem(
        id="task-qa",
        subject="qa",
        started_at="2026-03-22T00:00:00+00:00",
        metadata={"on_fail": ["task-impl"]},
    )

    plan = plan_task_update_followups(
        existing=existing,
        status=TaskStatus.failed,
        all_tasks=[],
        failure_metadata={"failure_kind": "regular"},
    )

    assert plan["dependent_ids_to_wake"] == []
    assert plan["failed_targets_to_wake"] == ["task-impl"]


def test_plan_task_update_combines_metadata_and_followups():
    existing = TaskItem(
        id="task-qa",
        subject="qa",
        started_at="2026-03-22T00:00:00+00:00",
        metadata={"on_fail": ["task-impl"]},
    )
    blocked = TaskItem(id="task-docs", subject="docs", status=TaskStatus.blocked, blocked_by=["task-qa"])

    plan = plan_task_update(
        existing=existing,
        status=TaskStatus.failed,
        all_tasks=[blocked],
        failure_metadata={"failure_kind": "regular", "failure_note": "clear repro"},
        add_on_fail_list=["task-dev", "task-impl"],
    )

    assert plan.metadata_to_apply == {
        "failure_kind": "regular",
        "failure_note": "clear repro",
        "on_fail": ["task-impl", "task-dev"],
    }
    assert plan.failed_targets_to_wake == ["task-impl"]
    assert plan.dependent_ids_to_wake == []


def test_execute_task_update_builds_full_result_and_updates_store(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))

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
        team="demo",
        task_id=qa.id,
        caller="qa1",
        store=store,
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
            wake_owner=False,
            message="",
            force=False,
        ),
    )

    assert result.task.status == TaskStatus.failed
    assert result.plan.failed_targets_to_wake == []
    assert result.effects.failure_notice is not None
    assert result.effects.failure_notice["failureNotice"] == "sent"
    leader_messages = MailboxManager("demo").peek("leader")
    assert any("COMPLEX FAIL:" in (msg.content or "") for msg in leader_messages)


def test_execute_task_update_effects_handles_failure_notice_and_reopen_release(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))

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
            metadata={"failure_kind": "complex", "failure_root_cause": "ownership unclear", "failure_evidence": "cross-cutting regression", "failure_recommended_next_owner": "leader", "failure_recommended_action": "triage owner"},
        )

    monkeypatch.setattr(
        "clawteam.services.task_update_service.wake_tasks_to_pending",
        lambda *args, **kwargs: [{"taskId": impl.id, "owner": "dev1", "respawned": False}],
    )

    effects = execute_task_update_effects(
        team="demo",
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
    leader_messages = MailboxManager("demo").peek("leader")
    assert any("COMPLEX FAIL:" in (msg.content or "") for msg in leader_messages)
