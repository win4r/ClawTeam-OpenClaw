from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from clawteam.cli.commands import app
from clawteam.identity import AgentIdentity
from clawteam.spawn.registry import register_agent
from clawteam.team.mailbox import MailboxManager
from clawteam.team.manager import TeamManager


SESSION_KEY = "clawteam-demo-qa1"


def _register_runtime_worker(monkeypatch, tmp_path: Path) -> Path:
    home = tmp_path / "home"
    data_dir = tmp_path / "isolated-data"
    home.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(data_dir))
    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    TeamManager.add_member("demo", "qa1", "qa1-id", agent_type="general-purpose")
    register_agent(
        team_name="demo",
        agent_name="qa1",
        backend="subprocess",
        pid=123,
        command=["openclaw", "tui"],
        session_key=SESSION_KEY,
        agent_id="qa1-id",
        agent_type="general-purpose",
        data_dir=str(data_dir),
    )
    return data_dir


def test_agent_identity_from_session_registry_includes_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    data_dir = _register_runtime_worker(monkeypatch, tmp_path)
    monkeypatch.delenv("CLAWTEAM_AGENT_NAME", raising=False)
    monkeypatch.delenv("CLAWTEAM_TEAM_NAME", raising=False)
    monkeypatch.delenv("CLAWTEAM_AGENT_ID", raising=False)
    monkeypatch.delenv("CLAWTEAM_AGENT_TYPE", raising=False)
    monkeypatch.delenv("CLAWTEAM_DATA_DIR", raising=False)
    monkeypatch.setattr("clawteam.identity._session_key_from_process_tree", lambda: SESSION_KEY)

    identity = AgentIdentity.from_env()

    assert identity.agent_name == "qa1"
    assert identity.team_name == "demo"
    assert identity.agent_id == "qa1-id"
    assert Path(identity.data_dir) == data_dir.resolve()


def test_inbox_receive_resolves_data_dir_from_session_registry(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    data_dir = _register_runtime_worker(monkeypatch, tmp_path)
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(data_dir))
    MailboxManager("demo").send(from_agent="leader", to="qa1", content="wake up")
    monkeypatch.delenv("CLAWTEAM_DATA_DIR", raising=False)
    monkeypatch.delenv("CLAWTEAM_AGENT_NAME", raising=False)
    monkeypatch.delenv("CLAWTEAM_TEAM_NAME", raising=False)
    monkeypatch.delenv("CLAWTEAM_AGENT_ID", raising=False)
    monkeypatch.delenv("CLAWTEAM_AGENT_TYPE", raising=False)
    monkeypatch.setattr("clawteam.identity._session_key_from_process_tree", lambda: SESSION_KEY)

    runner = CliRunner()
    result = runner.invoke(app, ["inbox", "receive", "demo", "--agent", "qa1"], env={"HOME": str(tmp_path / "home")})

    assert result.exit_code == 0, result.output
    assert "wake up" in result.output


def test_inbox_receive_fails_closed_when_session_has_no_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    _register_runtime_worker(monkeypatch, tmp_path)
    monkeypatch.delenv("CLAWTEAM_DATA_DIR", raising=False)
    monkeypatch.delenv("CLAWTEAM_AGENT_NAME", raising=False)
    monkeypatch.delenv("CLAWTEAM_TEAM_NAME", raising=False)
    monkeypatch.delenv("CLAWTEAM_AGENT_ID", raising=False)
    monkeypatch.delenv("CLAWTEAM_AGENT_TYPE", raising=False)
    monkeypatch.setattr(
        "clawteam.identity.runtime_session_record",
        lambda: {
            "team_name": "demo",
            "agent_name": "qa1",
            "agent_id": "qa1-id",
            "agent_type": "general-purpose",
            "data_dir": "",
        },
    )

    runner = CliRunner()
    result = runner.invoke(app, ["inbox", "receive", "demo", "--agent", "qa1"], env={"HOME": str(tmp_path / "home")})

    assert result.exit_code == 1
    assert "Missing ClawTeam data_dir" in result.output
