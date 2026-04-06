"""Auto-respawn logic for agents that exit abnormally."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

MAX_RESPAWN_ATTEMPTS = 2


def respawn_agent(
    team_name: str,
    agent_name: str,
    spawn_info: dict | None = None,
) -> str:
    """Attempt to respawn a dead agent using its recorded spawn info.

    Checks agent health (consecutive_failures) to enforce a max respawn limit.
    Records a failure outcome before attempting respawn so the circuit breaker
    tracks crash history.

    Args:
        team_name: Team the agent belongs to.
        agent_name: Logical name of the agent to respawn.
        spawn_info: Previously captured spawn registry entry.  When the caller
            already read the info before unregistering the dead agent it should
            pass it here; otherwise the function reads from the live registry.

    Returns:
        Status string — starts with ``"ok: "`` on success, ``"Error: "`` on failure.
    """
    from clawteam.spawn import get_backend, spawn_with_retry
    from clawteam.spawn.registry import get_agent_health, get_agent_info, record_outcome
    from clawteam.team.manager import TeamManager

    # Record the crash so consecutive_failures increments.
    health = record_outcome(team_name, agent_name, success=False)

    if health.consecutive_failures > MAX_RESPAWN_ATTEMPTS:
        return (
            f"Error: agent '{agent_name}' crashed {health.consecutive_failures} times "
            f"(max respawn attempts: {MAX_RESPAWN_ATTEMPTS}), not respawning"
        )

    info = spawn_info or get_agent_info(team_name, agent_name)
    if not info:
        return f"Error: no spawn info found for agent '{agent_name}'"

    member = TeamManager.get_member(team_name, agent_name)
    if not member:
        return f"Error: agent '{agent_name}' not found in team config"

    backend_name = info.get("backend", "tmux")
    command = info.get("command", [])
    if not command:
        return f"Error: no command recorded for agent '{agent_name}'"

    try:
        backend = get_backend(backend_name)
        result = spawn_with_retry(
            backend,
            max_retries=1,
            command=command,
            agent_name=agent_name,
            agent_id=member.agent_id,
            agent_type=member.agent_type,
            team_name=team_name,
            model=member.model_name or None,
        )

        if result.startswith("Error"):
            return f"Error: respawn failed for '{agent_name}': {result}"

        logger.info(
            "Respawned agent '%s' (crash count: %d/%d)",
            agent_name,
            health.consecutive_failures,
            MAX_RESPAWN_ATTEMPTS,
        )
        return (
            f"ok: respawned agent '{agent_name}' "
            f"(crash {health.consecutive_failures}/{MAX_RESPAWN_ATTEMPTS})"
        )
    except Exception as exc:
        return f"Error: respawn failed for '{agent_name}': {exc}"
