"""Tests for clawteam.spawn.prompt — build_agent_prompt."""

from clawteam.spawn.prompt import build_agent_prompt


class TestBuildAgentPrompt:
    def test_basic_prompt_contains_identity(self):
        prompt = build_agent_prompt(
            agent_name="worker-1",
            agent_id="abc123",
            agent_type="coder",
            team_name="alpha",
            leader_name="leader",
            task="Implement feature X",
        )
        assert "worker-1" in prompt
        assert "abc123" in prompt
        assert "coder" in prompt
        assert "alpha" in prompt
        assert "leader" in prompt
        assert "Implement feature X" in prompt

    def test_prompt_contains_coordination_protocol(self):
        prompt = build_agent_prompt(
            agent_name="w", agent_id="id", agent_type="t",
            team_name="team", leader_name="lead", task="do stuff",
        )
        assert "clawteam task list" in prompt
        assert "clawteam task update" in prompt
        assert "clawteam inbox send" in prompt
        assert "clawteam cost report" in prompt
        assert "clawteam session save" in prompt

    def test_prompt_includes_user_when_provided(self):
        prompt = build_agent_prompt(
            agent_name="w", agent_id="id", agent_type="t",
            team_name="team", leader_name="lead", task="task",
            user="alice",
        )
        assert "alice" in prompt

    def test_prompt_excludes_user_when_empty(self):
        prompt = build_agent_prompt(
            agent_name="w", agent_id="id", agent_type="t",
            team_name="team", leader_name="lead", task="task",
            user="",
        )
        assert "User:" not in prompt

    def test_prompt_includes_workspace_when_provided(self):
        prompt = build_agent_prompt(
            agent_name="w", agent_id="id", agent_type="t",
            team_name="team", leader_name="lead", task="task",
            workspace_dir="/tmp/ws", workspace_branch="feature-x",
        )
        assert "/tmp/ws" in prompt
        assert "feature-x" in prompt
        assert "Workspace" in prompt
        assert "isolated git worktree" in prompt

    def test_prompt_excludes_workspace_when_empty(self):
        prompt = build_agent_prompt(
            agent_name="w", agent_id="id", agent_type="t",
            team_name="team", leader_name="lead", task="task",
            workspace_dir="",
        )
        assert "Workspace" not in prompt

    def test_prompt_uses_team_and_leader_in_commands(self):
        prompt = build_agent_prompt(
            agent_name="dev", agent_id="id", agent_type="t",
            team_name="my-team", leader_name="boss", task="task",
        )
        assert "clawteam task list my-team --owner dev" in prompt
        assert "clawteam inbox send my-team boss" in prompt
        assert "clawteam cost report my-team" in prompt

    # --- Intent-based prompt (Auftragstaktik) ---

    def test_mission_section_with_intent(self):
        prompt = build_agent_prompt(
            agent_name="w", agent_id="id", agent_type="t",
            team_name="team", leader_name="lead", task="task",
            intent="Analyze AAPL for value investing",
        )
        assert "## Mission" in prompt
        assert "**Intent:** Analyze AAPL" in prompt

    def test_mission_with_end_state_and_constraints(self):
        prompt = build_agent_prompt(
            agent_name="w", agent_id="id", agent_type="t",
            team_name="team", leader_name="lead", task="task",
            end_state="Buy/sell/hold recommendation",
            constraints=["No leverage", "Max 10%"],
        )
        assert "**End State:**" in prompt
        assert "**Constraints:**" in prompt
        assert "- No leverage" in prompt

    def test_no_mission_when_no_intent_fields(self):
        prompt = build_agent_prompt(
            agent_name="w", agent_id="id", agent_type="t",
            team_name="team", leader_name="lead", task="task",
        )
        assert "## Mission" not in prompt

    def test_mission_before_task(self):
        prompt = build_agent_prompt(
            agent_name="w", agent_id="id", agent_type="t",
            team_name="team", leader_name="lead", task="do stuff",
            intent="Test ordering",
        )
        assert prompt.index("## Mission") < prompt.index("## Task")

    # --- Boids coordination rules ---

    def test_boids_rules_for_multi_agent(self):
        prompt = build_agent_prompt(
            agent_name="w", agent_id="id", agent_type="t",
            team_name="team", leader_name="lead", task="task",
            team_size=3,
        )
        assert "## Coordination Rules" in prompt
        assert "**Separation**" in prompt
        assert "**Alignment**" in prompt
        assert "**Cohesion**" in prompt
        assert "**Boundary**" in prompt

    def test_no_boids_for_single_agent(self):
        prompt = build_agent_prompt(
            agent_name="w", agent_id="id", agent_type="t",
            team_name="team", leader_name="lead", task="task",
            team_size=1,
        )
        assert "## Coordination Rules" not in prompt

    def test_no_boids_by_default(self):
        prompt = build_agent_prompt(
            agent_name="w", agent_id="id", agent_type="t",
            team_name="team", leader_name="lead", task="task",
        )
        assert "## Coordination Rules" not in prompt

    def test_boids_before_task(self):
        prompt = build_agent_prompt(
            agent_name="w", agent_id="id", agent_type="t",
            team_name="team", leader_name="lead", task="task",
            team_size=2,
        )
        assert prompt.index("## Coordination Rules") < prompt.index("## Task")

    # --- Metacognitive self-evaluation ---

    def test_metacognition_block_present(self):
        prompt = build_agent_prompt(
            agent_name="w", agent_id="id", agent_type="t",
            team_name="team", leader_name="lead", task="task",
        )
        assert "## Self-Evaluation" in prompt
        assert "[confidence: 0.X]" in prompt
        assert "confidence < 0.6" in prompt

    def test_metacognition_after_coordination(self):
        prompt = build_agent_prompt(
            agent_name="w", agent_id="id", agent_type="t",
            team_name="team", leader_name="lead", task="task",
        )
        assert prompt.index("## Coordination Protocol") < prompt.index("## Self-Evaluation")
