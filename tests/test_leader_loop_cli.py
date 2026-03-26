from __future__ import annotations

import json

from typer.testing import CliRunner

from clawteam.cli.commands import app
from clawteam.team.manager import TeamManager


def test_lifecycle_leader_loop_once_json(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")

    class FakeLoop:
        def __init__(self, *args, **kwargs):
            pass

        def run_once(self):
            return {
                "team": "demo",
                "released_locks": [],
                "dead_agents": ["worker1"],
                "respawned": [{"agent": "worker1"}],
                "skipped": [],
                "failed": [],
            }

        def run_forever(self, interval_seconds=10.0):
            raise AssertionError("should not be called in --once mode")

    monkeypatch.setattr("clawteam.team.leader_loop.LeaderLoop", FakeLoop)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["--json", "lifecycle", "leader-loop", "--team", "demo", "--once"],
        env={"CLAWTEAM_DATA_DIR": str(tmp_path)},
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["team"] == "demo"
    assert payload["dead_agents"] == ["worker1"]
    assert payload["respawned"][0]["agent"] == "worker1"
