"""Event types for the ClawTeam event bus."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class HarnessEvent:
    """Base class for all harness events."""

    team_name: str = ""
    timestamp: str = field(default_factory=_now_iso)


# ── Worker lifecycle ──────────────────────────────────────────────────


@dataclass
class BeforeWorkerSpawn(HarnessEvent):
    """Fired before a worker agent is spawned. Set veto=True to cancel."""

    agent_name: str = ""
    agent_type: str = ""
    command: list[str] = field(default_factory=list)
    veto: bool = False


@dataclass
class AfterWorkerSpawn(HarnessEvent):
    """Fired after a worker agent has been successfully spawned."""

    agent_name: str = ""
    agent_id: str = ""
    backend: str = ""
    target: str = ""  # e.g. tmux target


@dataclass
class WorkerExit(HarnessEvent):
    """Fired when a worker process exits normally."""

    agent_name: str = ""
    exit_code: int | None = None
    abandoned_tasks: list[str] = field(default_factory=list)


@dataclass
class WorkerCrash(HarnessEvent):
    """Fired when a worker process crashes (SIGKILL, OOM, etc.)."""

    agent_name: str = ""
    error: str = ""


# ── Task lifecycle ────────────────────────────────────────────────────


@dataclass
class BeforeTaskCreate(HarnessEvent):
    """Fired before a task is created."""

    subject: str = ""
    owner: str = ""


@dataclass
class AfterTaskUpdate(HarnessEvent):
    """Fired after a task status changes."""

    task_id: str = ""
    old_status: str = ""
    new_status: str = ""
    owner: str = ""


@dataclass
class TaskCompleted(HarnessEvent):
    """Fired when a task transitions to completed."""

    task_id: str = ""
    owner: str = ""
    duration_seconds: float = 0.0


# ── Messaging ─────────────────────────────────────────────────────────


@dataclass
class BeforeInboxSend(HarnessEvent):
    """Fired before a message is sent."""

    from_agent: str = ""
    to: str = ""
    msg_type: str = ""


@dataclass
class AfterInboxReceive(HarnessEvent):
    """Fired after messages are consumed from an inbox."""

    agent_name: str = ""
    count: int = 0


# ── Workspace ─────────────────────────────────────────────────────────


@dataclass
class BeforeWorkspaceMerge(HarnessEvent):
    """Fired before a workspace merge."""

    agent_name: str = ""
    branch: str = ""


@dataclass
class AfterWorkspaceCleanup(HarnessEvent):
    """Fired after a workspace is cleaned up."""

    agent_name: str = ""


# ── Team lifecycle ────────────────────────────────────────────────────


@dataclass
class TeamLaunch(HarnessEvent):
    """Fired when a team is launched from a template."""

    template: str = ""
    agent_count: int = 0


@dataclass
class TeamShutdown(HarnessEvent):
    """Fired when a team is shut down and cleaned up."""

    pass


# ── Health ────────────────────────────────────────────────────────────


@dataclass
class AgentIdle(HarnessEvent):
    """Fired when an agent reports idle status."""

    agent_name: str = ""
    last_task: str = ""


@dataclass
class HeartbeatTimeout(HarnessEvent):
    """Fired when an agent's heartbeat times out."""

    agent_name: str = ""
    last_seen: str = ""


# ── Harness phases ────────────────────────────────────────────────────


@dataclass
class PhaseTransition(HarnessEvent):
    """Fired when the harness transitions between phases."""

    from_phase: str = ""
    to_phase: str = ""
    artifacts: list[str] = field(default_factory=list)


# ── Transport / Board ─────────────────────────────────────────────────


@dataclass
class TransportFallback(HarnessEvent):
    """Fired when a transport falls back to a secondary mechanism."""

    transport: str = ""
    fallback: str = ""
    reason: str = ""


@dataclass
class BoardAttach(HarnessEvent):
    """Fired when a user attaches to the board."""

    pass
