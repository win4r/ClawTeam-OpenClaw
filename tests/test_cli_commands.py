"""CLI command tests — runtime injection and lifecycle (cherry-picked from upstream #85)."""

from __future__ import annotations

from typer.testing import CliRunner

from clawteam.cli.commands import app
from clawteam.team.manager import TeamManager
from clawteam.team.routing_policy import DefaultRoutingPolicy, RuntimeEnvelope


def test_runtime_inject_cli_invokes_tmux_backend(monkeypatch, tmp_path):
    runner = CliRunner()
    env = {
        "HOME": str(tmp_path),
        "CLAWTEAM_DATA_DIR": str(tmp_path / ".clawteam"),
    }
    captured = {}

    def fake_inject(self, team, agent_name, envelope):
        captured["team"] = team
        captured["agent"] = agent_name
        captured["envelope"] = envelope
        return True, "ok"

    monkeypatch.setattr("clawteam.spawn.tmux_backend.TmuxBackend.inject_runtime_message", fake_inject)

    result = runner.invoke(
        app,
        [
            "runtime",
            "inject",
            "demo",
            "worker",
            "--source",
            "leader",
            "--summary",
            "Auth module complete.",
            "--evidence",
            "12 tests passed",
            "--recommended-next-action",
            "Begin integration task T5.",
        ],
        env=env,
    )

    assert result.exit_code == 0
    assert captured["team"] == "demo"
    assert captured["agent"] == "worker"
    assert captured["envelope"].summary == "Auth module complete."
    assert captured["envelope"].evidence == ["12 tests passed"]
    assert captured["envelope"].recommended_next_action == "Begin integration task T5."


def test_runtime_state_cli_reports_pending_routes(tmp_path):
    runner = CliRunner()
    env = {
        "HOME": str(tmp_path),
        "CLAWTEAM_DATA_DIR": str(tmp_path / ".clawteam"),
    }
    policy = DefaultRoutingPolicy(team_name="demo", throttle_seconds=30)
    first = RuntimeEnvelope(source="leader", target="worker", summary="Initial update")
    first_decision = policy.decide(first)
    policy.record_dispatch_result(first_decision, success=True)
    policy.decide(RuntimeEnvelope(source="leader", target="worker", summary="Second update"))

    result = runner.invoke(app, ["runtime", "state", "demo"], env=env)

    assert result.exit_code == 0
    assert "leader -> worker" in result.output
    assert "pending=1" in result.output


def test_lifecycle_check_zombies_reports_clean_state(monkeypatch, tmp_path):
    runner = CliRunner()
    env = {
        "HOME": str(tmp_path),
        "CLAWTEAM_DATA_DIR": str(tmp_path / ".clawteam"),
    }

    monkeypatch.setattr("clawteam.spawn.registry.list_zombie_agents", lambda team, max_hours=2.0: [])

    result = runner.invoke(app, ["lifecycle", "check-zombies", "--team", "demo"], env=env)

    assert result.exit_code == 0
    assert "No zombie agents detected" in result.output


def test_runtime_watch_cli_uses_runtime_router(monkeypatch, tmp_path):
    runner = CliRunner()
    env = {
        "HOME": str(tmp_path),
        "CLAWTEAM_DATA_DIR": str(tmp_path / ".clawteam"),
        "CLAWTEAM_USER": "alice",
        "CLAWTEAM_AGENT_ID": "worker001",
        "CLAWTEAM_AGENT_NAME": "worker",
    }
    TeamManager.create_team(
        name="demo",
        leader_name="worker",
        leader_id="worker001",
        user="alice",
    )
    captured = {}

    def fake_watch(self):
        captured["agent"] = self.agent_name
        captured["runtime_router"] = self.runtime_router

    monkeypatch.setattr("clawteam.team.watcher.InboxWatcher.watch", fake_watch)

    result = runner.invoke(app, ["runtime", "watch", "demo"], env=env)

    assert result.exit_code == 0
    assert captured["agent"] == "alice_worker"
    assert captured["runtime_router"] is not None
    assert captured["runtime_router"].agent_name == "worker"
