from __future__ import annotations

from typer.testing import CliRunner

from clawteam.cli.commands import app
from clawteam.team.manager import TeamManager
from clawteam.templates import AgentDef, TemplateDef


class ErrorBackend:
    def spawn(self, **kwargs):
        return (
            "Error: command 'nanobot' not found in PATH. "
            "Install the agent CLI first or pass an executable path."
        )

    def list_running(self):
        return []


class RecordingBackend:
    def __init__(self, calls):
        self.calls = calls

    def spawn(self, **kwargs):
        self.calls.append(kwargs)
        return "Agent 'alice' spawned"

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


def test_spawn_cli_treats_unknown_backend_token_as_command(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLAWTEAM_DEFAULT_BACKEND", "subprocess")
    TeamManager.create_team(
        name="demo",
        leader_name="leader",
        leader_id="leader001",
    )

    calls = []
    selected_backends = []

    def fake_get_backend(backend):
        selected_backends.append(backend)
        return RecordingBackend(calls)

    monkeypatch.setattr("clawteam.spawn.get_backend", fake_get_backend)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["spawn", "codex", "--team", "demo", "--agent-name", "alice", "--no-workspace"],
        env={
            "CLAWTEAM_DATA_DIR": str(tmp_path),
            "CLAWTEAM_DEFAULT_BACKEND": "subprocess",
        },
    )

    assert result.exit_code == 0
    assert len(calls) == 1
    assert selected_backends == ["subprocess"]
    assert calls[0]["command"] == ["codex"]


def test_launch_cli_normalizes_tmux_template_backend_on_windows(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("clawteam.spawn.is_windows", lambda: True)
    monkeypatch.setattr("clawteam.platform_compat.is_windows", lambda: True)

    template = TemplateDef(
        name="demo-template",
        description="demo",
        command=["openclaw"],
        backend="tmux",
        leader=AgentDef(name="leader", type="leader", task="lead"),
        agents=[],
        tasks=[],
    )

    calls = []
    selected_backends = []

    def fake_get_backend(backend):
        selected_backends.append(backend)
        return RecordingBackend(calls)

    monkeypatch.setattr("clawteam.templates.load_template", lambda _name: template)
    monkeypatch.setattr("clawteam.spawn.get_backend", fake_get_backend)
    monkeypatch.setattr("clawteam.spawn.prompt.build_agent_prompt", lambda **_kwargs: "prompt")

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["launch", "demo-template"],
        env={"CLAWTEAM_DATA_DIR": str(tmp_path)},
    )

    assert result.exit_code == 0
    assert selected_backends == ["subprocess"]
    assert len(calls) == 1
