"""Failure-notice delivery helpers for task failures."""

from __future__ import annotations

from typing import Any

from clawteam.team.models import TaskItem


FAILURE_REPAIR_PACKET_KEYS = (
    "failure_target_files",
    "failure_repro_steps",
    "failure_expected_result",
    "failure_candidate_patch",
)


def _build_failure_repair_packet(task: TaskItem) -> list[str]:
    lines: list[str] = []
    target_files = task.metadata.get("failure_target_files") if isinstance(task.metadata, dict) else None
    if isinstance(target_files, list):
        filtered = [str(item).strip() for item in target_files if str(item).strip()]
        if filtered:
            lines.append("Repair packet / target files:")
            lines.extend(f"- {item}" for item in filtered)

    repro_steps = str(task.metadata.get("failure_repro_steps") or "").strip() if isinstance(task.metadata, dict) else ""
    if repro_steps:
        lines.append(f"Repair packet / repro steps: {repro_steps}")

    expected_result = str(task.metadata.get("failure_expected_result") or "").strip() if isinstance(task.metadata, dict) else ""
    if expected_result:
        lines.append(f"Repair packet / expected result: {expected_result}")

    candidate_patch = str(task.metadata.get("failure_candidate_patch") or "").strip() if isinstance(task.metadata, dict) else ""
    if candidate_patch:
        lines.append(f"Repair packet / candidate patch: {candidate_patch}")

    return lines


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
            *_build_failure_repair_packet(task),
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
