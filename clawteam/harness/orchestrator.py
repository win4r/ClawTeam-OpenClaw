"""Harness orchestrator: coordinates plan-then-execute agent workflow."""

from __future__ import annotations

from pathlib import Path

from clawteam.harness.artifacts import ArtifactStore
from clawteam.harness.phases import (
    PLAN,
    VERIFY,
    AllTasksCompleteGate,
    ArtifactRequiredGate,
    HumanApprovalGate,
    PhaseRunner,
    PhaseState,
)
from clawteam.harness.roles import DEFAULT_ROLES
from clawteam.team.models import get_data_dir


class HarnessOrchestrator:
    """Orchestrates a plan-then-execute harness run."""

    def __init__(
        self,
        team_name: str,
        goal: str = "",
        cli: str = "claude",
        agent_count: int = 3,
        phases: list[str] | None = None,
        phase_roles: dict[str, str] | None = None,
        human_gates: list[str] | None = None,
    ) -> None:
        self.team_name = team_name
        self.goal = goal
        self.cli = cli
        self.agent_count = agent_count

        self.state = PhaseState(
            team_name=team_name,
            goal=goal,
            cli=cli,
            agent_count=agent_count,
        )
        if phases:
            self.state.phases = phases
        if phase_roles:
            self.state.phase_roles.update(phase_roles)

        self.runner = PhaseRunner(self.state)
        self.artifacts = ArtifactStore(
            self._harness_dir(), team_name, self.state.harness_id,
        )

        # Default gates
        self.runner.register_gate(PLAN, ArtifactRequiredGate(["spec.md"]))
        self.runner.register_gate(VERIFY, AllTasksCompleteGate())

        # Human approval gates
        for phase in (human_gates or [PLAN]):
            self.runner.register_gate(phase, HumanApprovalGate(phase))

    def _harness_dir(self) -> Path:
        return get_data_dir() / "harness"

    # ── Core operations ───────────────────────────────────────────────

    def start(self) -> str:
        """Start a new harness run. Returns harness_id."""
        self.runner.save(self._harness_dir())
        return self.state.harness_id

    def advance(self) -> str | None:
        """Try to advance to the next phase."""
        result = self.runner.advance()
        if result:
            self.runner.save(self._harness_dir())
        return result

    def status(self) -> dict:
        """Return current status."""
        can_advance, reason = self.runner.can_advance()
        return {
            "harness_id": self.state.harness_id,
            "team": self.team_name,
            "goal": self.state.goal,
            "phase": self.state.current_phase,
            "can_advance": can_advance,
            "gate_reason": reason,
            "artifacts": list(self.state.artifacts.keys()),
            "history": self.state.phase_history,
        }

    def register_artifact(self, name: str, path: str) -> None:
        """Register an artifact in the harness state."""
        self.state.artifacts[name] = path
        self.runner.save(self._harness_dir())

    def abort(self) -> None:
        """Abort the harness run."""
        self.state.phase_history.append({
            "phase": self.state.current_phase,
            "aborted_at": _now_iso(),
        })
        self.runner.save(self._harness_dir())

    # ── Role helpers ──────────────────────────────────────────────────

    def get_role_config(self, role: str):
        """Get the default RoleConfig for a given role."""
        return DEFAULT_ROLES.get(role)

    def get_role_for_phase(self, phase: str) -> str:
        """Get the role name for a given phase."""
        return self.state.phase_roles.get(phase, "")

    # ── Class methods for loading ─────────────────────────────────────

    @classmethod
    def load(cls, team_name: str, harness_id: str) -> HarnessOrchestrator | None:
        """Load an existing harness run."""
        base = get_data_dir() / "harness"
        state_path = base / team_name / harness_id / "state.json"
        if not state_path.is_file():
            return None
        runner = PhaseRunner.load(state_path)
        orch = cls.__new__(cls)
        orch.team_name = team_name
        orch.goal = runner.state.goal
        orch.cli = runner.state.cli
        orch.agent_count = runner.state.agent_count
        orch.state = runner.state
        orch.runner = runner
        orch.artifacts = ArtifactStore(base, team_name, harness_id)
        return orch

    @classmethod
    def find_latest(cls, team_name: str) -> HarnessOrchestrator | None:
        """Find the most recent harness run for a team."""
        base = get_data_dir() / "harness" / team_name
        if not base.is_dir():
            return None
        runs = sorted(base.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
        for run_dir in runs:
            state_path = run_dir / "state.json"
            if state_path.is_file():
                return cls.load(team_name, run_dir.name)
        return None


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
