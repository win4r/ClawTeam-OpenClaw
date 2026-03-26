from clawteam.spawn.prompt import build_agent_prompt


def test_openclaw_prompt_mentions_allowlisted_absolute_clawteam_path():
    prompt = build_agent_prompt(
        agent_name="worker1",
        agent_id="agent-1",
        agent_type="general-purpose",
        team_name="demo-team",
        leader_name="leader",
        task="do work",
    )
    assert "$CLAWTEAM_BIN" in prompt
    assert "$CLAWTEAM_CMD" not in prompt
    assert "allowlist" in prompt.lower()
