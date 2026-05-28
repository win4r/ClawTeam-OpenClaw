"""Helpers for rendering runtime notifications for live agent injection."""

from __future__ import annotations

from xml.sax.saxutils import escape


def render_runtime_notification(envelope) -> str:
    """Render a structured runtime notification payload for a live agent."""
    summary = str(getattr(envelope, "summary", "") or "").strip()
    if not summary:
        summary = "Runtime update"

    evidence = getattr(envelope, "evidence", []) or []
    if isinstance(evidence, str):
        evidence = [evidence]
    evidence_block = "\n".join(str(item) for item in evidence if item)

    lines = [
        '<clawteam_notification version="1"',
        f'  source="{escape(str(getattr(envelope, "source", "system") or "system"))}"',
        f'  target="{escape(str(getattr(envelope, "target", "") or ""))}"',
        f'  channel="{escape(str(getattr(envelope, "channel", "direct") or "direct"))}"',
        f'  priority="{escape(str(getattr(envelope, "priority", "medium") or "medium"))}">',
        "<summary>",
        escape(summary),
        "</summary>",
    ]

    if evidence_block:
        lines.extend(["<evidence>", escape(evidence_block), "</evidence>"])
    recommended_next_action = str(getattr(envelope, "recommended_next_action", "") or "").strip()
    if recommended_next_action:
        lines.extend(
            [
                "<recommended_next_action>",
                escape(recommended_next_action),
                "</recommended_next_action>",
            ]
        )

    lines.append("</clawteam_notification>")
    return "\n".join(lines)
