"""Spawn registry - persists agent process info for liveness checking."""

from __future__ import annotations

import json
import subprocess
import time
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field

from clawteam.fileutil import atomic_write_text, file_locked
from clawteam.paths import ensure_within_root, validate_identifier
from clawteam.team.models import get_data_dir

# ---------------------------------------------------------------------------
# Circuit Breaker — agent health tracking
# ---------------------------------------------------------------------------

class HealthState(str, Enum):
    healthy = "healthy"
    degraded = "degraded"
    open = "open"


class AgentHealth(BaseModel):
    """Health status for a spawned agent (circuit breaker pattern)."""

    model_config = {"populate_by_name": True}

    agent_name: str = Field(alias="agentName")
    state: HealthState = HealthState.healthy
    quality_score: float = Field(default=1.0, alias="qualityScore")
    consecutive_failures: int = Field(default=0, alias="consecutiveFailures")
    total_successes: int = Field(default=0, alias="totalSuccesses")
    total_failures: int = Field(default=0, alias="totalFailures")
    last_failure_at: float = Field(default=0.0, alias="lastFailureAt")
    cooldown_seconds: float = Field(default=60.0, alias="cooldownSeconds")

    @property
    def is_accepting_tasks(self) -> bool:
        """Return True if the agent can accept new tasks."""
        if self.state != HealthState.open:
            return True
        # Half-open: allow after cooldown
        if self.last_failure_at and (time.time() - self.last_failure_at) >= self.cooldown_seconds:
            return True
        return False


DEFAULT_FAILURE_THRESHOLD = 3
DEFAULT_COOLDOWN_SECONDS = 60.0


def _health_path(team_name: str) -> Path:
    return ensure_within_root(
        get_data_dir() / "teams",
        validate_identifier(team_name, "team name"),
        "agent_health.json",
    )


def _load_health(team_name: str) -> dict[str, dict]:
    path = _health_path(team_name)
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_health(team_name: str, data: dict[str, dict]) -> None:
    atomic_write_text(_health_path(team_name), json.dumps(data, indent=2))


def get_agent_health(team_name: str, agent_name: str) -> AgentHealth:
    """Return health status for an agent (creates default if not tracked)."""
    health_data = _load_health(team_name)
    if agent_name in health_data:
        return AgentHealth.model_validate(health_data[agent_name])
    return AgentHealth(agent_name=agent_name)


def get_all_health(team_name: str) -> dict[str, AgentHealth]:
    """Return health for all tracked agents."""
    health_data = _load_health(team_name)
    return {
        name: AgentHealth.model_validate(data)
        for name, data in health_data.items()
    }


def record_outcome(
    team_name: str,
    agent_name: str,
    success: bool,
    failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
    cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
) -> AgentHealth:
    """Record a task outcome and update agent health state.

    State transitions:
    - healthy → degraded: first failure
    - degraded → open: consecutive_failures >= threshold
    - open → healthy: success after cooldown (half-open probe)
    - any → healthy: success resets consecutive failures
    """
    path = _health_path(team_name)
    with file_locked(path):
        health_data = _load_health(team_name)
        raw = health_data.get(agent_name, {"agentName": agent_name})
        health = AgentHealth.model_validate(raw)
        health.cooldown_seconds = cooldown_seconds

        if success:
            health.consecutive_failures = 0
            health.total_successes += 1
            health.quality_score = min(1.0, health.quality_score + 0.1)
            health.state = HealthState.healthy
        else:
            health.consecutive_failures += 1
            health.total_failures += 1
            health.last_failure_at = time.time()
            health.quality_score = max(0.0, health.quality_score - 0.2)
            if health.consecutive_failures >= failure_threshold:
                health.state = HealthState.open
            elif health.consecutive_failures >= 1:
                health.state = HealthState.degraded

        health_data[agent_name] = json.loads(health.model_dump_json(by_alias=True))
        _save_health(team_name, health_data)
    return health


def _registry_path(team_name: str) -> Path:
    return ensure_within_root(
        get_data_dir() / "teams",
        validate_identifier(team_name, "team name"),
        "spawn_registry.json",
    )


def register_agent(
    team_name: str,
    agent_name: str,
    backend: str,
    tmux_target: str = "",
    pid: int = 0,
    command: list[str] | None = None,
) -> None:
    """Record spawn info for an agent (atomic + locked write)."""
    path = _registry_path(team_name)
    with file_locked(path):
        registry = _load(path)
        registry[agent_name] = {
            "backend": backend,
            "tmux_target": tmux_target,
            "pid": pid,
            "command": command or [],
            "spawned_at": time.time(),
        }
        _save(path, registry)


def unregister_agent(team_name: str, agent_name: str) -> None:
    """Remove an agent entry from the spawn registry."""
    path = _registry_path(team_name)
    registry = _load(path)
    registry.pop(agent_name, None)
    _save(path, registry)


def get_registry(team_name: str) -> dict[str, dict]:
    """Return the full spawn registry for a team."""
    return _load(_registry_path(team_name))


def get_agent_info(team_name: str, agent_name: str) -> dict | None:
    """Return persisted spawn info for a single agent, if any."""
    registry = get_registry(team_name)
    info = registry.get(agent_name)
    return info if isinstance(info, dict) else None


def is_agent_alive(team_name: str, agent_name: str) -> bool | None:
    """Check if a spawned agent process is still alive.

    Returns True if alive, False if dead, None if no spawn info found.
    """
    registry = get_registry(team_name)
    info = registry.get(agent_name)
    if not info:
        return None

    backend = info.get("backend", "")
    if backend == "tmux":
        alive = _tmux_pane_alive(info.get("tmux_target", ""))
        if alive is False:
            # Tmux target may be invalid (e.g. after tile operation);
            # fall back to PID check
            pid = info.get("pid", 0)
            if pid:
                return _pid_alive(pid)
        return alive
    elif backend == "subprocess":
        return _pid_alive(info.get("pid", 0))
    return None


def list_dead_agents(team_name: str) -> list[str]:
    """Return names of agents whose processes are no longer alive."""
    registry = get_registry(team_name)
    dead = []
    for name, info in registry.items():
        alive = is_agent_alive(team_name, name)
        if alive is False:
            dead.append(name)
    return dead



def list_zombie_agents(team_name: str, max_hours: float = 2.0) -> list[dict]:
    """Return agents that are still alive but have been running longer than max_hours.

    Each entry contains: agent_name, pid, backend, spawned_at (unix ts), running_hours.
    Agents with no spawned_at recorded are skipped (legacy registry entries).
    """
    registry = get_registry(team_name)
    threshold = max_hours * 3600
    now = time.time()
    zombies = []
    for name, info in registry.items():
        spawned_at = info.get("spawned_at")
        if not spawned_at:
            continue
        alive = is_agent_alive(team_name, name)
        if alive is True:
            running_seconds = now - spawned_at
            if running_seconds > threshold:
                zombies.append({
                    "agent_name": name,
                    "pid": info.get("pid", 0),
                    "backend": info.get("backend", ""),
                    "spawned_at": spawned_at,
                    "running_hours": round(running_seconds / 3600, 1),
                })
    return zombies



def _tmux_pane_alive(target: str) -> bool:
    """Check if a tmux target (session:window) still has a running process."""
    if not target:
        return False
    # Check if the window exists at all
    result = subprocess.run(
        ["tmux", "list-panes", "-t", target, "-F", "#{pane_dead} #{pane_current_command}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        # Window doesn't exist anymore
        return False
    # Check pane_dead flag — "1" means the command has exited
    for line in result.stdout.strip().splitlines():
        parts = line.split(None, 1)
        if parts and parts[0] == "1":
            return False
        # Also check if the pane is just running a shell (agent exited, shell remains)
        if len(parts) >= 2 and parts[1] in ("bash", "zsh", "sh", "fish"):
            return False
    return True


def _pid_alive(pid: int) -> bool:
    """Check if a process with the given PID is still running."""
    if pid <= 0:
        return False
    try:
        import os
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we can't signal it
        return True


def _load(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save(path: Path, data: dict) -> None:
    atomic_write_text(path, json.dumps(data, indent=2))
