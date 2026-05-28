"""Ralph Loop plugin: re-spawn agents that exit before completing tasks.

Based on the Ralph technique (persistent iteration loops), adapted for
ClawTeam's multi-agent orchestration with role-scoped context recovery.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from clawteam.plugins.base import HarnessPlugin

if TYPE_CHECKING:
    from clawteam.harness.context import HarnessContext


class RalphLoopPlugin(HarnessPlugin):
    """Re-spawn agents that exit before completing their tasks.

    Uses HarnessContext to:
    - ctx.bus: subscribe to WorkerExit events
    - ctx.get_tasks(): check task completion status
    - ctx.spawner: re-spawn agents with resume + context recovery
    """

    name = "ralph-loop"
    version = "0.1.0"
    description = "Re-spawn agents that exit before completing their tasks"

    def __init__(self, max_iterations: int = 5):
        self.max_iterations = max_iterations
        self._iterations: dict[str, int] = {}
        self._ctx: HarnessContext | None = None

    def on_register(self, ctx: HarnessContext) -> None:
        from clawteam.events.types import WorkerExit
        self._ctx = ctx
        ctx.bus.subscribe(WorkerExit, self._on_exit, priority=-10)

    def _on_exit(self, event) -> None:
        """Handle WorkerExit: re-spawn if tasks are incomplete."""
        if self._ctx is None:
            return

        agent = event.agent_name
        team = event.team_name
        self._iterations[agent] = self._iterations.get(agent, 0) + 1

        # Check task completion
        tasks_store = self._ctx.get_tasks()
        if tasks_store is None:
            return

        try:
            tasks = tasks_store.list_tasks()
            agent_tasks = [t for t in tasks if t.owner == agent]
            if not agent_tasks:
                return  # No tasks assigned, nothing to re-spawn for

            all_done = all(t.status.value == "completed" for t in agent_tasks)
            if all_done:
                return  # All done

            if self._iterations[agent] > self.max_iterations:
                return  # Max iterations reached
        except Exception:
            return

        # Build recovery context
        recovery_prompt = self._build_context(agent, team)

        # Re-spawn via spawner
        if self._ctx.spawner:
            self._ctx.spawner.respawn(
                agent_name=agent,
                team_name=team,
                resume=True,
                extra_prompt=recovery_prompt,
            )

    def _build_context(self, agent: str, team: str) -> str:
        """Build role-scoped recovery prompt via ContextRecovery."""
        try:
            from clawteam.harness.context_recovery import ContextRecovery
            recovery = ContextRecovery(self._ctx)
            role = self._get_agent_role(agent, team)
            return recovery.build_recovery_prompt(
                agent_name=agent,
                team_name=team,
                role=role,
                iteration=self._iterations.get(agent, 1),
                max_iterations=self.max_iterations,
            )
        except Exception:
            # Minimal fallback
            iteration = self._iterations.get(agent, 1)
            return (
                f"## Resume — Iteration {iteration}/{self.max_iterations}\n"
                f"You have incomplete tasks. Continue working on them."
            )

    def _get_agent_role(self, agent: str, team: str) -> str:
        """Determine agent's role from team member data."""
        try:
            from clawteam.team.manager import TeamManager
            members = TeamManager.list_members(team)
            for m in members:
                if m.name == agent:
                    return m.agent_type
        except Exception:
            pass
        return "executor"
