from __future__ import annotations

import json
from unittest.mock import patch

from typer.testing import CliRunner

from clawteam.cli.commands import app
from clawteam.team.lifecycle import LifecycleManager
from clawteam.team.mailbox import MailboxManager
from clawteam.team.manager import TeamManager
from clawteam.team.models import TaskStatus
from clawteam.team.tasks import TaskStore


def _setup_team_with_locked_task(team_name: str = "demo") -> tuple[TaskStore, str]:
    TeamManager.create_team(name=team_name, leader_name="leader", leader_id="leader001")
    store = TaskStore(team_name)
    t = store.create("stale lock task", owner="dead-agent")

    # Acquire lock for dead-agent.
    with patch("clawteam.spawn.registry.get_registry", return_value={}), patch(
        "clawteam.spawn.registry.is_agent_alive", return_value=None
    ):
        store.update(t.id, status=TaskStatus.in_progress, caller="dead-agent")

    return store, t.id


def test_lifecycle_manager_sweep_releases_stale_locks_and_notifies_leader():
    store, tid = _setup_team_with_locked_task("team-sweep")

    mailbox = MailboxManager("team-sweep")
    lm = LifecycleManager("team-sweep", mailbox)

    with patch("clawteam.spawn.registry.is_agent_alive", return_value=False):
        result = lm.sweep_stale_locks()

    assert result["released"] == 1
    assert result["tasks"][0]["id"] == tid

    task = store.get(tid)
    assert task is not None
    assert task.status == TaskStatus.pending
    assert task.locked_by == ""
    assert "stale_lock_released" in task.metadata

    leader_msgs = mailbox.receive("leader", limit=20)
    assert any("Recovered 1 stale lock" in (m.content or "") for m in leader_msgs)


def test_lifecycle_sweep_cli_json_output():
    _setup_team_with_locked_task("team-sweep-cli")

    runner = CliRunner()
    with patch("clawteam.spawn.registry.is_agent_alive", return_value=False):
        result = runner.invoke(
            app,
            ["--json", "lifecycle", "sweep", "--team", "team-sweep-cli"],
        )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["released"] == 1
    assert payload["tasks"][0]["id"]
