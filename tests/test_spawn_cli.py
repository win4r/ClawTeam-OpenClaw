from __future__ import annotations

from typer.testing import CliRunner

from clawteam.cli.commands import app
from clawteam.team.manager import TeamManager


class ErrorBackend:
    def spawn(self, **kwargs):
        return (
            "Error: command 'nanobot' not found in PATH. "
            "Install the agent CLI first or pass an executable path."
        )

    def list_running(self):
        return []


def test_spawn_cli_exits_nonzero_and_rolls_back_failed_member(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    TeamManager.create_team(
        name="demo",
        leader_name="leader",
        leader_id="leader001",
    )
    monkeypatch.setattr("clawteam.spawn.get_backend", lambda _: ErrorBackend())

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["spawn", "tmux", "nanobot", "--team", "demo", "--agent-name", "alice", "--no-workspace"],
        env={"CLAWTEAM_DATA_DIR": str(tmp_path)},
    )

    assert result.exit_code == 1
    assert "Error: command 'nanobot' not found in PATH" in result.output
    assert [member.name for member in TeamManager.list_members("demo")] == ["leader"]
