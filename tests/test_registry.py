"""Tests for clawteam.spawn.registry — agent process registry and liveness."""

from clawteam.spawn.registry import (
    _load,
    _pid_alive,
    _save,
    get_registry,
    is_agent_alive,
    list_dead_agents,
    list_zombie_agents,
    register_agent,
)
from clawteam.team.manager import TeamManager


def _create_team(name: str) -> None:
    TeamManager.create_team(name=name, leader_name="leader", leader_id="lid")


class TestRegisterAgent:
    def test_register_creates_entry(self, team_name, isolated_data_dir):
        _create_team(team_name)
        register_agent(team_name, "worker-1", backend="tmux", tmux_target="ct:w1", pid=1234)

        registry = get_registry(team_name)
        assert "worker-1" in registry
        assert registry["worker-1"]["backend"] == "tmux"
        assert registry["worker-1"]["pid"] == 1234
        assert registry["worker-1"]["tmux_target"] == "ct:w1"
        assert "spawned_at" in registry["worker-1"]

    def test_register_overwrites_existing(self, team_name):
        _create_team(team_name)
        register_agent(team_name, "w1", backend="tmux", pid=100)
        register_agent(team_name, "w1", backend="subprocess", pid=200)

        registry = get_registry(team_name)
        assert registry["w1"]["backend"] == "subprocess"
        assert registry["w1"]["pid"] == 200

    def test_register_multiple_agents(self, team_name):
        _create_team(team_name)
        register_agent(team_name, "a1", backend="tmux", pid=1)
        register_agent(team_name, "a2", backend="subprocess", pid=2)

        registry = get_registry(team_name)
        assert len(registry) == 2


class TestGetRegistry:
    def test_empty_when_no_file(self, team_name):
        _create_team(team_name)
        assert get_registry(team_name) == {}

    def test_handles_corrupt_file(self, team_name, isolated_data_dir):
        _create_team(team_name)
        path = isolated_data_dir / "teams" / team_name / "spawn_registry.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("not json")
        assert get_registry(team_name) == {}


class TestPidAlive:
    def test_zero_pid_is_dead(self):
        assert _pid_alive(0) is False

    def test_negative_pid_is_dead(self):
        assert _pid_alive(-1) is False

    def test_current_process_is_alive(self):
        import os
        assert _pid_alive(os.getpid()) is True

    def test_nonexistent_pid_is_dead(self):
        assert _pid_alive(999999999) is False


class TestIsAgentAlive:
    def test_returns_none_when_no_registry(self, team_name):
        _create_team(team_name)
        assert is_agent_alive(team_name, "unknown") is None

    def test_subprocess_alive_with_current_pid(self, team_name):
        import os
        _create_team(team_name)
        register_agent(team_name, "self", backend="subprocess", pid=os.getpid())
        assert is_agent_alive(team_name, "self") is True

    def test_subprocess_dead_with_fake_pid(self, team_name):
        _create_team(team_name)
        register_agent(team_name, "ghost", backend="subprocess", pid=999999999)
        assert is_agent_alive(team_name, "ghost") is False

    def test_unknown_backend_returns_none(self, team_name):
        _create_team(team_name)
        register_agent(team_name, "x", backend="alien", pid=1)
        assert is_agent_alive(team_name, "x") is None


class TestListDeadAgents:
    def test_empty_registry(self, team_name):
        _create_team(team_name)
        assert list_dead_agents(team_name) == []

    def test_finds_dead_agent(self, team_name):
        _create_team(team_name)
        register_agent(team_name, "ghost", backend="subprocess", pid=999999999)
        dead = list_dead_agents(team_name)
        assert "ghost" in dead

    def test_excludes_alive_agent(self, team_name):
        import os
        _create_team(team_name)
        register_agent(team_name, "alive", backend="subprocess", pid=os.getpid())
        register_agent(team_name, "dead", backend="subprocess", pid=999999999)
        dead = list_dead_agents(team_name)
        assert "dead" in dead
        assert "alive" not in dead


class TestListZombieAgents:
    def test_skips_legacy_entries_without_spawned_at(self, team_name, isolated_data_dir, monkeypatch):
        import os

        _create_team(team_name)
        register_agent(team_name, "worker", backend="subprocess", pid=os.getpid())
        path = isolated_data_dir / "teams" / team_name / "spawn_registry.json"
        registry = _load(path)
        registry["worker"].pop("spawned_at", None)
        _save(path, registry)

        monkeypatch.setattr("clawteam.spawn.registry.is_agent_alive", lambda _team, _agent: True)

        assert list_zombie_agents(team_name, max_hours=2.0) == []

    def test_returns_only_long_running_alive_agents(self, team_name, isolated_data_dir, monkeypatch):
        _create_team(team_name)
        register_agent(team_name, "old-worker", backend="subprocess", pid=111)
        register_agent(team_name, "fresh-worker", backend="subprocess", pid=222)
        register_agent(team_name, "dead-worker", backend="subprocess", pid=333)

        path = isolated_data_dir / "teams" / team_name / "spawn_registry.json"
        registry = _load(path)
        registry["old-worker"]["spawned_at"] = 1
        registry["fresh-worker"]["spawned_at"] = 9_000
        registry["dead-worker"]["spawned_at"] = 1
        _save(path, registry)

        monkeypatch.setattr(
            "clawteam.spawn.registry.is_agent_alive",
            lambda _team, agent: {"old-worker": True, "fresh-worker": True, "dead-worker": False}[agent],
        )
        monkeypatch.setattr("clawteam.spawn.registry.time.time", lambda: 10_800)

        zombies = list_zombie_agents(team_name, max_hours=2.0)

        assert len(zombies) == 1
        assert zombies[0]["agent_name"] == "old-worker"
        assert zombies[0]["running_hours"] == 3.0


class TestLoadSave:
    def test_save_and_load_roundtrip(self, tmp_path):
        path = tmp_path / "reg.json"
        data = {"a": {"backend": "tmux", "pid": 1}}
        _save(path, data)
        assert _load(path) == data

    def test_load_missing_file(self, tmp_path):
        assert _load(tmp_path / "missing.json") == {}

    def test_load_corrupt_file(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{broken")
        assert _load(path) == {}

    def test_save_creates_parent_dirs(self, tmp_path):
        path = tmp_path / "deep" / "nested" / "reg.json"
        _save(path, {"x": 1})
        assert _load(path) == {"x": 1}
