"""Task update application services: use-case orchestration and follow-up execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from clawteam.services.failure_service import handle_failed_task_notice
from clawteam.services.task_service import release_task_to_owner, wake_tasks_to_pending
from clawteam.task.transition import (
    TaskTransitionPlan,
    TaskTransitionRequest,
    TaskTransitionValidationError,
    build_failure_metadata,
    merge_transition_metadata,
    plan_task_transition,
    plan_task_transition_followups,
)
from clawteam.team.models import TaskItem, TaskStatus


TaskUpdateValidationError = TaskTransitionValidationError
TaskUpdatePlan = TaskTransitionPlan
merge_update_metadata = merge_transition_metadata
plan_task_update_followups = plan_task_transition_followups


def plan_task_update(
    *,
    existing: TaskItem,
    status: TaskStatus | None,
    all_tasks: list[TaskItem],
    failure_metadata: dict[str, str] | None,
    add_on_fail_list: list[str] | None,
) -> TaskUpdatePlan:
    """Backward-compatible wrapper around the task transition planner."""
    transition_request = TaskTransitionRequest(
        status=status,
        add_on_fail=add_on_fail_list,
        failure_kind=(failure_metadata or {}).get("failure_kind"),
        failure_note=(failure_metadata or {}).get("failure_note"),
        failure_root_cause=(failure_metadata or {}).get("failure_root_cause"),
        failure_evidence=(failure_metadata or {}).get("failure_evidence"),
        failure_recommended_next_owner=(failure_metadata or {}).get("failure_recommended_next_owner"),
        failure_recommended_action=(failure_metadata or {}).get("failure_recommended_action"),
    )
    return plan_task_transition(existing=existing, request=transition_request, all_tasks=all_tasks)


@dataclass(frozen=True)
class TaskUpdateEffects:
    wake: dict[str, Any] | None
    auto_releases: list[dict[str, Any]]
    failure_notice: dict[str, Any] | None


@dataclass(frozen=True)
class TaskUpdateRequest:
    status: TaskStatus | None
    owner: str | None
    subject: str | None
    description: str | None
    add_blocks: list[str] | None
    add_blocked_by: list[str] | None
    add_on_fail: list[str] | None
    failure_kind: str | None
    failure_note: str | None
    failure_root_cause: str | None
    failure_evidence: str | None
    failure_recommended_next_owner: str | None
    failure_recommended_action: str | None
    wake_owner: bool
    message: str
    force: bool


@dataclass(frozen=True)
class TaskUpdateResult:
    task: TaskItem
    plan: TaskUpdatePlan
    effects: TaskUpdateEffects


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


def execute_task_update(
    *,
    team: str,
    task_id: str,
    caller: str,
    request: TaskUpdateRequest,
    store: Any,
) -> TaskUpdateResult:
    """Run the full task-update use case behind the CLI adapter."""
    existing = store.get(task_id)
    if not existing:
        raise KeyError(task_id)

    transition_request = TaskTransitionRequest(
        status=request.status,
        add_on_fail=request.add_on_fail,
        failure_kind=request.failure_kind,
        failure_note=request.failure_note,
        failure_root_cause=request.failure_root_cause,
        failure_evidence=request.failure_evidence,
        failure_recommended_next_owner=request.failure_recommended_next_owner,
        failure_recommended_action=request.failure_recommended_action,
    )
    plan = plan_task_transition(
        existing=existing,
        request=transition_request,
        all_tasks=store.list_tasks(),
    )

    task = store.update(
        task_id,
        status=request.status,
        owner=request.owner,
        subject=request.subject,
        description=request.description,
        add_blocks=request.add_blocks,
        add_blocked_by=request.add_blocked_by,
        metadata=plan.metadata_to_apply,
        caller=caller,
        force=request.force,
    )

    effects = execute_task_update_effects(
        team=team,
        task=task,
        caller=caller,
        wake_owner=request.wake_owner,
        message=request.message,
        dependent_ids_to_wake=plan.dependent_ids_to_wake,
        failed_targets_to_wake=plan.failed_targets_to_wake,
    )

    return TaskUpdateResult(task=task, plan=plan, effects=effects)
