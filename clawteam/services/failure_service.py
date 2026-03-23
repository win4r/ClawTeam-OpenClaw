"""Compatibility wrapper for failure-notice delivery."""

from __future__ import annotations

from typing import Any

from clawteam.delivery.failure_notifier import notify_task_failure
from clawteam.team.models import TaskItem


def handle_failed_task_notice(team: str, task: TaskItem, caller: str) -> dict[str, Any] | None:
    return notify_task_failure(team=team, task=task, caller=caller)
