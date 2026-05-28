"""Default SpawnStrategy: phase-role based agent spawning."""

from __future__ import annotations

import uuid
from typing import Any

from clawteam.harness.phases import PhaseState
from clawteam.harness.roles import DEFAULT_ROLES, EVALUATOR, EXECUTOR, PLANNER
from clawteam.harness.strategies import SpawnStrategy


class PhaseRoleSpawner(SpawnStrategy):
    """Spawn agents by looking up phase_roles mapping and role configs."""

    def __init__(self, cli: str = "claude", backend_name: str = "tmux"):
        self._cli = cli
        self._backend_name = backend_name

    def spawn_for_phase(self, phase: str, orchestrator: Any) -> list[str]:
        """Spawn agents appropriate for the given phase."""
        state: PhaseState = orchestrator.state
        role_name = state.phase_roles.get(phase, "")
        if not role_name:
            return []

        role_config = DEFAULT_ROLES.get(role_name)
        count = self._agent_count_for_role(role_name, state.agent_count)

        # Emit BeforeWorkerSpawn and check veto
        try:
            from clawteam.events.global_bus import get_event_bus
            from clawteam.events.types import BeforeWorkerSpawn
            event = BeforeWorkerSpawn(
                team_name=state.team_name,
                agent_name=f"{role_name}-pending",
                agent_type=role_name,
                command=[self._cli],
            )
            get_event_bus().emit(event)
            if event.veto:
                return []
        except Exception:
            pass

        spawned: list[str] = []
        for i in range(count):
            agent_name = f"{role_name}-{uuid.uuid4().hex[:6]}"
            agent_id = uuid.uuid4().hex[:12]

            prompt_addon = role_config.system_prompt_addon if role_config else ""

            # Use the existing spawn infrastructure
            try:
                from clawteam.config import load_config
                from clawteam.harness.prompts import build_harness_system_prompt
                from clawteam.spawn import get_backend
                from clawteam.team.manager import TeamManager

                cfg = load_config()

                # Register agent as team member
                if not TeamManager.team_exists(state.team_name):
                    TeamManager.create_team(
                        name=state.team_name,
                        leader_name="conductor",
                        leader_id="conductor",
                    )
                TeamManager.add_member(
                    state.team_name, agent_name,
                    agent_id=agent_id, agent_type=role_name,
                )

                # Build system prompt
                system_prompt = build_harness_system_prompt(state.team_name, agent_name)
                if prompt_addon:
                    system_prompt += f"\n\n{prompt_addon}"

                # Build task prompt
                task_prompt = self._build_task_prompt(phase, role_name, state)

                backend = get_backend(self._backend_name)
                result = backend.spawn(
                    command=[self._cli],
                    agent_name=agent_name,
                    agent_id=agent_id,
                    agent_type=role_name,
                    team_name=state.team_name,
                    prompt=task_prompt,
                    system_prompt=system_prompt,
                    skip_permissions=cfg.skip_permissions,
                    keepalive=True,
                )
                if not result.startswith("Error"):
                    spawned.append(agent_name)
            except Exception:
                pass

        return spawned

    def respawn(
        self,
        agent_name: str,
        team_name: str,
        resume: bool = True,
        extra_prompt: str = "",
    ) -> str:
        """Re-spawn an agent, optionally resuming its session."""
        try:
            from clawteam.config import load_config
            from clawteam.spawn import get_backend

            cfg = load_config()
            agent_id = uuid.uuid4().hex[:12]

            command = [self._cli]
            if resume:
                command = self._build_resume_command(self._cli)

            backend = get_backend(self._backend_name)
            result = backend.spawn(
                command=command,
                agent_name=agent_name,
                agent_id=agent_id,
                agent_type="respawned",
                team_name=team_name,
                prompt=extra_prompt or None,
                skip_permissions=cfg.skip_permissions,
                keepalive=True,
            )
            return result
        except Exception as e:
            return f"Error: {e}"

    def _agent_count_for_role(self, role: str, configured_count: int) -> int:
        if role in (PLANNER, EVALUATOR):
            return 1
        if role == EXECUTOR:
            return configured_count
        return 1

    def _build_task_prompt(self, phase: str, role: str, state: PhaseState) -> str:
        lines = [f"## Phase: {phase}", f"## Goal: {state.goal}"]
        if role == PLANNER:
            lines.append(
                "Produce a structured specification (spec.md) and sprint contracts "
                "(sprint-contract-NNN.json) as artifacts."
            )
        elif role == EXECUTOR:
            lines.append("Check your assigned tasks and implement them.")
        elif role == EVALUATOR:
            lines.append("Test the implementation against sprint contract success criteria.")
        return "\n".join(lines)

    def _build_resume_command(self, cli: str) -> list[str]:
        """Build CLI-specific resume command."""
        resume_map = {
            "claude": ["claude", "--continue"],
            "codex": ["codex", "resume", "--last"],
            "gemini": ["gemini", "--resume", "latest"],
            "kimi": ["kimi", "--continue"],
            "qwen": ["qwen", "--continue"],
            "opencode": ["opencode", "--continue"],
            "pi": ["pi", "--continue"],
            "nanobot": ["nanobot", "agent"],  # no native continue
        }
        return resume_map.get(cli, [cli])
