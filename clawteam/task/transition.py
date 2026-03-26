"""Task transition policy: validation, metadata planning, and follow-up planning."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from clawteam.team.models import TaskItem, TaskStatus
from clawteam.workflow.topology import WorkflowTopology


COMPLEX_FAILURE_REQUIRED_FLAGS = {
    "--failure-root-cause": "failure_root_cause",
    "--failure-evidence": "failure_evidence",
    "--failure-recommended-next-owner": "failure_recommended_next_owner",
    "--failure-recommended-action": "failure_recommended_action",
}
BLOCKED_ROUTING_REQUIRED_FLAGS = {
    "--failure-root-cause": "failure_root_cause",
    "--failure-evidence": "failure_evidence",
    "--failure-recommended-next-owner": "failure_recommended_next_owner",
    "--failure-recommended-action": "failure_recommended_action",
}


class TaskTransitionValidationError(ValueError):
    """Raised when task transition options violate workflow policy."""


WATCHDOG_FAILURE_ROOT_CAUSE = "worker agent turn stalled without terminal task update"
WATCHDOG_RECOVERY_CASE = "recover_watchdog_failed_completion"
EXECUTION_TERMINAL_CASE = "execution_scoped_terminal_writeback"
CLAIM_EXECUTION_CASE = "claim_execution"
REOPEN_TASK_CASE = "reopen_task"
DUPLICATE_TERMINAL_SAME_STATUS = "duplicate_terminal_same_status"
DUPLICATE_TERMINAL_CONFLICTING_STATUS = "duplicate_terminal_conflicting_status"
WATCHDOG_RECOVERY_FAILURE_KEYS = [
    "failure_kind",
    "failure_root_cause",
    "failure_evidence",
    "failure_note",
    "failure_recommended_next_owner",
    "failure_recommended_action",
    "stall_phase",
    "session_key",
]


@dataclass(frozen=True)
class TaskTransitionRequest:
    status: TaskStatus | None
    add_on_fail: list[str] | None
    failure_kind: str | None
    failure_note: str | None
    failure_root_cause: str | None
    failure_evidence: str | None
    failure_recommended_next_owner: str | None
    failure_recommended_action: str | None


@dataclass(frozen=True)
class ClaimExecutionEvent:
    caller: str
    force: bool = False


@dataclass(frozen=True)
class TerminalWritebackEvent:
    caller: str
    status: TaskStatus
    execution_id: str | None = None
    runtime_path: bool = False


@dataclass(frozen=True)
class ReopenTaskEvent:
    caller: str


@dataclass(frozen=True)
class TaskTransitionPlan:
    metadata_to_apply: dict[str, Any] | None
    dependent_ids_to_wake: list[str]
    failed_targets_to_wake: list[str]


@dataclass(frozen=True)
class TaskTransitionDecision:
    accepted: bool
    case_name: str
    rejection_reason: str | None = None
    metadata_to_apply: dict[str, Any] | None = None
    metadata_keys_to_remove: list[str] | None = None


def build_failure_metadata(
    *,
    status: TaskStatus | None,
    failure_kind: str | None,
    failure_note: str | None,
    failure_root_cause: str | None,
    failure_evidence: str | None,
    failure_recommended_next_owner: str | None,
    failure_recommended_action: str | None,
) -> dict[str, str] | None:
    """Validate failure options and normalize metadata payload."""
    option_values = {
        "failure_kind": failure_kind,
        "failure_note": failure_note,
        "failure_root_cause": failure_root_cause,
        "failure_evidence": failure_evidence,
        "failure_recommended_next_owner": failure_recommended_next_owner,
        "failure_recommended_action": failure_recommended_action,
    }

    if status == TaskStatus.failed:
        kind = (failure_kind or "complex").strip().lower()
        if kind not in ("regular", "complex"):
            raise TaskTransitionValidationError("--failure-kind must be regular or complex")

        failure_metadata: dict[str, str] = {"failure_kind": kind}
        for key, value in option_values.items():
            if key == "failure_kind":
                continue
            if value and value.strip():
                failure_metadata[key] = value.strip()

        if kind == "complex":
            missing = [
                flag
                for flag, key in COMPLEX_FAILURE_REQUIRED_FLAGS.items()
                if not (option_values.get(key) or "").strip()
            ]
            if missing:
                raise TaskTransitionValidationError(f"complex fail requires: {', '.join(missing)}")

        return failure_metadata

    if status == TaskStatus.blocked:
        if failure_kind and failure_kind.strip():
            raise TaskTransitionValidationError("--failure-kind is not allowed with --status blocked")
        blocked_option_values = {
            "failure_note": failure_note,
            "failure_root_cause": failure_root_cause,
            "failure_evidence": failure_evidence,
            "failure_recommended_next_owner": failure_recommended_next_owner,
            "failure_recommended_action": failure_recommended_action,
        }
        if not any((value or "").strip() for value in blocked_option_values.values()):
            return None

        missing = [
            flag
            for flag, key in BLOCKED_ROUTING_REQUIRED_FLAGS.items()
            if not (blocked_option_values.get(key) or "").strip()
        ]
        if missing:
            raise TaskTransitionValidationError(f"blocked routing requires: {', '.join(missing)}")

        blocked_metadata: dict[str, str] = {}
        if failure_note and failure_note.strip():
            blocked_metadata["blocked_note"] = failure_note.strip()
        blocked_metadata["blocked_root_cause"] = (failure_root_cause or "").strip()
        blocked_metadata["blocked_evidence"] = (failure_evidence or "").strip()
        blocked_metadata["blocked_recommended_next_owner"] = (failure_recommended_next_owner or "").strip()
        blocked_metadata["blocked_recommended_action"] = (failure_recommended_action or "").strip()
        return blocked_metadata

    if any((value or "").strip() for value in option_values.values()):
        raise TaskTransitionValidationError("failure options require --status failed or --status blocked")
    return None


def merge_transition_metadata(
    existing: TaskItem,
    failure_metadata: dict[str, str] | None,
    add_on_fail_list: list[str] | None,
) -> dict[str, Any] | None:
    """Merge transition metadata patches without duplicating on_fail targets."""
    merged_metadata: dict[str, Any] = dict(failure_metadata or {})
    if add_on_fail_list:
        current_on_fail = list(existing.metadata.get("on_fail", []))
        for target in add_on_fail_list:
            if target not in current_on_fail:
                current_on_fail.append(target)
        merged_metadata["on_fail"] = current_on_fail
    return merged_metadata or None


def plan_task_transition_followups(
    *,
    existing: TaskItem,
    status: TaskStatus | None,
    all_tasks: list[TaskItem],
    failure_metadata: dict[str, str] | None,
) -> dict[str, list[str]]:
    """Plan transition follow-ups implied by a task status update."""
    topology = WorkflowTopology(all_tasks)
    dependent_ids_to_wake: list[str] = []
    failed_targets_to_wake: list[str] = []

    if status == TaskStatus.completed:
        dependent_ids_to_wake = topology.wake_on_complete(existing.id)
    elif status == TaskStatus.failed and failure_metadata:
        if failure_metadata.get("failure_kind") == "regular":
            failed_targets_to_wake = topology.wake_on_regular_failure(existing)

    return {
        "dependent_ids_to_wake": dependent_ids_to_wake,
        "failed_targets_to_wake": failed_targets_to_wake,
    }


def _parse_iso_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def plan_claim_execution(
    *,
    existing: TaskItem,
    event: ClaimExecutionEvent,
) -> TaskTransitionDecision:
    if existing.status not in (TaskStatus.pending, TaskStatus.blocked):
        return TaskTransitionDecision(
            accepted=False,
            case_name=CLAIM_EXECUTION_CASE,
            rejection_reason="claim_requires_pending_or_blocked_task",
        )
    if existing.locked_by and existing.locked_by != event.caller and not event.force:
        return TaskTransitionDecision(
            accepted=False,
            case_name=CLAIM_EXECUTION_CASE,
            rejection_reason="task_locked_by_other_agent",
        )
    return TaskTransitionDecision(
        accepted=True,
        case_name=CLAIM_EXECUTION_CASE,
    )


def plan_execution_scoped_terminal_writeback(
    *,
    existing: TaskItem,
    caller: str,
    requested_status: TaskStatus | None,
    execution_id: str | None,
    runtime_path: bool = False,
) -> TaskTransitionDecision | None:
    if requested_status not in (TaskStatus.completed, TaskStatus.failed):
        return None
    if existing.blocked_by or existing.status == TaskStatus.blocked:
        return TaskTransitionDecision(
            accepted=False,
            case_name=EXECUTION_TERMINAL_CASE,
            rejection_reason="task_still_blocked",
        )
    if not execution_id:
        if runtime_path:
            return TaskTransitionDecision(
                accepted=False,
                case_name=EXECUTION_TERMINAL_CASE,
                rejection_reason="missing_execution_id",
            )
        return None
    if not existing.active_execution_id:
        if existing.last_terminal_execution_id and execution_id == existing.last_terminal_execution_id:
            duplicate_reason = (
                DUPLICATE_TERMINAL_SAME_STATUS
                if existing.last_terminal_status == requested_status.value
                else DUPLICATE_TERMINAL_CONFLICTING_STATUS
            )
            return TaskTransitionDecision(
                accepted=False,
                case_name=EXECUTION_TERMINAL_CASE,
                rejection_reason=duplicate_reason,
            )
        return TaskTransitionDecision(
            accepted=False,
            case_name=EXECUTION_TERMINAL_CASE,
            rejection_reason="no_active_execution",
        )
    if execution_id != existing.active_execution_id:
        return TaskTransitionDecision(
            accepted=False,
            case_name=EXECUTION_TERMINAL_CASE,
            rejection_reason="stale_execution",
        )
    if existing.active_execution_owner and caller != existing.active_execution_owner:
        return TaskTransitionDecision(
            accepted=False,
            case_name=EXECUTION_TERMINAL_CASE,
            rejection_reason="execution_owner_mismatch",
        )
    return TaskTransitionDecision(
        accepted=True,
        case_name=EXECUTION_TERMINAL_CASE,
    )


def plan_terminal_writeback(
    *,
    existing: TaskItem,
    event: TerminalWritebackEvent,
) -> TaskTransitionDecision | None:
    return plan_execution_scoped_terminal_writeback(
        existing=existing,
        caller=event.caller,
        requested_status=event.status,
        execution_id=event.execution_id,
        runtime_path=event.runtime_path,
    )


def plan_runtime_terminal_writeback(
    *,
    existing: TaskItem,
    caller: str,
    status: TaskStatus | None,
    execution_id: str | None,
) -> TaskTransitionDecision | None:
    return plan_execution_scoped_terminal_writeback(
        existing=existing,
        caller=caller,
        requested_status=status,
        execution_id=execution_id,
        runtime_path=True,
    )


def plan_reopen_task(
    *,
    existing: TaskItem,
    event: ReopenTaskEvent,
) -> TaskTransitionDecision:
    if existing.status not in (TaskStatus.completed, TaskStatus.failed, TaskStatus.blocked):
        return TaskTransitionDecision(
            accepted=False,
            case_name=REOPEN_TASK_CASE,
            rejection_reason="reopen_requires_terminal_or_blocked_task",
        )
    return TaskTransitionDecision(
        accepted=True,
        case_name=REOPEN_TASK_CASE,
    )


def plan_watchdog_failed_completion_recovery(
    *,
    existing: TaskItem,
    caller: str,
    requested_status: TaskStatus | None,
) -> TaskTransitionDecision | None:
    if requested_status != TaskStatus.completed:
        return None
    if existing.status != TaskStatus.failed:
        return None
    if existing.owner and caller != existing.owner:
        return TaskTransitionDecision(
            accepted=False,
            case_name=WATCHDOG_RECOVERY_CASE,
            rejection_reason="watchdog_recovery_requires_owner",
        )

    metadata = existing.metadata or {}
    if metadata.get("failure_root_cause") != WATCHDOG_FAILURE_ROOT_CAUSE:
        return None

    session_key = str(metadata.get("session_key") or "").strip()
    if session_key and not session_key.endswith(f"-{caller}"):
        return TaskTransitionDecision(
            accepted=False,
            case_name=WATCHDOG_RECOVERY_CASE,
            rejection_reason="watchdog_recovery_session_mismatch",
        )

    watchdog_at = _parse_iso_timestamp(metadata.get("watchdog_decision_at"))
    updated_at = _parse_iso_timestamp(existing.updated_at)
    if watchdog_at and updated_at and updated_at < watchdog_at:
        return TaskTransitionDecision(
            accepted=False,
            case_name=WATCHDOG_RECOVERY_CASE,
            rejection_reason="watchdog_recovery_stale_task_snapshot",
        )

    metadata_to_apply = {
        "recovered_from_watchdog_failure": True,
        "watchdog_recovered_at": datetime.now().astimezone().isoformat(),
        "watchdog_recovered_by": caller,
    }
    if metadata.get("watchdog_decision_at"):
        metadata_to_apply["watchdog_original_decision_at"] = metadata.get("watchdog_decision_at")

    return TaskTransitionDecision(
        accepted=True,
        case_name=WATCHDOG_RECOVERY_CASE,
        metadata_to_apply=metadata_to_apply,
        metadata_keys_to_remove=list(WATCHDOG_RECOVERY_FAILURE_KEYS),
    )


def plan_task_transition(
    *,
    existing: TaskItem,
    request: TaskTransitionRequest,
    all_tasks: list[TaskItem],
) -> TaskTransitionPlan:
    """Build the complete task-transition plan before mutating stores."""
    failure_metadata = build_failure_metadata(
        status=request.status,
        failure_kind=request.failure_kind,
        failure_note=request.failure_note,
        failure_root_cause=request.failure_root_cause,
        failure_evidence=request.failure_evidence,
        failure_recommended_next_owner=request.failure_recommended_next_owner,
        failure_recommended_action=request.failure_recommended_action,
    )
    metadata_to_apply = merge_transition_metadata(existing, failure_metadata, request.add_on_fail)
    followups = plan_task_transition_followups(
        existing=existing,
        status=request.status,
        all_tasks=all_tasks,
        failure_metadata=failure_metadata,
    )
    return TaskTransitionPlan(
        metadata_to_apply=metadata_to_apply,
        dependent_ids_to_wake=followups["dependent_ids_to_wake"],
        failed_targets_to_wake=followups["failed_targets_to_wake"],
    )