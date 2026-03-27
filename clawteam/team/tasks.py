"""Task store for shared team task management."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from clawteam.task.transition import TaskTransitionDecision, plan_runtime_terminal_writeback
from clawteam.team.models import TaskItem, TaskStatus, get_data_dir


UNFINISHED_TASK_STATUSES = {
    TaskStatus.pending,
    TaskStatus.in_progress,
    TaskStatus.blocked,
}


class TaskLockError(Exception):
    """Raised when a task is locked by another agent."""


class TaskExecutionError(RuntimeError):
    """Raised when an execution-scoped writeback does not match the active execution."""




@dataclass(frozen=True)
class TransitionApplyResult:
    """Result of applying a transition decision in the task store."""

    task: TaskItem
    accepted: bool
    case_name: str
    rejection_reason: str | None = None
    execution_id: str | None = None
    audit_recorded: bool = True


@dataclass(frozen=True)
class TaskPatch:
    """Non-transition task field updates applied after policy decisions."""

    owner: str | None = None
    subject: str | None = None
    description: str | None = None
    add_blocks: list[str] | None = None
    add_blocked_by: list[str] | None = None
    metadata: dict[str, Any] | None = None
    metadata_keys_to_remove: list[str] | None = None

    def is_empty(self) -> bool:
        return not any(
            value is not None
            for value in (
                self.owner,
                self.subject,
                self.description,
                self.add_blocks,
                self.add_blocked_by,
                self.metadata,
                self.metadata_keys_to_remove,
            )
        )


def _tasks_root(team_name: str) -> Path:
    d = get_data_dir() / "tasks" / team_name
    d.mkdir(parents=True, exist_ok=True)
    return d


def _task_path(team_name: str, task_id: str) -> Path:
    return _tasks_root(team_name) / f"task-{task_id}.json"


def _tasks_lock_path(team_name: str) -> Path:
    return _tasks_root(team_name) / ".tasks.lock"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _next_execution_id(task: TaskItem) -> tuple[int, str]:
    next_seq = max(int(task.execution_seq or 0), 0) + 1
    return next_seq, f"{task.id}-exec-{next_seq}"


def _append_transition_log(
    task: TaskItem,
    *,
    case_name: str,
    accepted: bool,
    caller: str,
    execution_id: str | None = None,
    rejection_reason: str | None = None,
) -> None:
    entries = list(task.metadata.get("transition_log", []))
    entries.append(
        {
            "at": _now_iso(),
            "case": case_name,
            "accepted": accepted,
            "caller": caller,
            "executionId": execution_id or "",
            "rejectionReason": rejection_reason or "",
        }
    )
    task.metadata["transition_log"] = entries[-20:]


class TaskStore:
    """File-based task store with dependency tracking.

    Each task is stored as a separate JSON file:
    ``{data_dir}/tasks/{team}/task-{id}.json``
    """

    def __init__(self, team_name: str):
        self.team_name = team_name

    @contextmanager
    def _write_lock(self):
        lock_path = _tasks_lock_path(self.team_name)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def create(
        self,
        subject: str,
        description: str = "",
        owner: str = "",
        blocks: list[str] | None = None,
        blocked_by: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> TaskItem:
        task = TaskItem(
            subject=subject,
            description=description,
            owner=owner,
            blocks=blocks or [],
            blocked_by=blocked_by or [],
            metadata=metadata or {},
        )
        if task.blocked_by:
            task.status = TaskStatus.blocked
        with self._write_lock():
            self._save_unlocked(task)
        return task

    def get(self, task_id: str) -> TaskItem | None:
        return self._get_unlocked(task_id)

    def _get_unlocked(self, task_id: str) -> TaskItem | None:
        path = _task_path(self.team_name, task_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return TaskItem.model_validate(data)
        except Exception:
            return None

    def apply_transition_decision(
        self,
        task_id: str,
        *,
        decision: dict[str, Any],
        caller: str,
        status: TaskStatus | None = None,
        force: bool = False,
        execution_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        metadata_keys_to_remove: list[str] | None = None,
        owner: str | None = None,
        subject: str | None = None,
        description: str | None = None,
        add_blocks: list[str] | None = None,
        add_blocked_by: list[str] | None = None,
    ) -> TransitionApplyResult | None:
        case_name = str(decision.get("case_name") or "unknown_transition")
        accepted = bool(decision.get("accepted", True))
        rejection_reason = decision.get("rejection_reason")
        audit = {
            "case_name": case_name,
            "accepted": accepted,
            "caller": caller,
            "execution_id": execution_id,
            "rejection_reason": rejection_reason,
        }
        task = self.update(
            task_id,
            status=status,
            owner=owner,
            subject=subject,
            description=description,
            add_blocks=add_blocks,
            add_blocked_by=add_blocked_by,
            metadata=metadata,
            metadata_keys_to_remove=metadata_keys_to_remove,
            execution_id=execution_id,
            caller=caller,
            force=force,
            transition_audit=audit,
        )
        if task is None:
            return None
        return TransitionApplyResult(
            task=task,
            accepted=accepted,
            case_name=case_name,
            rejection_reason=rejection_reason,
            execution_id=execution_id,
            audit_recorded=True,
        )

    def claim_execution(self, task_id: str, *, caller: str, force: bool = False) -> TransitionApplyResult | None:
        from clawteam.task.transition import ClaimExecutionEvent, plan_claim_execution

        with self._write_lock():
            task = self._get_unlocked(task_id)
            if task is None:
                return None

            decision = plan_claim_execution(
                existing=task,
                event=ClaimExecutionEvent(caller=caller, force=force),
            )
            if not decision.accepted:
                _append_transition_log(
                    task,
                    case_name=decision.case_name,
                    accepted=False,
                    caller=caller,
                    rejection_reason=decision.rejection_reason,
                )
                task.updated_at = _now_iso()
                self._save_unlocked(task)
                return TransitionApplyResult(
                    task=task,
                    accepted=False,
                    case_name=decision.case_name,
                    rejection_reason=decision.rejection_reason,
                    audit_recorded=True,
                )

            previous_status = task.status
            previous_owner = task.locked_by
            self._acquire_lock(task, caller, force)
            if not task.started_at:
                task.started_at = _now_iso()
            if previous_status != TaskStatus.in_progress or not task.active_execution_id or previous_owner != task.locked_by:
                next_seq, next_execution_id = _next_execution_id(task)
                task.execution_seq = next_seq
                task.active_execution_id = next_execution_id
                task.active_execution_owner = task.locked_by or caller or task.owner
            task.status = TaskStatus.in_progress
            _append_transition_log(
                task,
                case_name=decision.case_name,
                accepted=True,
                caller=caller,
                execution_id=task.active_execution_id,
            )
            task.updated_at = _now_iso()
            self._save_unlocked(task)
            return TransitionApplyResult(
                task=task,
                accepted=True,
                case_name=decision.case_name,
                execution_id=task.active_execution_id,
                audit_recorded=True,
            )

    def record_transition_rejection(
        self,
        task_id: str,
        *,
        case_name: str,
        caller: str,
        execution_id: str | None = None,
        rejection_reason: str | None = None,
    ) -> TransitionApplyResult | None:
        return self.apply_transition_decision(
            task_id,
            decision={
                "case_name": case_name,
                "accepted": False,
                "rejection_reason": rejection_reason,
            },
            caller=caller,
            execution_id=execution_id,
        )

    def accept_terminal_writeback(
        self,
        task_id: str,
        *,
        status: TaskStatus,
        caller: str,
        execution_id: str | None,
        metadata: dict[str, Any] | None = None,
        metadata_keys_to_remove: list[str] | None = None,
        force: bool = False,
        case_name: str = "execution_scoped_terminal_writeback",
    ) -> TransitionApplyResult | None:
        return self.apply_transition_decision(
            task_id,
            decision={"case_name": case_name, "accepted": True},
            status=status,
            caller=caller,
            execution_id=execution_id,
            metadata=metadata,
            metadata_keys_to_remove=metadata_keys_to_remove,
            force=force,
        )

    def apply_runtime_terminal_writeback(
        self,
        task_id: str,
        *,
        status: TaskStatus,
        caller: str,
        execution_id: str | None,
        metadata: dict[str, Any] | None = None,
        metadata_keys_to_remove: list[str] | None = None,
        force: bool = False,
        fallback_case_name: str = "worker_runtime_failed_closed",
    ) -> tuple[TaskTransitionDecision | None, TaskItem | None, TransitionApplyResult | None]:
        existing = self.get(task_id)
        task = None
        apply_result = None
        if existing is None:
            return None, task, apply_result

        decision = plan_runtime_terminal_writeback(
            existing=existing,
            caller=caller,
            status=status,
            execution_id=execution_id,
        )
        if decision and not decision.accepted:
            rejection = self.record_transition_rejection(
                task_id,
                case_name=decision.case_name,
                caller=caller,
                execution_id=execution_id,
                rejection_reason=decision.rejection_reason,
            )
            task = rejection.task if rejection is not None else self.get(task_id)
            return decision, task, apply_result

        applied_case = fallback_case_name
        if decision and decision.accepted:
            applied_case = decision.case_name
        apply_result = self.accept_terminal_writeback(
            task_id,
            status=status,
            caller=caller,
            execution_id=execution_id,
            metadata=metadata,
            metadata_keys_to_remove=metadata_keys_to_remove,
            force=force,
            case_name=applied_case,
        )
        return decision, task, apply_result

    def reopen_task(self, task_id: str, *, caller: str, force: bool = False) -> TransitionApplyResult | None:
        return self.apply_transition_decision(
            task_id,
            decision={"case_name": "reopen_task", "accepted": True},
            status=TaskStatus.pending,
            caller=caller,
            force=force,
        )

    def apply_patch(
        self,
        task_id: str,
        *,
        patch: TaskPatch,
        caller: str = "",
        force: bool = False,
    ) -> TaskItem | None:
        return self.update(
            task_id,
            owner=patch.owner,
            subject=patch.subject,
            description=patch.description,
            add_blocks=patch.add_blocks,
            add_blocked_by=patch.add_blocked_by,
            metadata=patch.metadata,
            metadata_keys_to_remove=patch.metadata_keys_to_remove,
            caller=caller,
            force=force,
        )

    def update(
        self,
        task_id: str,
        status: TaskStatus | None = None,
        owner: str | None = None,
        subject: str | None = None,
        description: str | None = None,
        add_blocks: list[str] | None = None,
        add_blocked_by: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        metadata_keys_to_remove: list[str] | None = None,
        execution_id: str | None = None,
        caller: str = "",
        force: bool = False,
        transition_audit: dict[str, Any] | None = None,
    ) -> TaskItem | None:
        with self._write_lock():
            task = self._get_unlocked(task_id)
            if not task:
                return None

            if status in (TaskStatus.completed, TaskStatus.failed) and execution_id:
                if not task.active_execution_id:
                    if task.last_terminal_execution_id and execution_id == task.last_terminal_execution_id:
                        duplicate_reason = (
                            "duplicate_terminal_same_status"
                            if task.last_terminal_status == status.value
                            else "duplicate_terminal_conflicting_status"
                        )
                        raise TaskExecutionError(
                            f"Task '{task.id}' already recorded terminal status '{task.last_terminal_status}' for execution '{execution_id}' ({duplicate_reason})."
                        )
                    raise TaskExecutionError(
                        f"Task '{task.id}' has no active execution; got terminal writeback for '{execution_id}'."
                    )
                if execution_id != task.active_execution_id:
                    raise TaskExecutionError(
                        f"Task '{task.id}' active execution is '{task.active_execution_id}', not '{execution_id}'."
                    )
                if task.active_execution_owner and caller and caller != task.active_execution_owner:
                    raise TaskExecutionError(
                        f"Task '{task.id}' active execution owner is '{task.active_execution_owner}', not '{caller}'."
                    )

            # Lock logic when transitioning to in_progress
            if status == TaskStatus.in_progress:
                previous_status = task.status
                previous_owner = task.locked_by
                self._acquire_lock(task, caller, force)
                # Record when work actually started
                if not task.started_at:
                    task.started_at = _now_iso()
                if previous_status != TaskStatus.in_progress or not task.active_execution_id or previous_owner != task.locked_by:
                    next_seq, execution_id = _next_execution_id(task)
                    task.execution_seq = next_seq
                    task.active_execution_id = execution_id
                    task.active_execution_owner = task.locked_by or caller or task.owner

            # Clear lock when transitioning to completed, pending, or failed
            if status in (TaskStatus.completed, TaskStatus.pending, TaskStatus.failed):
                task.locked_by = ""
                task.locked_at = ""
                if status in (TaskStatus.completed, TaskStatus.failed) and task.active_execution_id:
                    task.last_terminal_execution_id = task.active_execution_id
                    task.last_terminal_status = status.value
                task.active_execution_id = ""
                task.active_execution_owner = ""

            # Compute duration when completing a task that has a start time
            if status == TaskStatus.completed and task.started_at:
                try:
                    start = datetime.fromisoformat(task.started_at)
                    duration_secs = (datetime.now(timezone.utc) - start).total_seconds()
                    task.metadata["duration_seconds"] = round(duration_secs, 2)
                except (ValueError, TypeError):
                    pass  # malformed timestamp, skip

            if status is not None:
                task.status = status
            if owner is not None:
                task.owner = owner
            if subject is not None:
                task.subject = subject
            if description is not None:
                task.description = description
            if add_blocks:
                for b in add_blocks:
                    if b not in task.blocks:
                        task.blocks.append(b)
            if add_blocked_by:
                for b in add_blocked_by:
                    if b not in task.blocked_by:
                        task.blocked_by.append(b)
            if metadata_keys_to_remove:
                for key in metadata_keys_to_remove:
                    task.metadata.pop(key, None)
            if metadata:
                task.metadata.update(metadata)
            if transition_audit:
                _append_transition_log(
                    task,
                    case_name=str(transition_audit.get("case_name") or "unknown_transition"),
                    accepted=bool(transition_audit.get("accepted", True)),
                    caller=str(transition_audit.get("caller") or caller),
                    execution_id=transition_audit.get("execution_id"),
                    rejection_reason=transition_audit.get("rejection_reason"),
                )
            task.updated_at = _now_iso()

            if task.status == TaskStatus.completed and self._should_resolve_dependents_on_completion(task):
                self._resolve_dependents_unlocked(task_id)
            elif task.status == TaskStatus.failed:
                self._apply_failure_flow_unlocked(task)

            self._save_unlocked(task)
            return task

    def _acquire_lock(self, task: TaskItem, caller: str, force: bool) -> None:
        """Acquire lock on a task for the caller agent."""
        if task.locked_by and task.locked_by != caller and not force:
            # Check if lock holder is still alive via spawn registry
            from clawteam.spawn.registry import is_agent_alive
            alive = is_agent_alive(self.team_name, task.locked_by)
            if alive is not False:
                # Lock holder is alive or unknown — refuse
                raise TaskLockError(
                    f"Task '{task.id}' is locked by '{task.locked_by}' "
                    f"(since {task.locked_at}). Use --force to override."
                )
            # Lock holder is dead — release and continue

        task.locked_by = caller or ""
        task.locked_at = _now_iso() if caller else ""

    def release_stale_locks(self) -> list[str]:
        """Scan all tasks and release locks held by dead agents.

        Returns list of task IDs whose locks were released.
        """
        from clawteam.spawn.registry import is_agent_alive

        released = []
        with self._write_lock():
            for task in self._list_tasks_unlocked():
                if not task.locked_by:
                    continue
                alive = is_agent_alive(self.team_name, task.locked_by)
                if alive is False:
                    task.locked_by = ""
                    task.locked_at = ""
                    task.updated_at = _now_iso()
                    self._save_unlocked(task)
                    released.append(task.id)
        return released

    def list_tasks(
        self, status: TaskStatus | None = None, owner: str | None = None
    ) -> list[TaskItem]:
        return self._list_tasks_unlocked(status=status, owner=owner)

    def _list_tasks_unlocked(
        self, status: TaskStatus | None = None, owner: str | None = None
    ) -> list[TaskItem]:
        root = _tasks_root(self.team_name)
        tasks = []
        for f in sorted(root.glob("task-*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                task = TaskItem.model_validate(data)
                if status and task.status != status:
                    continue
                if owner and task.owner != owner:
                    continue
                tasks.append(task)
            except Exception:
                continue
        return tasks

    def clear_unfinished_tasks_for_owner(self, owner: str) -> list[TaskItem]:
        """Delete started unfinished tasks owned by ``owner`` and started unfinished dependents.

        This is used when a worker runtime has been replaced and its old task
        world must not leak into the new runtime. We clear only tasks that had
        actually started execution; never-started pending/blocked tasks should
        remain in the board so the leader/runtime can re-wake them safely.
        """
        if not owner:
            return []

        def _started(task: TaskItem) -> bool:
            return bool(
                task.started_at
                or task.execution_seq
                or task.active_execution_id
                or task.active_execution_owner
                or task.last_terminal_execution_id
                or task.locked_by
                or task.status == TaskStatus.in_progress
            )

        with self._write_lock():
            tasks = self._list_tasks_unlocked()
            unfinished = {
                task.id: task
                for task in tasks
                if task.status in UNFINISHED_TASK_STATUSES
            }
            doomed = {
                task.id
                for task in unfinished.values()
                if task.owner == owner and _started(task)
            }
            if not doomed:
                return []

            changed = True
            while changed:
                changed = False
                for task in unfinished.values():
                    if task.id in doomed:
                        continue
                    if any(dep in doomed for dep in task.blocked_by) and _started(task):
                        doomed.add(task.id)
                        changed = True

            cleared: list[TaskItem] = []
            for task in tasks:
                if task.id not in doomed:
                    continue
                _task_path(self.team_name, task.id).unlink(missing_ok=True)
                cleared.append(task)
            return cleared

    def get_stats(self) -> dict[str, Any]:
        """Aggregate task timing stats for this team.

        Returns dict with total tasks, completed count, and avg duration
        (only counting tasks that have duration_seconds in metadata).
        """
        tasks = self.list_tasks()
        completed = [t for t in tasks if t.status == TaskStatus.completed]
        durations = [
            t.metadata["duration_seconds"]
            for t in completed
            if "duration_seconds" in t.metadata
        ]
        avg_duration = sum(durations) / len(durations) if durations else 0.0
        return {
            "total": len(tasks),
            "completed": len(completed),
            "in_progress": sum(1 for t in tasks if t.status == TaskStatus.in_progress),
            "pending": sum(1 for t in tasks if t.status == TaskStatus.pending),
            "blocked": sum(1 for t in tasks if t.status == TaskStatus.blocked),
            "timed_completed": len(durations),
            "avg_duration_seconds": round(avg_duration, 2),
        }

    def _save_unlocked(self, task: TaskItem) -> None:
        path = _task_path(self.team_name, task.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            dir=path.parent,
            prefix=f"{path.stem}-",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
                tmp_file.write(task.model_dump_json(indent=2, by_alias=True))
            Path(tmp_name).replace(path)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise

    @staticmethod
    def _should_resolve_dependents_on_completion(task: TaskItem) -> bool:
        metadata = task.metadata if isinstance(task.metadata, dict) else {}
        if str(metadata.get("template_stage") or "").strip().lower() != "scope":
            return True
        return str(metadata.get("materialization_mode") or "immediate").strip().lower() != "post-scope"

    def _resolve_dependents_unlocked(self, completed_task_id: str) -> None:
        root = _tasks_root(self.team_name)
        for f in root.glob("task-*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                task = TaskItem.model_validate(data)
                if completed_task_id in task.blocked_by:
                    task.blocked_by.remove(completed_task_id)
                    if not task.blocked_by and task.status == TaskStatus.blocked:
                        task.status = TaskStatus.pending
                    task.updated_at = _now_iso()
                    self._save_unlocked(task)
            except Exception:
                continue

    def _apply_failure_flow_unlocked(self, failed_task: TaskItem) -> None:
        on_fail_targets = failed_task.metadata.get("on_fail", [])
        if (
            not on_fail_targets
            or not failed_task.started_at
            or failed_task.metadata.get("failure_kind") != "regular"
        ):
            return

        for target_id in on_fail_targets:
            target = self._get_unlocked(target_id)
            if target is None:
                continue

            target.status = TaskStatus.pending
            target.locked_by = ""
            target.locked_at = ""
            target.updated_at = _now_iso()
            self._save_unlocked(target)
