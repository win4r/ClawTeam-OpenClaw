"""Role-scoped context recovery for agent re-spawns."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from clawteam.harness.context import HarnessContext


class ContextRecovery:
    """Builds role-scoped recovery prompts for re-spawned agents.

    Each role gets only the context it needs:
    - Executor: own tasks + own contract + teammate one-liner summaries
    - Planner: own tasks + spec draft
    - Evaluator: all contracts + criteria + global status
    """

    def __init__(self, ctx: HarnessContext | None = None):
        self._ctx = ctx

    def build_recovery_prompt(
        self,
        agent_name: str,
        team_name: str,
        role: str = "",
        iteration: int = 1,
        max_iterations: int = 5,
    ) -> str:
        """Build a role-scoped recovery prompt with 5 layers of context."""
        sections: list[str] = []

        # Layer 1: Iteration context
        sections.append(f"## Resume Context — Iteration {iteration}/{max_iterations}")

        # Layer 2: Task progress (own tasks only for executors)
        sections.append(self._task_progress(agent_name, team_name, role))

        # Layer 3: Git summary (own work only)
        sections.append(self._git_summary(agent_name, team_name, role))

        # Layer 4: Artifact context (role-scoped)
        sections.append(self._artifact_context(agent_name, team_name, role))

        # Layer 5: Teammate status (one-liner summaries)
        sections.append(self._teammate_summary(agent_name, team_name, role))

        return "\n\n".join(s for s in sections if s)

    def _task_progress(self, agent_name: str, team_name: str, role: str) -> str:
        """Layer 2: Task progress scoped to the agent's role."""
        try:
            from clawteam.team.tasks import TaskStore
            store = TaskStore(team_name)
            if role in ("executor", "planner"):
                tasks = [t for t in store.list_tasks() if t.owner == agent_name]
            else:
                tasks = store.list_tasks()

            if not tasks:
                return ""

            status_icons = {
                "completed": "\u2705",
                "in_progress": "\U0001f504",
                "pending": "\u23f3",
                "blocked": "\U0001f6ab",
            }
            lines = ["### Your Tasks" if role != "evaluator" else "### All Tasks"]
            for t in tasks:
                icon = status_icons.get(t.status.value, "?")
                lines.append(f"- [{icon}] {t.subject} ({t.status.value})")
            return "\n".join(lines)
        except Exception:
            return ""

    def _git_summary(self, agent_name: str, team_name: str, role: str) -> str:
        """Layer 3: Git log summary (own commits only for executors)."""
        if role == "evaluator":
            return ""
        try:
            import subprocess
            result = subprocess.run(
                ["git", "log", "--oneline", "-5", f"--author={agent_name}"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                return f"### Your Previous Commits\n```\n{result.stdout.strip()}\n```"
        except Exception:
            pass
        return ""

    def _artifact_context(self, agent_name: str, team_name: str, role: str) -> str:
        """Layer 4: Artifact context scoped by role."""
        if not self._ctx or not self._ctx.artifacts:
            return ""
        try:
            if role == "executor":
                # Only show this executor's assigned contract
                artifacts = self._ctx.artifacts.list_artifacts()
                for art in artifacts:
                    name = art["name"]
                    if "sprint-contract" in name:
                        content = self._ctx.artifacts.read(name)
                        if content and agent_name in content:
                            return f"### Your Sprint Contract\n```json\n{content[:1000]}\n```"
                return ""
            elif role == "evaluator":
                # Show spec + all contract criteria
                spec = self._ctx.artifacts.read("spec.md")
                lines = []
                if spec:
                    lines.append(f"### Specification\n{spec[:2000]}")
                return "\n\n".join(lines) if lines else ""
            elif role == "planner":
                spec = self._ctx.artifacts.read("spec.md")
                if spec:
                    return f"### Your Spec Draft\n{spec[:2000]}"
        except Exception:
            pass
        return ""

    def _teammate_summary(self, agent_name: str, team_name: str, role: str) -> str:
        """Layer 5: One-liner teammate summaries."""
        try:
            from clawteam.team.models import TaskStatus
            from clawteam.team.tasks import TaskStore
            store = TaskStore(team_name)
            tasks = store.list_tasks()

            # Group by owner, exclude self
            owner_status: dict[str, tuple[int, int]] = {}
            for t in tasks:
                if t.owner and t.owner != agent_name:
                    done, total = owner_status.get(t.owner, (0, 0))
                    total += 1
                    if t.status == TaskStatus.completed:
                        done += 1
                    owner_status[t.owner] = (done, total)

            if not owner_status:
                return ""

            lines = ["### Team Status"]
            for owner, (done, total) in owner_status.items():
                lines.append(f"- {owner}: {done}/{total} tasks completed")

            # Check unread messages
            try:
                from clawteam.team.mailbox import MailboxManager
                mailbox = MailboxManager(team_name)
                count = mailbox.peek_count(agent_name)
                if count > 0:
                    lines.append(f"- {count} unread message(s) in your inbox")
            except Exception:
                pass

            return "\n".join(lines)
        except Exception:
            return ""
