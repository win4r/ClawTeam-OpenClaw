from __future__ import annotations

from unittest.mock import patch

from clawteam.team.leader_loop import LeaderLoop, LeaderLoopConfig
from clawteam.team.mailbox import MailboxManager
from clawteam.team.manager import TeamManager
from clawteam.team.tasks import TaskStore


class _FakeBackend:
    def __init__(self, message: str = "Agent spawned"):
        self.message = message
        self.calls = []

    def spawn(self, **kwargs):
        self.calls.append(kwargs)
        return self.message


def _setup_team(team: str = "demo"):
    TeamManager.create_team(name=team, leader_name="leader", leader_id="leader001")
    TeamManager.add_member(team_name=team, member_name="worker1", agent_id="worker001")
    store = TaskStore(team)
    task = store.create(subject="do task", owner="worker1")
    return store, task


def test_leader_loop_respawns_dead_agent_and_notifies_leader():
    store, task = _setup_team("team-loop")
    mailbox = MailboxManager("team-loop")
    fake_backend = _FakeBackend("Agent 'worker1' spawned as subprocess")

    loop = LeaderLoop(
        "team-loop",
        mailbox,
        config=LeaderLoopConfig(auto_respawn=True, respawn_backoff_seconds=0, max_respawns_per_agent=2),
    )

    with patch("clawteam.team.leader_loop.list_dead_agents", return_value=["worker1"]), patch(
        "clawteam.team.leader_loop.get_registry",
        return_value={"worker1": {"backend": "subprocess", "command": ["openclaw"]}},
    ), patch("clawteam.team.leader_loop.get_backend", return_value=fake_backend):
        result = loop.run_once()

    assert result["dead_agents"] == ["worker1"]
    assert len(result["respawned"]) == 1
    assert fake_backend.calls
    call = fake_backend.calls[0]
    assert call["agent_name"] == "worker1"
    assert call["team_name"] == "team-loop"
    assert task.id in (call.get("prompt") or "")

    msgs = mailbox.receive("leader", limit=20)
    assert any("Auto-respawned 'worker1'" in (m.content or "") for m in msgs)


def test_leader_loop_respects_backoff():
    _setup_team("team-loop-backoff")
    mailbox = MailboxManager("team-loop-backoff")
    fake_backend = _FakeBackend("ok")

    loop = LeaderLoop(
        "team-loop-backoff",
        mailbox,
        config=LeaderLoopConfig(auto_respawn=True, respawn_backoff_seconds=60, max_respawns_per_agent=2),
    )

    with patch("clawteam.team.leader_loop.list_dead_agents", return_value=["worker1"]), patch(
        "clawteam.team.leader_loop.get_registry",
        return_value={"worker1": {"backend": "subprocess", "command": ["openclaw"]}},
    ), patch("clawteam.team.leader_loop.get_backend", return_value=fake_backend), patch(
        "clawteam.team.leader_loop.time.time", return_value=100.0
    ):
        first = loop.run_once()
        second = loop.run_once()

    assert len(first["respawned"]) == 1
    assert len(second["respawned"]) == 0
    assert any(item["reason"] == "backoff" for item in second["skipped"])
    assert len(fake_backend.calls) == 1


def test_leader_loop_stops_after_retry_budget_exhausted():
    _setup_team("team-loop-budget")
    mailbox = MailboxManager("team-loop-budget")
    fake_backend = _FakeBackend("Error: command 'openclaw' not found in PATH")

    loop = LeaderLoop(
        "team-loop-budget",
        mailbox,
        config=LeaderLoopConfig(auto_respawn=True, respawn_backoff_seconds=0, max_respawns_per_agent=1),
    )

    with patch("clawteam.team.leader_loop.list_dead_agents", return_value=["worker1"]), patch(
        "clawteam.team.leader_loop.get_registry",
        return_value={"worker1": {"backend": "subprocess", "command": ["openclaw"]}},
    ), patch("clawteam.team.leader_loop.get_backend", return_value=fake_backend), patch(
        "clawteam.team.leader_loop.time.time", return_value=100.0
    ):
        first = loop.run_once()
        second = loop.run_once()

    assert len(first["failed"]) == 1
    assert any(item["reason"] in ("retry_exhausted", "permanent_failure") for item in second["skipped"])
    assert len(fake_backend.calls) == 1
