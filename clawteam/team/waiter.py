"""Task waiter - blocks until all tasks in a team are completed."""

from __future__ import annotations

import logging
import signal
import time
from dataclasses import dataclass, field
from typing import Callable

from clawteam.team.mailbox import MailboxManager
from clawteam.team.models import TaskItem, TaskStatus, TeamMessage
from clawteam.team.tasks import TaskStore

logger = logging.getLogger(__name__)


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
        max_respawn_attempts: int = 3,
        auto_respawn: bool = True,
        max_concurrent_agents: int = 0,
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
        self.max_respawn_attempts = max_respawn_attempts
        self.auto_respawn = auto_respawn
        self.max_concurrent_agents = max_concurrent_agents
        self._running = False
        self._messages_received = 0
        self._known_dead: set[str] = set()
        self._respawn_attempts: dict[str, int] = {}
        self._respawn_queue: list[str] = []

    def wait(self) -> WaitResult:
        """Block until all tasks are completed, timeout, or interrupted."""
        self._running = True
        start = time.monotonic()

        # Save and install signal handlers
        prev_sigint = signal.getsignal(signal.SIGINT)
        prev_sigterm = signal.getsignal(signal.SIGTERM)

        def _handle_signal(signum, frame):
            self._running = False

        signal.signal(signal.SIGINT, _handle_signal)
        signal.signal(signal.SIGTERM, _handle_signal)

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
                if total > 0 and completed == total:
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
            # Restore original signal handlers
            signal.signal(signal.SIGINT, prev_sigint)
            signal.signal(signal.SIGTERM, prev_sigterm)

    def _check_dead_agents(self) -> None:
        """Detect dead agents, reset their tasks, and attempt respawn."""
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
                t for t in tasks if t.owner == agent_name and t.status == TaskStatus.in_progress
            ]
            for t in abandoned:
                self.task_store.update(t.id, status=TaskStatus.pending)

            if abandoned and self.on_agent_dead:
                self.on_agent_dead(agent_name, abandoned)

            # Queue for respawn (don't spawn immediately — check concurrency first)
            if self.auto_respawn and agent_name not in self._respawn_queue:
                self._respawn_queue.append(agent_name)

        # Process respawn queue with concurrency limit
        if self._respawn_queue:
            self._process_respawn_queue()

    def _process_respawn_queue(self) -> None:
        """Process queued respawns, respecting max_concurrent_agents limit."""
        if not self._respawn_queue:
            return

        # Check how many agents are currently alive
        if self.max_concurrent_agents > 0:
            try:
                from clawteam.spawn.registry import count_alive_agents
                alive = count_alive_agents(self.team_name)
            except ImportError:
                alive = 0

            if alive >= self.max_concurrent_agents:
                logger.info(
                    "Respawn deferred: %d/%d agents alive (limit reached), "
                    "%d in queue",
                    alive,
                    self.max_concurrent_agents,
                    len(self._respawn_queue),
                )
                return

            # Only spawn up to the available slots
            available_slots = self.max_concurrent_agents - alive
        else:
            available_slots = len(self._respawn_queue)  # no limit

        spawned = 0
        remaining = []
        for agent_name in self._respawn_queue:
            if spawned >= available_slots:
                remaining.append(agent_name)
                continue
            if self._respawn_agent(agent_name):
                spawned += 1
            # If respawn returned False (max attempts exceeded or no info),
            # don't re-queue
        self._respawn_queue = remaining

    def _respawn_agent(self, agent_name: str) -> bool:
        """Attempt to respawn a dead agent using stored spawn info.

        Returns True if spawn was attempted (success or fail),
        False if skipped (max attempts exceeded or no spawn info).
        """
        try:
            from clawteam.spawn import get_backend
            from clawteam.spawn.registry import get_registry
        except ImportError:
            return False

        attempt = self._respawn_attempts.get(agent_name, 0)
        if attempt >= self.max_respawn_attempts:
            logger.warning(
                "Agent '%s' exceeded max respawn attempts (%d), skipping",
                agent_name,
                self.max_respawn_attempts,
            )
            return False

        registry = get_registry(self.team_name)
        info = registry.get(agent_name)
        if not info or not info.get("command"):
            logger.warning("No spawn info for agent '%s', cannot respawn", agent_name)
            return False

        backoff = respawn_backoff(attempt)
        self._respawn_attempts[agent_name] = attempt + 1

        logger.info(
            "Respawning agent '%s' (attempt %d/%d, backoff %.0fs)",
            agent_name,
            attempt + 1,
            self.max_respawn_attempts,
            backoff,
        )
        time.sleep(backoff)

        backend_name = info.get("backend", "tmux")
        try:
            be = get_backend(backend_name)
            result = be.spawn(
                command=info["command"],
                agent_name=agent_name,
                agent_id=info.get("agent_id", ""),
                agent_type=info.get("agent_type", ""),
                team_name=self.team_name,
                prompt=info.get("prompt") or None,
                cwd=info.get("spawn_cwd") or None,
                skip_permissions=info.get("skip_permissions", False),
                stagger_seconds=info.get("stagger_seconds", 0),
            )
            if result.startswith("Error"):
                logger.error("Respawn failed for '%s': %s", agent_name, result)
            else:
                logger.info("Respawned agent '%s': %s", agent_name, result)
                # Allow re-detection if it dies again
                self._known_dead.discard(agent_name)
            return True
        except Exception:
            logger.exception("Respawn failed for agent '%s'", agent_name)
            return True


def respawn_backoff(attempt: int, max_delay: float = 120.0) -> float:
    """Calculate exponential backoff delay for respawn attempts.

    Returns 10, 30, 60, 120 (capped) for attempts 0, 1, 2, 3+.
    """
    delays = [10.0, 30.0, 60.0, 120.0]
    if attempt < len(delays):
        return min(delays[attempt], max_delay)
    return max_delay


def _task_summary(task: TaskItem) -> dict:
    """Summarize a task for the wait result."""
    return {
        "id": task.id,
        "subject": task.subject,
        "status": task.status.value,
        "owner": task.owner,
    }
