"""Task update application services: use-case orchestration and follow-up execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from clawteam.services.task_service import wake_tasks_to_pending
from clawteam.task.transition import (
    ReopenTaskEvent,
    TaskTransitionPlan,
    TaskTransitionRequest,
    TaskTransitionValidationError,
    TerminalWritebackEvent,
    build_failure_metadata,
    merge_transition_metadata,
    plan_reopen_task,
    plan_task_transition,
    plan_task_transition_followups,
    plan_terminal_writeback,
    plan_watchdog_failed_completion_recovery,
)
from clawteam.team.models import TaskItem, TaskStatus
from clawteam.team.tasks import TaskStore


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
    execution_id: str | None
    wake_owner: bool
    message: str
    force: bool


@dataclass(frozen=True)
class TaskUpdateResult:
    task: TaskItem
    plan: TaskUpdatePlan
    effects: TaskUpdateEffects
    transition_case: str | None = None


@dataclass(frozen=True)
class TaskUpdateContext:
    store: TaskStore
    team: str
    runtime: Any
    release_notifier: Callable[[str, TaskItem, str, str], dict[str, Any] | None]
    failure_notifier: Callable[[str, TaskItem, str], dict[str, Any] | None]
    repo: str | None = None

    @property
    def release_team(self) -> str:
        """Backward-compatible alias for older call sites."""
        return self.team

    @property
    def release_repo(self) -> str | None:
        """Backward-compatible alias for older call sites."""
        return self.repo


def execute_task_update_effects(
    *,
    ctx: TaskUpdateContext,
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
        wake = ctx.runtime.release_to_owner(
            task,
            caller=caller,
            message=message,
            respawn=True,
            release_notifier=ctx.release_notifier,
        )

    auto_releases: list[dict[str, Any]] = []
    if dependent_ids_to_wake:
        auto_releases.extend(
            wake_tasks_to_pending(
                ctx.release_team,
                dependent_ids_to_wake,
                caller=caller,
                message_builder=lambda target: (
                    f"Task {target.id} is unblocked because dependency {task.id} completed. "
                    "Start now and report only real blockers."
                ),
                repo=ctx.release_repo,
                store=ctx.store,
                runtime=ctx.runtime,
                release_notifier=ctx.release_notifier,
            )
        )
    if failed_targets_to_wake:
        auto_releases.extend(
            wake_tasks_to_pending(
                ctx.team,
                failed_targets_to_wake,
                caller=caller,
                message_builder=lambda target: (
                    f"Task {target.id} is reopened because task {task.id} failed and routed work back to you. "
                    "Start now and report only real blockers."
                ),
                repo=ctx.repo,
                store=ctx.store,
                runtime=ctx.runtime,
                release_notifier=ctx.release_notifier,
            )
        )

    failure_notice = None
    if task.status == TaskStatus.failed:
        failure_notice = ctx.failure_notifier(ctx.team, task, caller)

    return TaskUpdateEffects(
        wake=wake,
        auto_releases=auto_releases,
        failure_notice=failure_notice,
    )


def execute_task_update(
    *,
    task_id: str,
    caller: str,
    request: TaskUpdateRequest,
    ctx: TaskUpdateContext,
) -> TaskUpdateResult:
    """Run the full task-update use case behind the CLI adapter."""
    existing = ctx.store.get(task_id)
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
        all_tasks=ctx.store.list_tasks(),
    )

    transition_case: str | None = None
    metadata_keys_to_remove: list[str] | None = None
    execution_decision = plan_terminal_writeback(
        existing=existing,
        event=TerminalWritebackEvent(
            caller=caller,
            status=request.status,
            execution_id=request.execution_id,
        ) if request.status in (TaskStatus.completed, TaskStatus.failed) else None,
    ) if request.status in (TaskStatus.completed, TaskStatus.failed) else None
    if execution_decision and not execution_decision.accepted:
        ctx.store.record_transition_rejection(
            task_id,
            case_name=execution_decision.case_name,
            caller=caller,
            execution_id=request.execution_id,
            rejection_reason=execution_decision.rejection_reason,
        )
        raise RuntimeError(
            f"terminal writeback rejected: {execution_decision.rejection_reason}"
        )
    if execution_decision and execution_decision.accepted:
        transition_case = execution_decision.case_name

    recovery_decision = plan_watchdog_failed_completion_recovery(
        existing=existing,
        caller=caller,
        requested_status=request.status,
    )
    if recovery_decision and recovery_decision.accepted:
        transition_case = recovery_decision.case_name
        metadata_keys_to_remove = recovery_decision.metadata_keys_to_remove
        metadata = dict(plan.metadata_to_apply or {})
        metadata.update(recovery_decision.metadata_to_apply or {})
        plan = TaskUpdatePlan(
            metadata_to_apply=metadata,
            dependent_ids_to_wake=plan.dependent_ids_to_wake,
            failed_targets_to_wake=plan.failed_targets_to_wake,
        )

    if request.status in (TaskStatus.completed, TaskStatus.failed):
        decision = execution_decision or {
            "case_name": transition_case or "terminal_writeback_without_execution_scope",
            "accepted": True,
        }
        if hasattr(decision, "case_name"):
            decision = {
                "case_name": decision.case_name,
                "accepted": decision.accepted,
                "rejection_reason": decision.rejection_reason,
            }
        task = ctx.store.apply_transition_decision(
            task_id,
            decision=decision,
            status=request.status,
            caller=caller,
            execution_id=request.execution_id,
            metadata=plan.metadata_to_apply,
            metadata_keys_to_remove=metadata_keys_to_remove,
            force=request.force,
        )
    elif request.status == TaskStatus.pending and existing.status != TaskStatus.pending:
        reopen_decision = plan_reopen_task(existing=existing, event=ReopenTaskEvent(caller=caller))
        if not reopen_decision.accepted:
            ctx.store.record_transition_rejection(
                task_id,
                case_name=reopen_decision.case_name,
                caller=caller,
                rejection_reason=reopen_decision.rejection_reason,
            )
            raise RuntimeError(f"reopen rejected: {reopen_decision.rejection_reason}")
        task = ctx.store.apply_transition_decision(
            task_id,
            decision={"case_name": reopen_decision.case_name, "accepted": True},
            status=TaskStatus.pending,
            caller=caller,
            force=request.force,
        )
        if any(
            value is not None
            for value in (
                request.owner,
                request.subject,
                request.description,
                request.add_blocks,
                request.add_blocked_by,
                plan.metadata_to_apply,
            )
        ):
            task = ctx.store.update(
                task_id,
                owner=request.owner,
                subject=request.subject,
                description=request.description,
                add_blocks=request.add_blocks,
                add_blocked_by=request.add_blocked_by,
                metadata=plan.metadata_to_apply,
                metadata_keys_to_remove=metadata_keys_to_remove,
                caller=caller,
                force=request.force,
            )
    else:
        task = ctx.store.update(
            task_id,
            status=request.status,
            owner=request.owner,
            subject=request.subject,
            description=request.description,
            add_blocks=request.add_blocks,
            add_blocked_by=request.add_blocked_by,
            metadata=plan.metadata_to_apply,
            metadata_keys_to_remove=metadata_keys_to_remove,
            execution_id=request.execution_id,
            caller=caller,
            force=request.force,
        )

    effects = execute_task_update_effects(
        ctx=ctx,
        task=task,
        caller=caller,
        wake_owner=request.wake_owner,
        message=request.message,
        dependent_ids_to_wake=plan.dependent_ids_to_wake,
        failed_targets_to_wake=plan.failed_targets_to_wake,
    )

    return TaskUpdateResult(task=task, plan=plan, effects=effects, transition_case=transition_case)
