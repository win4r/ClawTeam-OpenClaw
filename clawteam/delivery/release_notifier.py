"""Release/wake delivery helpers for task release notifications."""

from __future__ import annotations

from typing import Any

from clawteam.team.models import TaskItem


def notify_task_release(team: str, task: TaskItem, caller: str, message: str) -> dict[str, Any] | None:
    """Deliver a task release/wake notice to the task owner via mailbox."""
    from clawteam.team.mailbox import MailboxManager

    mailbox = MailboxManager(team)
    sent = mailbox.send(
        caller,
        task.owner,
        message,
        key=f"task-wake:{task.id}",
        last_task=task.id,
        status=task.status.value,
    )
    return {
        "messageSent": True,
        "message": message,
        "messageId": sent.request_id,
    }
