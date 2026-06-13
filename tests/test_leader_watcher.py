from __future__ import annotations

import time
from pathlib import Path

from clawteam.team.leader_watcher import LeaderWatcher
from clawteam.team.manager import TeamManager
from clawteam.team.models import TaskStatus
from clawteam.team.tasks import TaskStore


class FakeBackend:
    def __init__(self):
        self.injected = []

    def inject_runtime_message(self, team, agent_name, envelope):
        self.injected.append((team, agent_name, envelope))
        return True, "injected"


def _create_team(tmp_path: Path, monkeypatch, team_name: str = "demo") -> None:
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    TeamManager.create_team(team_name, leader_name="leader", leader_id="leader-id")
    TeamManager.add_member(team_name, "worker1", agent_id="worker-id")


def test_leader_watcher_injects_startup_and_dedupes(monkeypatch, tmp_path):
    _create_team(tmp_path, monkeypatch)
    backend = FakeBackend()
    monkeypatch.setattr("clawteam.spawn.get_backend", lambda _: backend)

    watcher = LeaderWatcher(
        "demo",
        "leader",
        redis_mode="off",
        heartbeat_interval=3600,
    )

    first = watcher.check_once(reason="startup")
    second = watcher.check_once(reason="poll")

    assert first.injected is True
    assert second.injected is False
    assert len(backend.injected) == 1
    assert "Scheduler check:" in backend.injected[0][2].summary


def test_leader_watcher_reinjects_on_task_completion(monkeypatch, tmp_path):
    _create_team(tmp_path, monkeypatch)
    backend = FakeBackend()
    monkeypatch.setattr("clawteam.spawn.get_backend", lambda _: backend)
    store = TaskStore("demo")
    task = store.create("Implement feature", owner="worker1")

    watcher = LeaderWatcher(
        "demo",
        "leader",
        redis_mode="off",
        heartbeat_interval=3600,
    )
    watcher.check_once(reason="startup")

    store.update(task.id, status=TaskStatus.completed, caller="worker1", force=True)
    result = watcher.check_once(reason="poll")

    assert result.injected is True
    assert len(backend.injected) == 2
    assert "worker1 finished 1 task(s)" in backend.injected[-1][2].summary


def test_leader_watcher_heartbeat_injects_without_state_change(monkeypatch, tmp_path):
    _create_team(tmp_path, monkeypatch)
    backend = FakeBackend()
    monkeypatch.setattr("clawteam.spawn.get_backend", lambda _: backend)

    watcher = LeaderWatcher(
        "demo",
        "leader",
        redis_mode="off",
        heartbeat_interval=1,
    )
    watcher.check_once(reason="startup")
    time.sleep(1.1)
    result = watcher.check_once(reason="poll")

    assert result.injected is True
    assert result.reason == "heartbeat"
    assert len(backend.injected) == 2


def test_redis_wakeup_off_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    from clawteam.team.redis_wakeup import resolve_wakeup

    resolved = resolve_wakeup("demo", "off")

    assert resolved.enabled is False
    assert resolved.reason == "disabled"


def test_leader_watcher_auto_nudges_permission_prompt(monkeypatch, tmp_path):
    _create_team(tmp_path, monkeypatch)
    backend = FakeBackend()
    monkeypatch.setattr("clawteam.spawn.get_backend", lambda _: backend)
    monkeypatch.setattr(
        "clawteam.spawn.registry.get_registry",
        lambda _team: {
            "leader": {"backend": "tmux", "tmux_target": "%1"},
            "worker1": {"backend": "tmux", "tmux_target": "%2"},
        },
    )

    watcher = LeaderWatcher("demo", "leader", redis_mode="off", heartbeat_interval=3600)
    monkeypatch.setattr(
        watcher,
        "_capture_pane_text",
        lambda target: "Do you want to proceed? 1. Yes 2. No" if target == "%2" else "",
    )

    result = watcher.check_once(reason="poll")

    auto = [env for _team, agent, env in backend.injected if agent == "worker1"]
    assert result.injected is True
    assert auto
    assert auto[0].message_type == "auto_nudge"
    assert auto[0].recommended_next_action == "yes, proceed"


def test_leader_watcher_stale_leader_nudge_waits_for_idle_pane(monkeypatch, tmp_path):
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace

    _create_team(tmp_path, monkeypatch)
    backend = FakeBackend()
    monkeypatch.setattr("clawteam.spawn.get_backend", lambda _: backend)
    monkeypatch.setattr(
        "clawteam.spawn.registry.get_registry",
        lambda _team: {"leader": {"backend": "tmux", "tmux_target": "%1"}},
    )
    monkeypatch.setattr(
        "clawteam.team.leader_watcher._read_heartbeat",
        lambda _team_dir, _agent: SimpleNamespace(
            last_turn_at=datetime.now(timezone.utc) - timedelta(seconds=240)
        ),
    )
    store = TaskStore("demo")
    store.create("Implement feature", owner="worker1")

    watcher = LeaderWatcher("demo", "leader", redis_mode="off", heartbeat_interval=3600)
    monkeypatch.setattr(watcher, "_capture_pane_text", lambda _target: "leader$ ")

    result = watcher.check_once(reason="poll")

    stale = [env for _team, agent, env in backend.injected if agent == "leader" and env.message_type == "stale_leader_nudge"]
    assert result.injected is True
    assert stale
    assert "stale" in stale[0].summary
