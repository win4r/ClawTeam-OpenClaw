"""HarnessContext — unified capability interface for plugins."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from clawteam.events.bus import EventBus
    from clawteam.harness.artifacts import ArtifactStore
    from clawteam.harness.strategies import SpawnStrategy


class HarnessContext:
    """Provides plugins with access to all framework capabilities.

    Instead of giving plugins just an EventBus (listen-only), this context
    lets plugins both observe AND act: query tasks, spawn agents, read/write
    artifacts, manage sessions.
    """

    def __init__(
        self,
        bus: EventBus,
        team_name: str = "",
        tasks: Any = None,           # TaskStore or None
        spawner: SpawnStrategy | None = None,
        sessions: Any = None,        # SessionStore or None
        artifacts: ArtifactStore | None = None,
        config: Any = None,          # ClawTeamConfig or None
    ) -> None:
        self.bus = bus
        self.team_name = team_name
        self.tasks = tasks
        self.spawner = spawner
        self.sessions = sessions
        self.artifacts = artifacts
        self.config = config

    def get_tasks(self):
        """Get TaskStore, lazily creating if needed."""
        if self.tasks is None and self.team_name:
            from clawteam.team.tasks import TaskStore
            self.tasks = TaskStore(self.team_name)
        return self.tasks

    def get_sessions(self):
        """Get SessionStore, lazily creating if needed."""
        if self.sessions is None and self.team_name:
            from clawteam.spawn.sessions import SessionStore
            self.sessions = SessionStore(self.team_name)
        return self.sessions

    def get_config(self):
        """Get ClawTeamConfig, lazily loading if needed."""
        if self.config is None:
            from clawteam.config import load_config
            self.config = load_config()
        return self.config
