"""Task update application services: use-case orchestration and follow-up execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from clawteam.services.task_service import wake_tasks_to_pending
from clawteam.templates import (
    ScopeTaskValidationError,
    find_scope_audit_warnings,
    inject_resolved_scope_context,
    validate_scope_task_completion,
)
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
from clawteam.team.tasks import TaskPatch, TaskStore, TransitionApplyResult


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
    apply_result: TransitionApplyResult | None = None

    def __post_init__(self) -> None:
        if self.transition_case is None and self.apply_result is not None:
            object.__setattr__(self, "transition_case", self.apply_result.case_name)


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


def _scope_payload(task: TaskItem) -> dict[str, Any] | None:
    payload = task.metadata.get("resolved_scope")
    return payload if isinstance(payload, dict) else None


def _propagate_resolved_scope_to_targets(
    *,
    store: TaskStore,
    target_ids: list[str],
    scope_payload: dict[str, Any],
    scope_warnings: list[dict[str, Any]] | None = None,
) -> None:
    for target_id in target_ids:
        target = store.get(target_id)
        if target is None:
            continue
        patched_metadata = dict(getattr(target, "metadata", {}) or {})
        patched_metadata["resolved_scope"] = scope_payload
        if scope_warnings is not None:
            patched_metadata["scope_audit_warnings"] = scope_warnings
        patched_description = inject_resolved_scope_context(
            description=getattr(target, "description", "") or "",
            normalized=scope_payload,
            scope_audit_warnings=scope_warnings,
        )
        store.update(
            target_id,
            description=patched_description,
            metadata=patched_metadata,
        )


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
    scope_payload = _scope_payload(task)
    scope_warnings = task.metadata.get("scope_audit_warnings") if isinstance(task.metadata, dict) else None
    if scope_payload and dependent_ids_to_wake:
        _propagate_resolved_scope_to_targets(
            store=ctx.store,
            target_ids=dependent_ids_to_wake,
            scope_payload=scope_payload,
            scope_warnings=scope_warnings if isinstance(scope_warnings, list) else None,
        )

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


def _build_generic_task_patch(
    *,
    request: TaskUpdateRequest,
    metadata_to_apply: dict[str, Any] | None,
    metadata_keys_to_remove: list[str] | None,
) -> TaskPatch:
    return TaskPatch(
        owner=request.owner,
        subject=request.subject,
        description=request.description,
        add_blocks=request.add_blocks,
        add_blocked_by=request.add_blocked_by,
        metadata=metadata_to_apply,
        metadata_keys_to_remove=metadata_keys_to_remove,
    )


def _decision_to_payload(decision: Any, default_case_name: str) -> dict[str, Any]:
    if hasattr(decision, "case_name"):
        return {
            "case_name": decision.case_name,
            "accepted": decision.accepted,
            "rejection_reason": decision.rejection_reason,
        }
    if isinstance(decision, dict):
        return {
            "case_name": decision.get("case_name", default_case_name),
            "accepted": decision.get("accepted", True),
            "rejection_reason": decision.get("rejection_reason"),
        }
    return {
        "case_name": default_case_name,
        "accepted": True,
        "rejection_reason": None,
    }


def _terminal_decision_for_apply(
    *,
    execution_decision: Any,
    recovery_decision: Any,
) -> dict[str, Any]:
    if recovery_decision is not None and getattr(recovery_decision, "accepted", False):
        return _decision_to_payload(
            recovery_decision,
            default_case_name="recover_watchdog_failed_completion",
        )
    if execution_decision is not None:
        return _decision_to_payload(
            execution_decision,
            default_case_name="terminal_writeback_without_execution_scope",
        )
    return {
        "case_name": "terminal_writeback_without_execution_scope",
        "accepted": True,
        "rejection_reason": None,
    }


def _apply_terminal_transition(
    *,
    ctx: TaskUpdateContext,
    task_id: str,
    caller: str,
    status: TaskStatus,
    execution_id: str | None,
    decision: Any,
    metadata_to_apply: dict[str, Any] | None,
    metadata_keys_to_remove: list[str] | None,
    force: bool,
) -> TransitionApplyResult | None:
    return ctx.store.apply_transition_decision(
        task_id,
        decision=_decision_to_payload(
            decision,
            default_case_name="terminal_writeback_without_execution_scope",
        ),
        status=status,
        caller=caller,
        execution_id=execution_id,
        metadata=metadata_to_apply,
        metadata_keys_to_remove=metadata_keys_to_remove,
        force=force,
    )


def _apply_reopen_transition(
    *,
    ctx: TaskUpdateContext,
    task_id: str,
    caller: str,
    force: bool,
    decision: Any,
) -> TransitionApplyResult | None:
    return ctx.store.apply_transition_decision(
        task_id,
        decision=_decision_to_payload(decision, default_case_name="reopen_task"),
        status=TaskStatus.pending,
        caller=caller,
        force=force,
    )


def _apply_generic_patch(
    *,
    ctx: TaskUpdateContext,
    task_id: str,
    caller: str,
    force: bool,
    patch: TaskPatch,
) -> TaskItem | None:
    return ctx.store.apply_patch(
        task_id,
        patch=patch,
        caller=caller,
        force=force,
    )


def _apply_generic_status_update(
    *,
    ctx: TaskUpdateContext,
    task_id: str,
    caller: str,
    request: TaskUpdateRequest,
    metadata_to_apply: dict[str, Any] | None,
    metadata_keys_to_remove: list[str] | None,
) -> TaskItem | None:
    return ctx.store.update(
        task_id,
        status=request.status,
        owner=request.owner,
        subject=request.subject,
        description=request.description,
        add_blocks=request.add_blocks,
        add_blocked_by=request.add_blocked_by,
        metadata=metadata_to_apply,
        metadata_keys_to_remove=metadata_keys_to_remove,
        execution_id=request.execution_id,
        caller=caller,
        force=request.force,
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

    metadata_keys_to_remove: list[str] | None = None
    apply_result: TransitionApplyResult | None = None

    existing_launch_brief = existing.metadata.get("launch_brief") if isinstance(existing.metadata, dict) else None
    is_scope_task = (existing.metadata.get("template_stage") == "scope") if isinstance(existing.metadata, dict) else False
    if request.status == TaskStatus.completed and is_scope_task:
        if not (request.description or "").strip():
            raise TaskTransitionValidationError(
                "scope task completion must include the final structured brief via --description before downstream release"
            )
        source_request = ""
        if isinstance(existing_launch_brief, dict):
            sections = existing_launch_brief.get("sections")
            if isinstance(sections, dict):
                source_request = str(sections.get("source_request") or "")
        try:
            validated_scope = validate_scope_task_completion(
                source_request=source_request,
                leader_brief=request.description or "",
            )
        except ScopeTaskValidationError as e:
            raise TaskTransitionValidationError(str(e)) from e
        scope_warnings = find_scope_audit_warnings(
            source_request=source_request,
            normalized=validated_scope,
        )
        metadata = dict(plan.metadata_to_apply or {})
        metadata["launch_brief"] = validated_scope.model_dump(mode="json")
        metadata["resolved_scope"] = validated_scope.model_dump(mode="json")
        metadata["scope_audit_warnings"] = [warning.model_dump(mode="json") for warning in scope_warnings]
        plan = TaskUpdatePlan(
            metadata_to_apply=metadata,
            dependent_ids_to_wake=plan.dependent_ids_to_wake,
            failed_targets_to_wake=plan.failed_targets_to_wake,
        )

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
    recovery_decision = plan_watchdog_failed_completion_recovery(
        existing=existing,
        caller=caller,
        requested_status=request.status,
    )
    if recovery_decision and recovery_decision.accepted:
        metadata_keys_to_remove = recovery_decision.metadata_keys_to_remove
        metadata = dict(plan.metadata_to_apply or {})
        metadata.update(recovery_decision.metadata_to_apply or {})
        plan = TaskUpdatePlan(
            metadata_to_apply=metadata,
            dependent_ids_to_wake=plan.dependent_ids_to_wake,
            failed_targets_to_wake=plan.failed_targets_to_wake,
        )

    generic_patch = _build_generic_task_patch(
        request=request,
        metadata_to_apply=plan.metadata_to_apply,
        metadata_keys_to_remove=metadata_keys_to_remove,
    )

    if request.status in (TaskStatus.completed, TaskStatus.failed):
        apply_result = _apply_terminal_transition(
            ctx=ctx,
            task_id=task_id,
            caller=caller,
            status=request.status,
            execution_id=request.execution_id,
            decision=_terminal_decision_for_apply(
                execution_decision=execution_decision,
                recovery_decision=recovery_decision,
            ),
            metadata_to_apply=plan.metadata_to_apply,
            metadata_keys_to_remove=metadata_keys_to_remove,
            force=request.force,
        )
        task = apply_result.task if apply_result is not None else None
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
        apply_result = _apply_reopen_transition(
            ctx=ctx,
            task_id=task_id,
            caller=caller,
            force=request.force,
            decision=reopen_decision,
        )
        task = apply_result.task if apply_result is not None else None
        if not generic_patch.is_empty():
            task = _apply_generic_patch(
                ctx=ctx,
                task_id=task_id,
                patch=generic_patch,
                caller=caller,
                force=request.force,
            )
    elif request.status is None:
        task = _apply_generic_patch(
            ctx=ctx,
            task_id=task_id,
            patch=generic_patch,
            caller=caller,
            force=request.force,
        )
    else:
        task = _apply_generic_status_update(
            ctx=ctx,
            task_id=task_id,
            caller=caller,
            request=request,
            metadata_to_apply=plan.metadata_to_apply,
            metadata_keys_to_remove=metadata_keys_to_remove,
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

    return TaskUpdateResult(task=task, plan=plan, effects=effects, apply_result=apply_result)
