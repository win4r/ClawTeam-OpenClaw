from __future__ import annotations

from unittest.mock import patch

from clawteam.team.leader_loop import LeaderLoop, LeaderLoopConfig
from clawteam.team.mailbox import MailboxManager
from clawteam.team.manager import TeamManager
from clawteam.team.tasks import TaskStore
from clawteam.team.models import TaskStatus


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


def test_leader_loop_respects_max_parallel_agents_limit():
    TeamManager.create_team(name="team-loop-parallel", leader_name="leader", leader_id="leader001")
    TeamManager.add_member(team_name="team-loop-parallel", member_name="worker1", agent_id="worker001")
    TeamManager.add_member(team_name="team-loop-parallel", member_name="worker2", agent_id="worker002")

    store = TaskStore("team-loop-parallel")
    store.create(subject="task1", owner="worker1")
    task2 = store.create(subject="task2", owner="worker2")
    store.update(task2.id, status=TaskStatus.in_progress, caller="worker2", force=True)

    mailbox = MailboxManager("team-loop-parallel")
    fake_backend = _FakeBackend("Agent 'worker1' spawned as subprocess")

    loop = LeaderLoop(
        "team-loop-parallel",
        mailbox,
        config=LeaderLoopConfig(auto_respawn=True, respawn_backoff_seconds=0, max_respawns_per_agent=2, max_parallel_agents=1),
    )

    with patch("clawteam.team.leader_loop.list_dead_agents", return_value=["worker1"]), patch(
        "clawteam.team.leader_loop.get_registry",
        return_value={"worker1": {"backend": "subprocess", "command": ["openclaw"]}},
    ), patch("clawteam.team.leader_loop.get_backend", return_value=fake_backend):
        result = loop.run_once()

    assert len(result["respawned"]) == 0
    assert any(item["reason"] == "parallel_limit" for item in result["skipped"])
    assert len(fake_backend.calls) == 0


def test_leader_loop_run_forever_stops_when_done():
    TeamManager.create_team(name="team-loop-done", leader_name="leader", leader_id="leader001")
    TeamManager.add_member(team_name="team-loop-done", member_name="worker1", agent_id="worker001")
    store = TaskStore("team-loop-done")
    task = store.create(subject="done", owner="worker1")
    store.update(task.id, status=TaskStatus.completed, caller="worker1", force=True)

    mailbox = MailboxManager("team-loop-done")
    loop = LeaderLoop("team-loop-done", mailbox)

    with patch.object(loop, "run_once", return_value={}) as run_once:
        loop.run_forever(interval_seconds=0.01, stop_when_done=True)

    assert run_once.call_count == 1


def test_leader_loop_switching_backend_policy_resets_permanent_failure_and_uses_default_backend():
    _setup_team("team-loop-policy")
    mailbox = MailboxManager("team-loop-policy")
    fake_backend = _FakeBackend("Agent 'worker1' spawned as subprocess")

    loop = LeaderLoop(
        "team-loop-policy",
        mailbox,
        config=LeaderLoopConfig(auto_respawn=True, respawn_backoff_seconds=0, max_respawns_per_agent=2),
    )

    # Seed old state: worker is permanently failed under tmux policy.
    loop._save_state({
        "agents": {
            "worker1": {
                "attempts": 2,
                "last_attempt": 99.0,
                "permanent_failure": True,
                "last_error": "old",
                "backend_policy": "tmux",
            }
        }
    })

    def _fake_get_effective(key: str):
        if key == "default_backend":
            return "subprocess", "file"
        if key == "skip_permissions":
            return "true", "default"
        return "", "default"

    with patch("clawteam.team.leader_loop.list_dead_agents", return_value=["worker1"]), patch(
        "clawteam.team.leader_loop.get_registry",
        return_value={"worker1": {"backend": "tmux", "command": ["openclaw"]}},
    ), patch("clawteam.team.leader_loop.get_backend", return_value=fake_backend), patch(
        "clawteam.team.leader_loop.get_effective", side_effect=_fake_get_effective
    ), patch("clawteam.team.leader_loop.time.time", return_value=100.0):
        result = loop.run_once()

    assert len(result["respawned"]) == 1
    assert result["respawned"][0]["backend"] == "subprocess"
    assert len(fake_backend.calls) == 1

    state = loop._load_state()["agents"]["worker1"]
    assert state["permanent_failure"] is False
    assert state["attempts"] == 1
    assert state["backend_policy"] == "subprocess"
