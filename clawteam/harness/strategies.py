"""Strategy interfaces for pluggable harness behavior."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class SpawnStrategy(ABC):
    """How to spawn agents for a phase."""

    @abstractmethod
    def spawn_for_phase(self, phase: str, orchestrator: Any) -> list[str]:
        """Spawn agents for the given phase. Returns list of agent names."""

    def respawn(
        self,
        agent_name: str,
        team_name: str,
        resume: bool = True,
        extra_prompt: str = "",
    ) -> str:
        """Re-spawn an agent, optionally resuming its session."""
        return ""


class RespawnStrategy(ABC):
    """How to handle agent exits — re-spawn or let go."""

    @abstractmethod
    def should_respawn(self, agent_name: str, team_name: str) -> bool:
        """Return True if the agent should be re-spawned."""

    @abstractmethod
    def on_agent_exit(
        self,
        agent_name: str,
        team_name: str,
        exit_info: dict,
        spawn_strategy: SpawnStrategy,
    ) -> None:
        """Handle agent exit: re-spawn if needed."""


class HealthStrategy(ABC):
    """How to check agent health."""

    @abstractmethod
    def check(self, team_name: str) -> list[dict]:
        """Check health of all agents. Returns list of issues found."""


class ExitNotifier(ABC):
    """Cross-process notification of agent exits."""

    @abstractmethod
    def record_exit(
        self,
        agent_name: str,
        exit_code: int | None = None,
        abandoned_tasks: list[str] | None = None,
    ) -> None:
        """Record an agent exit (called from the exiting process)."""

    @abstractmethod
    def read_new(self) -> list[dict]:
        """Read new exit records since last call (called from conductor)."""


class AssignmentStrategy(ABC):
    """How to assign contracts to agents."""

    @abstractmethod
    def assign(
        self,
        contracts: list,
        agent_names: list[str],
    ) -> dict[str, list]:
        """Assign contracts to agents. Returns {agent_name: [contracts]}."""
