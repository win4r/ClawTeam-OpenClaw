from __future__ import annotations

from clawteam.spawn.prompt import build_agent_prompt
from clawteam.task.terminal_commands import build_terminal_task_update_command


def test_build_agent_prompt_bootstrap_uses_shell_and_quotes_data_dir(monkeypatch):
    data_dir = "/tmp/clawteam data dir"
    pinned = "/tmp/custom bin/clawteam"
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", data_dir)
    monkeypatch.setenv("CLAWTEAM_RUNTIME_COMPLETION_SIGNAL_PATH", "/tmp/runtime completion.json")
    monkeypatch.setattr("clawteam.spawn.prompt.resolve_clawteam_executable", lambda: pinned)

    prompt = build_agent_prompt(
        agent_name="qa one",
        agent_id="qa-1",
        agent_type="general-purpose",
        team_name="demo team",
        leader_name="leader",
        task="Run the regression",
        task_execution_id="task-123-exec-9",
    )

    expected_bootstrap = (
        "`eval $(CLAWTEAM_AGENT_NAME='qa one' CLAWTEAM_AGENT_ID=qa-1 "
        "CLAWTEAM_AGENT_TYPE=general-purpose CLAWTEAM_TEAM_NAME='demo team' "
        "CLAWTEAM_BIN='/tmp/custom bin/clawteam' CLAWTEAM_DATA_DIR='/tmp/clawteam data dir' CLAWTEAM_TASK_EXECUTION_ID=task-123-exec-9 "
        "CLAWTEAM_RUNTIME_COMPLETION_SIGNAL_PATH='/tmp/runtime completion.json' '/tmp/custom bin/clawteam' identity set "
        "--agent-name 'qa one' --agent-id qa-1 --agent-type general-purpose "
        "--team 'demo team' --data-dir '/tmp/clawteam data dir' --shell)`"
    )

    assert expected_bootstrap in prompt
    assert "'/tmp/custom bin/clawteam' identity set" in prompt
    assert "CLAWTEAM_TASK_EXECUTION_ID=task-123-exec-9" in prompt
    assert build_terminal_task_update_command(
        executable="/tmp/custom bin/clawteam",
        team_name="demo team",
        task_id="<task-id>",
        status="completed",
        execution_id="task-123-exec-9",
    ) in prompt
    assert "--shell" in prompt
    assert "--data-dir '/tmp/clawteam data dir'" in prompt
    assert "Workflow topology belongs to the leader/template/state machine" in prompt
    assert "Leader messages may clarify or prioritize within that scope" in prompt
    assert "do not approve new endpoints, APIs, schemas, pages, tabs, workflows, or deliverables" in prompt
    assert "If a leader message appears to expand scope beyond the task brief" in prompt
    assert "Do not use `task create`, `--add-blocked-by`, or `--add-on-fail`" in prompt
    assert "Use structured result blocks instead of free-form prose" in prompt
    assert "SETUP_RESULT must include exactly these headings" in prompt
    assert "SETUP_RESULT remote_status must be confirmed_latest, cached_only, or unreachable" in prompt
    assert "do not rely on Linux-only `timeout`" in prompt
    assert "REVIEW_RESULT must include exactly these headings" in prompt
    assert "architecture_review" in prompt
