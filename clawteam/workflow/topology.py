"""Workflow topology helpers for task dependency relationships."""

from __future__ import annotations

from clawteam.team.models import TaskItem, TaskStatus


class WorkflowTopology:
    """Pure helper for dependency/follow-up topology decisions."""

    def __init__(self, tasks: list[TaskItem]):
        self.tasks = tasks

    def dependents_of(self, task_id: str) -> list[TaskItem]:
        return [task for task in self.tasks if task_id in task.blocked_by]

    def wake_on_complete(self, task_id: str) -> list[str]:
        return [
            task.id
            for task in self.dependents_of(task_id)
            if task.status == TaskStatus.blocked
        ]

    def wake_on_regular_failure(self, task: TaskItem) -> list[str]:
        if not task.started_at:
            return []
        return list(task.metadata.get("on_fail", []))
