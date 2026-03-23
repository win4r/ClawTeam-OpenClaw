"""Failure-notice delivery helpers for task failures."""

from __future__ import annotations

from typing import Any

from clawteam.team.models import TaskItem


def notify_task_failure(team: str, task: TaskItem, caller: str) -> dict[str, Any] | None:
    """Deliver a complex-failure notice to the team leader via mailbox."""
    from clawteam.team.mailbox import MailboxManager
    from clawteam.team.manager import TeamManager

    failure_kind = task.metadata.get("failure_kind", "complex")
    if failure_kind != "complex":
        return {"failureNotice": "skipped", "failureKind": failure_kind}

    leader_name = TeamManager.get_leader_name(team)
    if not leader_name:
        return {"failureNotice": "no-leader", "failureKind": failure_kind}

    root_cause = task.metadata.get("failure_root_cause") or "Unspecified"
    evidence = task.metadata.get("failure_evidence") or (task.metadata.get("failure_note") or "No evidence provided.")
    next_owner = task.metadata.get("failure_recommended_next_owner") or "leader"
    next_action = task.metadata.get("failure_recommended_action") or "Decide reroute/recovery"
    content = "\n".join(
        [
            f"COMPLEX FAIL: {task.subject} ({task.id})",
            f"Owner: {task.owner or '(unassigned)'}",
            f"Root cause: {root_cause}",
            f"Evidence: {evidence}",
            f"Recommended next owner: {next_owner}",
            f"Recommended action: {next_action}",
        ]
    )
    mailbox = MailboxManager(team)
    message = mailbox.send(from_agent=caller, to=leader_name, content=content)
    return {
        "failureNotice": "sent",
        "failureKind": failure_kind,
        "failureLeader": leader_name,
        "failureMessageId": message.request_id,
    }
