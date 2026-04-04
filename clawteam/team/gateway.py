"""Gateway integration utilities for ClawTeam ↔ A2A Gateway coordination.

Provides:
- Config export: generate Gateway-compatible peers JSON from team config
- Cost event sink: ingest external cost events (e.g. from A2A Gateway audit)
- Liveness notification: notify gateway when agents shut down
"""

from __future__ import annotations

import json
import logging
from typing import Any

from clawteam.team.manager import TeamManager
from clawteam.team.models import TeamConfig

logger = logging.getLogger(__name__)


def export_gateway_peers(
    team_name: str,
    gateway_base_url: str = "",
) -> list[dict[str, Any]]:
    """Export team members as Gateway-compatible peers config.

    Returns a list of peer objects matching the Gateway ``peers[]`` schema::

        [{"name": "agent-name", "agentCardUrl": "...", "metadata": {...}}]
    """
    config: TeamConfig | None = TeamManager.get_team(team_name)
    if not config:
        raise ValueError(f"Team '{team_name}' not found")

    peers: list[dict[str, Any]] = []
    for member in config.members:
        peer: dict[str, Any] = {
            "name": member.name,
            "agentId": member.agent_id,
            "agentType": member.agent_type,
            "model": member.model_name or None,
        }
        if gateway_base_url:
            peer["agentCardUrl"] = f"{gateway_base_url.rstrip('/')}/.well-known/agent.json"
        peers.append(peer)

    return peers


def export_gateway_config(
    team_name: str,
    gateway_base_url: str = "",
    include_routing: bool = True,
) -> dict[str, Any]:
    """Export full Gateway-compatible config fragment for a team.

    Includes peers list, routing rules (agentId-based), and agent card skills.
    """
    config: TeamConfig | None = TeamManager.get_team(team_name)
    if not config:
        raise ValueError(f"Team '{team_name}' not found")

    peers = export_gateway_peers(team_name, gateway_base_url)

    # Build skills from team members
    skills = [
        {
            "id": m.name,
            "name": m.name,
            "description": f"{m.agent_type} agent",
        }
        for m in config.members
    ]

    result: dict[str, Any] = {
        "teamName": team_name,
        "description": config.description,
        "peers": peers,
        "agentCard": {
            "name": f"ClawTeam: {team_name}",
            "description": config.description or f"ClawTeam team '{team_name}'",
            "skills": skills,
        },
    }

    if include_routing:
        rules = []
        for m in config.members:
            rules.append({
                "name": f"route-to-{m.name}",
                "match": {"pattern": f"(?i)@{m.name}\\b"},
                "target": {"agentId": m.agent_id},
                "priority": 0,
            })
        result["routing"] = {
            "defaultAgentId": config.lead_agent_id,
            "rules": rules,
        }

    return result


def notify_gateway_agent_status(
    gateway_url: str,
    agent_name: str,
    agent_id: str,
    status: str,
    team_name: str = "",
    timeout_seconds: float = 5.0,
) -> bool:
    """Notify A2A Gateway of agent status change (e.g. shutdown).

    Sends a best-effort HTTP POST. Returns True on success, False on failure.
    Does not raise exceptions.
    """
    import urllib.error
    import urllib.request

    url = f"{gateway_url.rstrip('/')}/a2a/webhooks/agent-status"
    payload = json.dumps({
        "agentName": agent_name,
        "agentId": agent_id,
        "status": status,
        "teamName": team_name,
    }).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds):
            pass
        logger.info("Gateway notified: %s %s → %s", agent_name, status, gateway_url)
        return True
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        logger.debug("Gateway notification failed (best-effort): %s", exc)
        return False
