from __future__ import annotations

from clawteam.task.transition import (
    TaskTransitionRequest,
    TaskTransitionValidationError,
    build_failure_metadata,
    merge_transition_metadata,
    plan_task_transition,
    plan_task_transition_followups,
)
from clawteam.team.models import TaskItem, TaskStatus


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
    except TaskTransitionValidationError as exc:
        assert "failure options require --status failed" in str(exc)
    else:
        raise AssertionError("expected TaskTransitionValidationError")


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
    except TaskTransitionValidationError as exc:
        assert "complex fail requires" in str(exc)
        assert "--failure-evidence" in str(exc)
    else:
        raise AssertionError("expected TaskTransitionValidationError")


def test_merge_transition_metadata_merges_on_fail_without_duplicates():
    existing = TaskItem(subject="review", metadata={"on_fail": ["task-a"]})

    merged = merge_transition_metadata(
        existing,
        {"failure_kind": "regular", "failure_note": "repro ready"},
        ["task-b", "task-a"],
    )

    assert merged == {
        "failure_kind": "regular",
        "failure_note": "repro ready",
        "on_fail": ["task-a", "task-b"],
    }


def test_plan_task_transition_followups_wakes_unblocked_dependents():
    existing = TaskItem(id="task-1", subject="impl")
    blocked = TaskItem(id="task-2", subject="qa", status=TaskStatus.blocked, blocked_by=["task-1"])
    already_pending = TaskItem(id="task-3", subject="docs", status=TaskStatus.pending, blocked_by=["task-1"])

    plan = plan_task_transition_followups(
        existing=existing,
        status=TaskStatus.completed,
        all_tasks=[blocked, already_pending],
        failure_metadata=None,
    )

    assert plan["dependent_ids_to_wake"] == ["task-2"]
    assert plan["failed_targets_to_wake"] == []


def test_plan_task_transition_followups_reopens_regular_fail_targets_only_after_actual_start():
    existing = TaskItem(
        id="task-qa",
        subject="qa",
        started_at="2026-03-22T00:00:00+00:00",
        metadata={"on_fail": ["task-impl"]},
    )

    plan = plan_task_transition_followups(
        existing=existing,
        status=TaskStatus.failed,
        all_tasks=[],
        failure_metadata={"failure_kind": "regular"},
    )

    assert plan["dependent_ids_to_wake"] == []
    assert plan["failed_targets_to_wake"] == ["task-impl"]


def test_plan_task_transition_combines_metadata_and_followups():
    existing = TaskItem(
        id="task-qa",
        subject="qa",
        started_at="2026-03-22T00:00:00+00:00",
        metadata={"on_fail": ["task-impl"]},
    )
    blocked = TaskItem(id="task-docs", subject="docs", status=TaskStatus.blocked, blocked_by=["task-qa"])

    plan = plan_task_transition(
        existing=existing,
        request=TaskTransitionRequest(
            status=TaskStatus.failed,
            add_on_fail=["task-dev", "task-impl"],
            failure_kind="regular",
            failure_note="clear repro",
            failure_root_cause=None,
            failure_evidence=None,
            failure_recommended_next_owner=None,
            failure_recommended_action=None,
        ),
        all_tasks=[blocked],
    )

    assert plan.metadata_to_apply == {
        "failure_kind": "regular",
        "failure_note": "clear repro",
        "on_fail": ["task-impl", "task-dev"],
    }
    assert plan.failed_targets_to_wake == ["task-impl"]
    assert plan.dependent_ids_to_wake == []
