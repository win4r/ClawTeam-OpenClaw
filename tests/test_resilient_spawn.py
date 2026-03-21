"""Tests for resilient spawn: stagger delay, respawn backoff, and registry spawn info."""

from __future__ import annotations

import sys

from clawteam.spawn.subprocess_backend import SubprocessBackend
from clawteam.spawn.tmux_backend import TmuxBackend
from clawteam.team.waiter import TaskWaiter, respawn_backoff

# ---------------------------------------------------------------------------
# Respawn backoff calculation
# ---------------------------------------------------------------------------


def test_respawn_backoff_values():
    assert respawn_backoff(0) == 10.0
    assert respawn_backoff(1) == 30.0
    assert respawn_backoff(2) == 60.0
    assert respawn_backoff(3) == 120.0


def test_respawn_backoff_caps_at_max():
    assert respawn_backoff(10) == 120.0
    assert respawn_backoff(100) == 120.0


def test_respawn_backoff_custom_max():
    assert respawn_backoff(0, max_delay=5.0) == 5.0
    assert respawn_backoff(1, max_delay=20.0) == 20.0


# ---------------------------------------------------------------------------
# Registry stores and retrieves spawn info with new fields
# ---------------------------------------------------------------------------


def test_registry_stores_full_spawn_info(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    from clawteam.spawn.registry import get_registry, register_agent

    register_agent(
        team_name="test-team",
        agent_name="worker1",
        backend="tmux",
        tmux_target="clawteam-test:worker1",
        pid=12345,
        command=["openclaw"],
        spawn_cwd="/tmp/workspace",
        agent_id="abc123",
        agent_type="general-purpose",
        prompt="Do the work",
        skip_permissions=True,
        stagger_seconds=8.0,
    )

    registry = get_registry("test-team")
    info = registry["worker1"]
    assert info["backend"] == "tmux"
    assert info["command"] == ["openclaw"]
    assert info["spawn_cwd"] == "/tmp/workspace"
    assert info["agent_id"] == "abc123"
    assert info["agent_type"] == "general-purpose"
    assert info["prompt"] == "Do the work"
    assert info["skip_permissions"] is True
    assert info["stagger_seconds"] == 8.0


def test_registry_backward_compat_defaults(tmp_path, monkeypatch):
    """Calling register_agent with only old fields still works."""
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    from clawteam.spawn.registry import get_registry, register_agent

    register_agent(
        team_name="test-team",
        agent_name="worker2",
        backend="subprocess",
        pid=9999,
        command=["claude"],
    )

    registry = get_registry("test-team")
    info = registry["worker2"]
    assert info["spawn_cwd"] == ""
    assert info["agent_id"] == ""
    assert info["prompt"] == ""
    assert info["skip_permissions"] is False
    assert info["stagger_seconds"] == 0


# ---------------------------------------------------------------------------
# Stagger delay is applied in shell command (subprocess backend)
# ---------------------------------------------------------------------------


class DummyProcess:
    def __init__(self, pid: int = 4321):
        self.pid = pid

    def poll(self):
        return None


def test_subprocess_stagger_in_shell_command(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    clawteam_bin = tmp_path / "venv" / "bin" / "clawteam"
    clawteam_bin.parent.mkdir(parents=True)
    clawteam_bin.write_text("#!/bin/sh\n")
    monkeypatch.setattr(sys, "argv", [str(clawteam_bin)])

    captured: dict[str, object] = {}

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        return DummyProcess()

    monkeypatch.setattr(
        "clawteam.spawn.command_validation.shutil.which",
        lambda name, path=None: "/usr/bin/codex" if name == "codex" else None,
    )
    monkeypatch.setattr("clawteam.spawn.subprocess_backend.subprocess.Popen", fake_popen)
    monkeypatch.setattr("clawteam.spawn.registry.register_agent", lambda **_: None)

    backend = SubprocessBackend()
    backend.spawn(
        command=["codex"],
        agent_name="worker1",
        agent_id="agent-1",
        agent_type="general-purpose",
        team_name="demo-team",
        prompt="do work",
        cwd="/tmp/demo",
        skip_permissions=True,
        stagger_seconds=8,
    )

    cmd = captured["cmd"]
    assert "sleep $(python3 -c" in cmd
    assert "random.uniform(0, 8)" in cmd


def test_subprocess_no_stagger_by_default(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    clawteam_bin = tmp_path / "venv" / "bin" / "clawteam"
    clawteam_bin.parent.mkdir(parents=True)
    clawteam_bin.write_text("#!/bin/sh\n")
    monkeypatch.setattr(sys, "argv", [str(clawteam_bin)])

    captured: dict[str, object] = {}

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        return DummyProcess()

    monkeypatch.setattr(
        "clawteam.spawn.command_validation.shutil.which",
        lambda name, path=None: "/usr/bin/codex" if name == "codex" else None,
    )
    monkeypatch.setattr("clawteam.spawn.subprocess_backend.subprocess.Popen", fake_popen)
    monkeypatch.setattr("clawteam.spawn.registry.register_agent", lambda **_: None)

    backend = SubprocessBackend()
    backend.spawn(
        command=["codex"],
        agent_name="worker1",
        agent_id="agent-1",
        agent_type="general-purpose",
        team_name="demo-team",
        prompt="do work",
        cwd="/tmp/demo",
        skip_permissions=True,
    )

    cmd = captured["cmd"]
    assert "sleep" not in cmd


# ---------------------------------------------------------------------------
# Stagger delay is applied in shell command (tmux backend)
# ---------------------------------------------------------------------------


def test_tmux_stagger_in_shell_command(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    clawteam_bin = tmp_path / "venv" / "bin" / "clawteam"
    clawteam_bin.parent.mkdir(parents=True)
    clawteam_bin.write_text("#!/bin/sh\n")
    monkeypatch.setattr(sys, "argv", [str(clawteam_bin)])

    run_calls: list[list[str]] = []

    class Result:
        def __init__(self, returncode: int = 0, stdout: str = ""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = ""

    def fake_run(args, **kwargs):
        run_calls.append(args)
        if args[:3] == ["tmux", "has-session", "-t"]:
            return Result(returncode=1)
        if args[:3] == ["tmux", "list-panes", "-t"]:
            return Result(returncode=0, stdout="9876\n")
        return Result(returncode=0)

    original_which = __import__("shutil").which
    monkeypatch.setattr(
        "clawteam.spawn.tmux_backend.shutil.which",
        lambda name, path=None: (
            "/opt/homebrew/bin/tmux" if name == "tmux" else original_which(name)
        ),
    )
    monkeypatch.setattr(
        "clawteam.spawn.command_validation.shutil.which",
        lambda name, path=None: "/usr/bin/codex" if name == "codex" else original_which(name),
    )
    monkeypatch.setattr("clawteam.spawn.tmux_backend.subprocess.run", fake_run)
    monkeypatch.setattr("clawteam.spawn.tmux_backend.time.sleep", lambda *_: None)
    monkeypatch.setattr("clawteam.spawn.registry.register_agent", lambda **_: None)

    backend = TmuxBackend()
    backend.spawn(
        command=["codex"],
        agent_name="worker1",
        agent_id="agent-1",
        agent_type="general-purpose",
        team_name="demo-team",
        prompt="do work",
        cwd="/tmp/demo",
        skip_permissions=True,
        stagger_seconds=5,
    )

    new_session = next(call for call in run_calls if call[:3] == ["tmux", "new-session", "-d"])
    full_cmd = new_session[-1]
    assert "sleep $(python3 -c" in full_cmd
    assert "random.uniform(0, 5)" in full_cmd


# ---------------------------------------------------------------------------
# Waiter respawn logic
# ---------------------------------------------------------------------------


def test_waiter_respawn_increments_attempts(monkeypatch, tmp_path):
    """Verify that _respawn_agent increments attempt counter and calls spawn."""
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("clawteam.team.waiter.time.sleep", lambda _: None)

    # Set up registry with spawn info
    from clawteam.spawn.registry import register_agent

    register_agent(
        team_name="test-team",
        agent_name="worker1",
        backend="subprocess",
        pid=9999,
        command=["openclaw"],
        spawn_cwd="/tmp/ws",
        agent_id="abc",
        agent_type="general-purpose",
        prompt="do stuff",
        skip_permissions=True,
    )

    spawn_calls: list[dict] = []

    class FakeBackend:
        def spawn(self, **kwargs):
            spawn_calls.append(kwargs)
            return "Agent 'worker1' spawned as subprocess (pid=5555)"

    monkeypatch.setattr("clawteam.spawn.get_backend", lambda _: FakeBackend())

    from clawteam.team.mailbox import MailboxManager
    from clawteam.team.tasks import TaskStore

    task_store = TaskStore("test-team")
    mailbox = MailboxManager("test-team")

    waiter = TaskWaiter(
        team_name="test-team",
        agent_name="leader",
        mailbox=mailbox,
        task_store=task_store,
        max_respawn_attempts=3,
    )

    waiter._respawn_agent("worker1")

    assert waiter._respawn_attempts["worker1"] == 1
    assert len(spawn_calls) == 1
    assert spawn_calls[0]["command"] == ["openclaw"]
    assert spawn_calls[0]["agent_name"] == "worker1"


def test_waiter_respawn_stops_after_max_attempts(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("clawteam.team.waiter.time.sleep", lambda _: None)

    from clawteam.spawn.registry import register_agent

    register_agent(
        team_name="test-team",
        agent_name="worker1",
        backend="subprocess",
        pid=9999,
        command=["openclaw"],
    )

    spawn_calls: list[dict] = []

    class FakeBackend:
        def spawn(self, **kwargs):
            spawn_calls.append(kwargs)
            return "Agent 'worker1' spawned"

    monkeypatch.setattr("clawteam.spawn.get_backend", lambda _: FakeBackend())

    from clawteam.team.mailbox import MailboxManager
    from clawteam.team.tasks import TaskStore

    task_store = TaskStore("test-team")
    mailbox = MailboxManager("test-team")

    waiter = TaskWaiter(
        team_name="test-team",
        agent_name="leader",
        mailbox=mailbox,
        task_store=task_store,
        max_respawn_attempts=2,
    )

    # Exhaust attempts
    waiter._respawn_attempts["worker1"] = 2
    waiter._respawn_agent("worker1")

    # Should not have spawned
    assert len(spawn_calls) == 0
    assert waiter._respawn_attempts["worker1"] == 2


def test_waiter_respawn_clears_known_dead_on_success(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("clawteam.team.waiter.time.sleep", lambda _: None)

    from clawteam.spawn.registry import register_agent

    register_agent(
        team_name="test-team",
        agent_name="worker1",
        backend="tmux",
        pid=9999,
        command=["openclaw"],
    )

    class FakeBackend:
        def spawn(self, **kwargs):
            return "Agent 'worker1' spawned in tmux"

    monkeypatch.setattr("clawteam.spawn.get_backend", lambda _: FakeBackend())

    from clawteam.team.mailbox import MailboxManager
    from clawteam.team.tasks import TaskStore

    task_store = TaskStore("test-team")
    mailbox = MailboxManager("test-team")

    waiter = TaskWaiter(
        team_name="test-team",
        agent_name="leader",
        mailbox=mailbox,
        task_store=task_store,
    )
    waiter._known_dead.add("worker1")

    waiter._respawn_agent("worker1")

    # known_dead should be cleared so agent can be re-detected if it dies again
    assert "worker1" not in waiter._known_dead
