from __future__ import annotations

from clawteam.task.transition import (
    CLAIM_EXECUTION_CASE,
    EXECUTION_TERMINAL_CASE,
    REOPEN_TASK_CASE,
    ClaimExecutionEvent,
    ReopenTaskEvent,
    TaskTransitionRequest,
    TaskTransitionValidationError,
    TerminalWritebackEvent,
    WATCHDOG_RECOVERY_CASE,
    build_failure_metadata,
    merge_transition_metadata,
    plan_claim_execution,
    plan_reopen_task,
    plan_task_transition,
    plan_task_transition_followups,
    plan_terminal_writeback,
    plan_watchdog_failed_completion_recovery,
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


def test_plan_watchdog_failed_completion_recovery_accepts_owner_completed():
    existing = TaskItem(
        id="task-1",
        subject="impl",
        owner="dev1",
        status=TaskStatus.failed,
        updated_at="2026-03-23T00:00:05+00:00",
        metadata={
            "failure_root_cause": "worker agent turn stalled without terminal task update",
            "session_key": "clawteam-demo-dev1",
            "watchdog_decision_at": "2026-03-23T00:00:00+00:00",
            "failure_evidence": "watchdog",
        },
    )

    decision = plan_watchdog_failed_completion_recovery(
        existing=existing,
        caller="dev1",
        requested_status=TaskStatus.completed,
    )

    assert decision is not None
    assert decision.accepted is True
    assert decision.case_name == WATCHDOG_RECOVERY_CASE
    assert decision.metadata_to_apply is not None
    assert decision.metadata_to_apply["recovered_from_watchdog_failure"] is True
    assert decision.metadata_to_apply["watchdog_recovered_by"] == "dev1"
    assert "failure_root_cause" in decision.metadata_keys_to_remove


def test_plan_watchdog_failed_completion_recovery_rejects_non_owner():
    existing = TaskItem(
        id="task-1",
        subject="impl",
        owner="dev1",
        status=TaskStatus.failed,
        updated_at="2026-03-23T00:00:05+00:00",
        metadata={
            "failure_root_cause": "worker agent turn stalled without terminal task update",
            "session_key": "clawteam-demo-dev1",
            "watchdog_decision_at": "2026-03-23T00:00:00+00:00",
        },
    )

    decision = plan_watchdog_failed_completion_recovery(
        existing=existing,
        caller="qa1",
        requested_status=TaskStatus.completed,
    )

    assert decision is not None
    assert decision.accepted is False
    assert decision.case_name == WATCHDOG_RECOVERY_CASE
    assert decision.rejection_reason == "watchdog_recovery_requires_owner"


def test_plan_watchdog_failed_completion_recovery_ignores_non_watchdog_failures():
    existing = TaskItem(
        id="task-1",
        subject="impl",
        owner="dev1",
        status=TaskStatus.failed,
        updated_at="2026-03-23T00:00:05+00:00",
        metadata={
            "failure_root_cause": "ordinary regression",
            "watchdog_decision_at": "2026-03-23T00:00:00+00:00",
        },
    )

    decision = plan_watchdog_failed_completion_recovery(
        existing=existing,
        caller="dev1",
        requested_status=TaskStatus.completed,
    )

    assert decision is None


def test_plan_claim_execution_accepts_pending_task():
    task = TaskItem(id="task-1", subject="impl", status=TaskStatus.pending)

    decision = plan_claim_execution(existing=task, event=ClaimExecutionEvent(caller="dev1"))

    assert decision.accepted is True
    assert decision.case_name == CLAIM_EXECUTION_CASE


def test_plan_terminal_writeback_rejects_stale_execution():
    task = TaskItem(
        id="task-1",
        subject="impl",
        status=TaskStatus.in_progress,
        active_execution_id="task-1-exec-2",
        active_execution_owner="dev1",
    )

    decision = plan_terminal_writeback(
        existing=task,
        event=TerminalWritebackEvent(
            caller="dev1",
            status=TaskStatus.completed,
            execution_id="task-1-exec-1",
        ),
    )

    assert decision is not None
    assert decision.accepted is False
    assert decision.case_name == EXECUTION_TERMINAL_CASE
    assert decision.rejection_reason == "stale_execution"


def test_plan_reopen_task_accepts_failed_task():
    task = TaskItem(id="task-1", subject="impl", status=TaskStatus.failed)

    decision = plan_reopen_task(existing=task, event=ReopenTaskEvent(caller="leader"))

    assert decision.accepted is True
    assert decision.case_name == REOPEN_TASK_CASE
