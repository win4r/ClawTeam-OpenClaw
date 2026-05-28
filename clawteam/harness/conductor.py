"""HarnessConductor: auto-drives the harness through phases."""

from __future__ import annotations

import signal
import sys
import time

from clawteam.harness.context import HarnessContext
from clawteam.harness.exit_journal import FileExitJournal
from clawteam.harness.orchestrator import HarnessOrchestrator
from clawteam.harness.spawner import PhaseRoleSpawner
from clawteam.harness.strategies import (
    ExitNotifier,
    HealthStrategy,
    RespawnStrategy,
    SpawnStrategy,
)


class RegistryHealthCheck(HealthStrategy):
    """Default health strategy using the spawn registry."""

    def check(self, team_name: str) -> list[dict]:
        try:
            from clawteam.spawn.registry import list_dead_agents
            return [{"agent": a, "status": "dead"} for a in list_dead_agents(team_name)]
        except Exception:
            return []


class NoRespawn(RespawnStrategy):
    """Default: don't re-spawn agents (Ralph Loop plugin replaces this)."""

    def should_respawn(self, agent_name: str, team_name: str) -> bool:
        return False

    def on_agent_exit(self, agent_name, team_name, exit_info, spawn_strategy):
        pass


class HarnessConductor:
    """Drives the harness through phases automatically.

    Runs as a foreground polling loop (like InboxWatcher).
    Ctrl+C to stop gracefully.
    """

    def __init__(
        self,
        orchestrator: HarnessOrchestrator,
        spawn_strategy: SpawnStrategy | None = None,
        respawn_strategy: RespawnStrategy | None = None,
        health_strategy: HealthStrategy | None = None,
        exit_notifier: ExitNotifier | None = None,
        poll_interval: float = 5.0,
        health_interval: float = 30.0,
    ) -> None:
        self._orch = orchestrator
        self._spawn = spawn_strategy or PhaseRoleSpawner(
            cli=orchestrator.cli,
        )
        self._respawn = respawn_strategy or NoRespawn()
        self._health = health_strategy or RegistryHealthCheck()
        self._exit_notifier = exit_notifier or FileExitJournal(
            orchestrator.team_name, orchestrator.state.harness_id,
        )
        self._poll_interval = poll_interval
        self._health_interval = health_interval
        self._running = False
        self._last_health_check = 0.0

    def build_context(self) -> HarnessContext:
        """Build a HarnessContext for plugins."""
        from clawteam.events.global_bus import get_event_bus
        return HarnessContext(
            bus=get_event_bus(),
            team_name=self._orch.team_name,
            spawner=self._spawn,
            artifacts=self._orch.artifacts,
        )

    def run(self) -> None:
        """Start the conductor loop. Blocks until harness completes or Ctrl+C."""
        self._running = True

        def _handle_signal(signum, frame):
            self._running = False
            print("\n[conductor] Stopping...", file=sys.stderr)

        signal.signal(signal.SIGINT, _handle_signal)
        signal.signal(signal.SIGTERM, _handle_signal)

        print(f"[conductor] Starting harness {self._orch.state.harness_id}", file=sys.stderr)
        print(f"[conductor] Phase: {self._orch.state.current_phase}", file=sys.stderr)

        # Initial spawn for current phase
        spawned = self._spawn.spawn_for_phase(
            self._orch.state.current_phase, self._orch,
        )
        if spawned:
            print(f"[conductor] Spawned: {', '.join(spawned)}", file=sys.stderr)

        self._last_health_check = time.monotonic()

        while self._running:
            # 1. Read exit journal for cross-process exit notifications
            exits = self._exit_notifier.read_new()
            for exit_info in exits:
                agent = exit_info.get("agent_name", "")
                print(f"[conductor] Agent exited: {agent}", file=sys.stderr)
                self._respawn.on_agent_exit(
                    agent_name=agent,
                    team_name=self._orch.team_name,
                    exit_info=exit_info,
                    spawn_strategy=self._spawn,
                )

            # 2. Try to advance phase
            new_phase = self._orch.advance()
            if new_phase:
                print(f"[conductor] Advanced to phase: {new_phase}", file=sys.stderr)
                if new_phase == "execute":
                    # Spawn executors first so task assignment can target real agent names.
                    spawned = self._spawn.spawn_for_phase(new_phase, self._orch)
                    if spawned:
                        print(f"[conductor] Spawned: {', '.join(spawned)}", file=sys.stderr)
                    self._prepare_execute(executor_names=spawned)
                else:
                    spawned = self._spawn.spawn_for_phase(new_phase, self._orch)
                    if spawned:
                        print(f"[conductor] Spawned: {', '.join(spawned)}", file=sys.stderr)

            # 3. Check if we're at the final phase
            phases = self._orch.state.phases
            if self._orch.state.current_phase == phases[-1]:
                print(f"[conductor] Harness complete (phase: {phases[-1]})", file=sys.stderr)
                self._running = False
                break

            # 4. Periodic health check
            now = time.monotonic()
            if now - self._last_health_check > self._health_interval:
                issues = self._health.check(self._orch.team_name)
                for issue in issues:
                    print(f"[conductor] Health issue: {issue}", file=sys.stderr)
                self._last_health_check = now

            time.sleep(self._poll_interval)

        print("[conductor] Stopped.", file=sys.stderr)

    def _prepare_execute(self, executor_names: list[str] | None = None) -> None:
        """Prepare the execute phase: load contracts, create tasks."""
        try:
            from clawteam.harness.contract_executor import ContractExecutor
            from clawteam.team.manager import TeamManager

            available_executors = list(executor_names or [])
            if not available_executors:
                team = TeamManager.get_team(self._orch.team_name)
                if team:
                    available_executors = [
                        member.name
                        for member in team.members
                        if member.agent_type == "executor"
                    ]

            executor = ContractExecutor(self._orch)
            tasks = executor.create_tasks_from_contracts(agent_names=available_executors)
            if tasks:
                print(f"[conductor] Created {len(tasks)} task(s) from contracts", file=sys.stderr)
        except Exception as e:
            print(f"[conductor] Warning: failed to create tasks: {e}", file=sys.stderr)
