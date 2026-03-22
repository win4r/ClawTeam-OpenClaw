from __future__ import annotations

from clawteam.spawn.prompt import build_agent_prompt


def test_build_agent_prompt_bootstrap_uses_shell_and_quotes_data_dir(monkeypatch):
    data_dir = "/tmp/clawteam data dir"
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", data_dir)

    prompt = build_agent_prompt(
        agent_name="qa one",
        agent_id="qa-1",
        agent_type="general-purpose",
        team_name="demo team",
        leader_name="leader",
        task="Run the regression",
    )

    expected_bootstrap = (
        "`eval $(CLAWTEAM_AGENT_NAME='qa one' CLAWTEAM_AGENT_ID=qa-1 "
        "CLAWTEAM_AGENT_TYPE=general-purpose CLAWTEAM_TEAM_NAME='demo team' "
        "CLAWTEAM_DATA_DIR='/tmp/clawteam data dir' clawteam identity set "
        "--agent-name 'qa one' --agent-id qa-1 --agent-type general-purpose "
        "--team 'demo team' --data-dir '/tmp/clawteam data dir' --shell)`"
    )

    assert expected_bootstrap in prompt
    assert "clawteam identity set" in prompt
    assert "--shell" in prompt
    assert "--data-dir '/tmp/clawteam data dir'" in prompt
    assert "Workflow topology belongs to the leader/template/state machine" in prompt
    assert "Do not use `task create`, `--add-blocked-by`, or `--add-on-fail`" in prompt
