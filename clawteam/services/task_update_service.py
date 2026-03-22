"""Task update application services: validation, planning, and follow-up execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from clawteam.services.failure_service import handle_failed_task_notice
from clawteam.services.task_service import release_task_to_owner, wake_tasks_to_pending
from clawteam.team.models import TaskItem, TaskStatus


COMPLEX_FAILURE_REQUIRED_FLAGS = {
    "--failure-root-cause": "failure_root_cause",
    "--failure-evidence": "failure_evidence",
    "--failure-recommended-next-owner": "failure_recommended_next_owner",
    "--failure-recommended-action": "failure_recommended_action",
}


class TaskUpdateValidationError(ValueError):
    """Raised when task update options violate workflow policy."""


@dataclass(frozen=True)
class TaskUpdatePlan:
    metadata_to_apply: dict[str, Any] | None
    dependent_ids_to_wake: list[str]
    failed_targets_to_wake: list[str]


@dataclass(frozen=True)
class TaskUpdateEffects:
    wake: dict[str, Any] | None
    auto_releases: list[dict[str, Any]]
    failure_notice: dict[str, Any] | None


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
            raise TaskUpdateValidationError("failure options require --status failed")
        return None

    kind = (failure_kind or "complex").strip().lower()
    if kind not in ("regular", "complex"):
        raise TaskUpdateValidationError("--failure-kind must be regular or complex")

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
            raise TaskUpdateValidationError(f"complex fail requires: {', '.join(missing)}")

    return failure_metadata


def merge_update_metadata(
    existing: TaskItem,
    failure_metadata: dict[str, str] | None,
    add_on_fail_list: list[str] | None,
) -> dict[str, Any] | None:
    """Merge task-update metadata patches without duplicating on_fail targets."""
    merged_metadata: dict[str, Any] = dict(failure_metadata or {})
    if add_on_fail_list:
        current_on_fail = list(existing.metadata.get("on_fail", []))
        for target in add_on_fail_list:
            if target not in current_on_fail:
                current_on_fail.append(target)
        merged_metadata["on_fail"] = current_on_fail
    return merged_metadata or None


def plan_task_update_followups(
    *,
    existing: TaskItem,
    status: TaskStatus | None,
    all_tasks: list[TaskItem],
    failure_metadata: dict[str, str] | None,
) -> dict[str, list[str]]:
    """Plan transition follow-ups implied by a task status update."""
    dependent_ids_to_wake: list[str] = []
    failed_targets_to_wake: list[str] = []

    if status == TaskStatus.completed:
        dependent_ids_to_wake = [
            candidate.id
            for candidate in all_tasks
            if existing.id in candidate.blocked_by and candidate.status == TaskStatus.blocked
        ]
    elif status == TaskStatus.failed and failure_metadata:
        if failure_metadata.get("failure_kind") == "regular" and existing.started_at:
            failed_targets_to_wake = list(existing.metadata.get("on_fail", []))

    return {
        "dependent_ids_to_wake": dependent_ids_to_wake,
        "failed_targets_to_wake": failed_targets_to_wake,
    }


def plan_task_update(
    *,
    existing: TaskItem,
    status: TaskStatus | None,
    all_tasks: list[TaskItem],
    failure_metadata: dict[str, str] | None,
    add_on_fail_list: list[str] | None,
) -> TaskUpdatePlan:
    """Build the complete task-update plan before mutating stores."""
    metadata_to_apply = merge_update_metadata(existing, failure_metadata, add_on_fail_list)
    followups = plan_task_update_followups(
        existing=existing,
        status=status,
        all_tasks=all_tasks,
        failure_metadata=failure_metadata,
    )
    return TaskUpdatePlan(
        metadata_to_apply=metadata_to_apply,
        dependent_ids_to_wake=followups["dependent_ids_to_wake"],
        failed_targets_to_wake=followups["failed_targets_to_wake"],
    )


def execute_task_update_effects(
    *,
    team: str,
    task: TaskItem,
    caller: str,
    wake_owner: bool,
    message: str,
    dependent_ids_to_wake: list[str],
    failed_targets_to_wake: list[str],
) -> TaskUpdateEffects:
    """Execute post-update side effects after the task store mutation succeeds."""
    wake = None
    if wake_owner and task.status == TaskStatus.pending and task.owner:
        wake = release_task_to_owner(team, task, caller=caller, message=message, respawn=True)

    auto_releases: list[dict[str, Any]] = []
    if dependent_ids_to_wake:
        auto_releases.extend(
            wake_tasks_to_pending(
                team,
                dependent_ids_to_wake,
                caller=caller,
                message_builder=lambda target: (
                    f"Task {target.id} is unblocked because dependency {task.id} completed. "
                    "Start now and report only real blockers."
                ),
            )
        )
    if failed_targets_to_wake:
        auto_releases.extend(
            wake_tasks_to_pending(
                team,
                failed_targets_to_wake,
                caller=caller,
                message_builder=lambda target: (
                    f"Task {target.id} is reopened because task {task.id} failed and routed work back to you. "
                    "Start now and report only real blockers."
                ),
            )
        )

    failure_notice = None
    if task.status == TaskStatus.failed:
        failure_notice = handle_failed_task_notice(team, task, caller)

    return TaskUpdateEffects(
        wake=wake,
        auto_releases=auto_releases,
        failure_notice=failure_notice,
    )
