from __future__ import annotations

from typer.testing import CliRunner

from clawteam.cli.commands import app
from clawteam.team.manager import TeamManager
from clawteam.team.tasks import TaskStore


class _FakeProc:
    def __init__(self, pid: int = 4242):
        self.pid = pid


def test_team_spawn_team_auto_loop_starts_background_process(monkeypatch):
    calls = []

    def _fake_popen(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return _FakeProc(9001)

    monkeypatch.setattr("clawteam.cli.commands.subprocess.Popen", _fake_popen)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "team",
            "spawn-team",
            "demo-auto-loop",
            "--auto-loop",
            "--loop-interval",
            "3",
        ],
    )

    assert result.exit_code == 0
    assert calls, "expected subprocess.Popen to be called"
    cmd, kwargs = calls[0]
    assert "lifecycle" in cmd and "leader-loop" in cmd
    assert "--team" in cmd and "demo-auto-loop" in cmd
    assert "--stop-when-done" in cmd
    assert kwargs.get("start_new_session") is True


def test_launch_no_autospawn_creates_team_and_tasks_without_spawn():
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "launch",
            "strategy-room",
            "--team-name",
            "demo-no-autospawn",
            "--no-autospawn",
        ],
    )

    assert result.exit_code == 0
    team = TeamManager.get_team("demo-no-autospawn")
    assert team is not None

    tasks = TaskStore("demo-no-autospawn").list_tasks()
    assert len(tasks) > 0
