"""Task transition policy: validation, metadata planning, and follow-up planning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from clawteam.team.models import TaskItem, TaskStatus
from clawteam.workflow.topology import WorkflowTopology


COMPLEX_FAILURE_REQUIRED_FLAGS = {
    "--failure-root-cause": "failure_root_cause",
    "--failure-evidence": "failure_evidence",
    "--failure-recommended-next-owner": "failure_recommended_next_owner",
    "--failure-recommended-action": "failure_recommended_action",
}


class TaskTransitionValidationError(ValueError):
    """Raised when task transition options violate workflow policy."""


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
class TaskTransitionPlan:
    metadata_to_apply: dict[str, Any] | None
    dependent_ids_to_wake: list[str]
    failed_targets_to_wake: list[str]


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

    if status != TaskStatus.failed:
        if any((value or "").strip() for value in option_values.values()):
            raise TaskTransitionValidationError("failure options require --status failed")
        return None

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
