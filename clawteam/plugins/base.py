"""Base class for ClawTeam plugins."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from clawteam.harness.context import HarnessContext
    from clawteam.harness.phases import PhaseGate


class HarnessPlugin(ABC):
    """Base class for all ClawTeam plugins.

    Plugins receive a HarnessContext that provides access to the full
    framework: event bus, task store, spawner, sessions, artifacts.
    """

    name: str = ""
    version: str = "0.1.0"
    description: str = ""

    @abstractmethod
    def on_register(self, ctx: HarnessContext) -> None:
        """Called when the plugin is loaded.

        Use ctx.bus to subscribe to events.
        Use ctx.tasks/spawner/sessions/artifacts to take actions.
        """

    def on_unregister(self) -> None:
        """Called when the plugin is unloaded."""

    def contribute_gates(self) -> dict[str, list[PhaseGate]]:
        """Contribute gates to specific phases. Returns {phase: [gates]}."""
        return {}

    def contribute_prompts(self, phase: str, role: str) -> str:
        """Contribute additional prompt text for agents in the given phase/role."""
        return ""
