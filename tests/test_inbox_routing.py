from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from clawteam.board.collector import BoardCollector
from clawteam.cli.commands import app
from clawteam.team.lifecycle import LifecycleManager
from clawteam.team.mailbox import MailboxManager
from clawteam.team.manager import TeamManager


def test_lifecycle_idle_routes_to_prefixed_leader_inbox(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    TeamManager.create_team(
        name="demo",
        leader_name="leader",
        leader_id="leader001",
        user="alice",
    )

    mailbox = MailboxManager("demo")
    LifecycleManager("demo", mailbox).send_idle(
        agent_name="worker",
        agent_id="worker001",
        leader_name="leader",
        last_task="task-1",
        task_status="blocked",
    )

    leader_inbox = tmp_path / "teams" / "demo" / "inboxes" / "alice_leader"
    assert len(list(leader_inbox.glob("msg-*.json"))) == 1
    assert not (tmp_path / "teams" / "demo" / "inboxes" / "leader").exists()

    board = BoardCollector().collect_team("demo")
    assert board["members"][0]["inboxCount"] == 1


def test_inbox_peek_defaults_to_resolved_member_inbox(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    TeamManager.create_team(
        name="demo",
        leader_name="leader",
        leader_id="leader001",
        user="alice",
    )
    MailboxManager("demo").send(
        from_agent="worker",
        to="leader",
        content="hello",
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["inbox", "peek", "demo"],
        env={
            "CLAWTEAM_DATA_DIR": str(tmp_path),
            "CLAWTEAM_USER": "alice",
            "CLAWTEAM_AGENT_ID": "leader001",
            "CLAWTEAM_AGENT_NAME": "leader",
            "CLAWTEAM_AGENT_TYPE": "leader",
            "CLAWTEAM_TEAM_NAME": "demo",
            "CLAWTEAM_AGENT_LEADER": "1",
        },
    )

    assert result.exit_code == 0
    assert "Pending messages: 1" in result.output
    assert "from=worker" in result.output
