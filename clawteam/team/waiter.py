"""Task waiter - blocks until all tasks in a team are completed."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass, field
from typing import Callable

from clawteam.platform_compat import install_signal_handlers, restore_signal_handlers
from clawteam.team.mailbox import MailboxManager
from clawteam.team.models import TaskItem, TaskStatus, TeamMessage
from clawteam.team.tasks import TaskStore


def _check_stalled_workers(team_dir: Path, threshold_s: float = 120.0) -> list[tuple[str, float]]:
    """Return workers whose heartbeat age exceeds threshold_s.

    Heartbeat support is optional while v2 slices land; absence of the
    heartbeat module is treated as no stalled workers.
    """
    try:
        from clawteam.team.heartbeat import list_heartbeats
    except Exception:
        return []

    now = datetime.now(timezone.utc)
    stalled: list[tuple[str, float]] = []
    for heartbeat in list_heartbeats(team_dir):
        try:
            age = (now - heartbeat.last_turn_at.astimezone(timezone.utc)).total_seconds()
        except Exception:
            continue
        if age > threshold_s:
            stalled.append((heartbeat.agent, age))
    return stalled


@dataclass
class WaitResult:
    """Result returned by TaskWaiter.wait()."""

    status: str  # "completed", "timeout", "interrupted"
    elapsed: float = 0.0
    total: int = 0
    completed: int = 0
    in_progress: int = 0
    pending: int = 0
    blocked: int = 0
    messages_received: int = 0
    task_details: list[dict] = field(default_factory=list)


class TaskWaiter:
    """Blocks until all tasks in a team reach completed status.

    Each poll cycle:
    1. Drain inbox messages and invoke on_message callback
    2. Detect dead agents and recover their in_progress tasks
    3. Check task completion and invoke on_progress callback (if changed)
    4. Return if all done, timed out, or interrupted
    5. Sleep poll_interval seconds
    """

    def __init__(
        self,
        team_name: str,
        agent_name: str,
        mailbox: MailboxManager,
        task_store: TaskStore,
        poll_interval: float = 5.0,
        timeout: float | None = None,
        on_message: Callable[[TeamMessage], None] | None = None,
        on_progress: Callable[[int, int, int, int, int], None] | None = None,
        on_agent_dead: Callable[[str, list[TaskItem]], None] | None = None,
        on_worker_stalled: Callable[[str, float], None] | None = None,
    ):
        self.team_name = team_name
        self.agent_name = agent_name
        self.mailbox = mailbox
        self.task_store = task_store
        self.poll_interval = poll_interval
        self.timeout = timeout
        self.on_message = on_message
        self.on_progress = on_progress
        self.on_agent_dead = on_agent_dead
        self.on_worker_stalled = on_worker_stalled
        self._running = False
        self._messages_received = 0
        self._known_dead: set[str] = set()
        self._already_flagged_stalled: set[str] = set()


    def _team_dir(self) -> Path:
        from clawteam.team.models import get_data_dir

        return get_data_dir() / "teams" / self.team_name

    def _run_stall_check(self) -> None:
        """Emit a one-shot callback/event for newly stalled heartbeat workers."""
        try:
            stalled = dict(_check_stalled_workers(self._team_dir()))
        except Exception:
            return

        for agent_name, seconds in stalled.items():
            if agent_name in self._already_flagged_stalled:
                continue
            self._already_flagged_stalled.add(agent_name)
            if self.on_worker_stalled:
                self.on_worker_stalled(agent_name, seconds)
            try:
                from clawteam.events.global_bus import get_event_bus
                from clawteam.events.types import HeartbeatTimeout
                from clawteam.team.heartbeat import read_heartbeat

                heartbeat = read_heartbeat(self._team_dir(), agent_name)
                last_seen = heartbeat.last_turn_at.isoformat() if heartbeat else ""
                get_event_bus().emit_async(
                    HeartbeatTimeout(
                        team_name=self.team_name,
                        agent_name=agent_name,
                        last_seen=last_seen,
                    )
                )
            except Exception:
                pass

        self._already_flagged_stalled.intersection_update(stalled)

    def wait(self) -> WaitResult:
        """Block until all tasks are completed, timeout, or interrupted."""
        self._running = True
        start = time.monotonic()

        # Save and install signal handlers
        def _handle_signal(signum, frame):
            self._running = False

        previous_handlers = install_signal_handlers(_handle_signal)

        last_summary = ""
        try:
            while self._running:
                # 1. Drain inbox messages
                messages = self.mailbox.receive(self.agent_name, limit=50)
                for msg in messages:
                    self._messages_received += 1
                    if self.on_message:
                        self.on_message(msg)

                # 2. Detect dead agents and recover their tasks
                self._check_dead_agents()

                # 2.5 Detect stalled heartbeat workers
                self._run_stall_check()

                # 3. Check task status
                tasks = self.task_store.list_tasks()
                total = len(tasks)
                completed = sum(1 for t in tasks if t.status == TaskStatus.completed)
                in_progress = sum(1 for t in tasks if t.status == TaskStatus.in_progress)
                pending = sum(1 for t in tasks if t.status == TaskStatus.pending)
                blocked = sum(1 for t in tasks if t.status == TaskStatus.blocked)

                # Deduplicate progress output
                summary = f"{completed}/{total}/{in_progress}/{pending}/{blocked}"
                if summary != last_summary:
                    if self.on_progress:
                        self.on_progress(completed, total, in_progress, pending, blocked)
                    last_summary = summary

                # 4. All done?
                if completed == total:
                    # Final drain — catch messages that arrived after task completion
                    for msg in self.mailbox.receive(self.agent_name, limit=50):
                        self._messages_received += 1
                        if self.on_message:
                            self.on_message(msg)
                    elapsed = time.monotonic() - start
                    return WaitResult(
                        status="completed",
                        elapsed=elapsed,
                        total=total,
                        completed=completed,
                        in_progress=0,
                        pending=0,
                        blocked=0,
                        messages_received=self._messages_received,
                        task_details=[_task_summary(t) for t in tasks],
                    )

                # 5. Timeout?
                elapsed = time.monotonic() - start
                if self.timeout and elapsed >= self.timeout:
                    return WaitResult(
                        status="timeout",
                        elapsed=elapsed,
                        total=total,
                        completed=completed,
                        in_progress=in_progress,
                        pending=pending,
                        blocked=blocked,
                        messages_received=self._messages_received,
                        task_details=[_task_summary(t) for t in tasks],
                    )

                # 6. Sleep
                time.sleep(self.poll_interval)

            # Interrupted
            elapsed = time.monotonic() - start
            tasks = self.task_store.list_tasks()
            total = len(tasks)
            return WaitResult(
                status="interrupted",
                elapsed=elapsed,
                total=total,
                completed=sum(1 for t in tasks if t.status == TaskStatus.completed),
                in_progress=sum(1 for t in tasks if t.status == TaskStatus.in_progress),
                pending=sum(1 for t in tasks if t.status == TaskStatus.pending),
                blocked=sum(1 for t in tasks if t.status == TaskStatus.blocked),
                messages_received=self._messages_received,
                task_details=[_task_summary(t) for t in tasks],
            )
        finally:
            restore_signal_handlers(previous_handlers)

    def _check_dead_agents(self) -> None:
        """Detect dead agents and mark their in_progress tasks as pending."""
        try:
            from clawteam.spawn.registry import list_dead_agents
        except ImportError:
            return

        dead_agents = list_dead_agents(self.team_name)
        for agent_name in dead_agents:
            if agent_name in self._known_dead:
                continue
            self._known_dead.add(agent_name)

            # Find this agent's in_progress tasks and reset them
            tasks = self.task_store.list_tasks()
            abandoned = [
                t for t in tasks
                if t.owner == agent_name and t.status == TaskStatus.in_progress
            ]
            for t in abandoned:
                self.task_store.update(t.id, status=TaskStatus.pending)

            if abandoned and self.on_agent_dead:
                self.on_agent_dead(agent_name, abandoned)

            # Auto-respawn if there are pending tasks (fallback for when on-exit hook didn't fire)
            if abandoned:
                try:
                    from clawteam.spawn.respawn import respawn_agent
                    respawn_agent(self.team_name, agent_name)
                except Exception:
                    pass  # Best-effort; on-exit hook is the primary respawn path


def _task_summary(task: TaskItem) -> dict:
    """Summarize a task for the wait result."""
    return {
        "id": task.id,
        "subject": task.subject,
        "status": task.status.value,
        "owner": task.owner,
    }
