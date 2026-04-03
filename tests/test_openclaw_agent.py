"""Tests for openclaw_agent parameter handling in spawn backends."""

from __future__ import annotations

from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# TmuxBackend tests
# ---------------------------------------------------------------------------

def _make_tmux_mocks(monkeypatch, captured: dict, *, tmux_ok: bool = True, agent_flag_supported: bool = True):
    """Patch tmux, shutil.which, register_agent, and time.sleep for TmuxBackend tests."""
    monkeypatch.setattr("clawteam.spawn.tmux_backend.shutil.which", lambda name: "/usr/bin/tmux" if name == "tmux" else None)
    monkeypatch.setattr("clawteam.spawn.command_validation.shutil.which", lambda name, path=None: f"/usr/bin/{name}")
    monkeypatch.setattr("clawteam.spawn.tmux_backend._openclaw_supports_agent_flag", lambda: agent_flag_supported)

    def fake_run(cmd, **kwargs):
        result = MagicMock()
        result.returncode = 0
        result.stdout = "pane-id\n" if "list-panes" in cmd else b""
        result.stderr = b""
        captured.setdefault("runs", []).append(cmd)
        if "new-session" in cmd or "new-window" in cmd:
            # Capture the full command string for assertion
            captured["spawn_cmd"] = cmd
        return result

    monkeypatch.setattr("clawteam.spawn.tmux_backend.subprocess.run", fake_run)
    monkeypatch.setattr("clawteam.spawn.tmux_backend.time.sleep", lambda _: None)
    monkeypatch.setattr("clawteam.spawn.registry.register_agent", lambda **_: None)
    monkeypatch.setattr("clawteam.spawn.tmux_backend._confirm_workspace_trust_if_prompted", lambda *a, **kw: False)


def test_tmux_backend_includes_agent_flag_when_openclaw_agent_set(monkeypatch, capsys):
    """tmux_backend.spawn() with openclaw_agent='researcher' should include --agent researcher in command."""
    from clawteam.spawn.tmux_backend import TmuxBackend

    captured: dict = {}
    _make_tmux_mocks(monkeypatch, captured, agent_flag_supported=True)

    backend = TmuxBackend()
    backend.spawn(
        command=["openclaw"],
        agent_name="researcher",
        agent_id="agent-1",
        agent_type="general-purpose",
        team_name="test-team",
        prompt="hello world",
        openclaw_agent="researcher",
    )

    # The spawn command (new-session or new-window) should contain --agent researcher
    spawn_cmd = captured.get("spawn_cmd", [])
    # The full shell command is the last element in the tmux new-session/new-window call
    full_shell_cmd = spawn_cmd[-1] if spawn_cmd else ""
    assert "--agent researcher" in full_shell_cmd, (
        f"Expected '--agent researcher' in final command, got: {full_shell_cmd!r}"
    )


def test_tmux_backend_excludes_agent_flag_when_not_set(monkeypatch):
    """tmux_backend.spawn() without openclaw_agent should not include --agent in the openclaw command."""
    from clawteam.spawn.tmux_backend import TmuxBackend

    captured: dict = {}
    _make_tmux_mocks(monkeypatch, captured)

    backend = TmuxBackend()
    backend.spawn(
        command=["openclaw"],
        agent_name="worker",
        agent_id="agent-2",
        agent_type="general-purpose",
        team_name="test-team",
        prompt="hello world",
        openclaw_agent=None,
    )

    spawn_cmd = captured.get("spawn_cmd", [])
    full_shell_cmd = spawn_cmd[-1] if spawn_cmd else ""
    # The exit hook always contains "--agent <name>" for lifecycle; we only want to
    # verify the openclaw command itself (before the ";") does not carry --agent.
    # Split on ";" to isolate the openclaw command portion.
    openclaw_part = full_shell_cmd.split(";")
    # Find the segment containing "openclaw tui" (the actual agent command)
    openclaw_cmd_segment = next(
        (seg for seg in openclaw_part if "openclaw" in seg and "lifecycle" not in seg), ""
    )
    assert "--agent" not in openclaw_cmd_segment, (
        f"Expected no '--agent' in openclaw command segment, got: {openclaw_cmd_segment!r}"
    )


def test_tmux_backend_drops_agent_flag_when_unsupported(monkeypatch, capsys):
    """When openclaw tui doesn't support --agent, the flag should be silently dropped."""
    from clawteam.spawn.tmux_backend import TmuxBackend

    captured: dict = {}
    _make_tmux_mocks(monkeypatch, captured, agent_flag_supported=False)

    backend = TmuxBackend()
    backend.spawn(
        command=["openclaw"],
        agent_name="researcher",
        agent_id="agent-1",
        agent_type="general-purpose",
        team_name="test-team",
        prompt="hello world",
        openclaw_agent="researcher",
    )

    spawn_cmd = captured.get("spawn_cmd", [])
    full_shell_cmd = spawn_cmd[-1] if spawn_cmd else ""
    # --agent should NOT appear in the openclaw command segment
    openclaw_part = full_shell_cmd.split(";")
    openclaw_cmd_segment = next(
        (seg for seg in openclaw_part if "openclaw" in seg and "lifecycle" not in seg), ""
    )
    assert "--agent" not in openclaw_cmd_segment, (
        f"Expected no '--agent' in openclaw command (unsupported), got: {openclaw_cmd_segment!r}"
    )

    # Warning about dropping the flag should be printed to stderr
    stderr_output = capsys.readouterr().err
    assert "does not support --agent" in stderr_output


def test_tmux_backend_sets_openclaw_workspace_env(monkeypatch):
    """Spawning openclaw should set OPENCLAW_WORKSPACE for workspace isolation."""
    from clawteam.spawn.tmux_backend import TmuxBackend

    captured: dict = {}
    _make_tmux_mocks(monkeypatch, captured)

    backend = TmuxBackend()
    backend.spawn(
        command=["openclaw"],
        agent_name="worker",
        agent_id="agent-2",
        agent_type="general-purpose",
        team_name="test-team",
        prompt="hello world",
    )

    spawn_cmd = captured.get("spawn_cmd", [])
    full_shell_cmd = spawn_cmd[-1] if spawn_cmd else ""
    assert "OPENCLAW_WORKSPACE=" in full_shell_cmd, (
        f"Expected OPENCLAW_WORKSPACE in exports, got: {full_shell_cmd!r}"
    )


# ---------------------------------------------------------------------------
# SubprocessBackend tests
# ---------------------------------------------------------------------------

def test_subprocess_backend_raises_with_openclaw_agent(monkeypatch):
    """subprocess_backend.spawn() with openclaw_agent should raise NotImplementedError."""
    import pytest

    from clawteam.spawn.subprocess_backend import SubprocessBackend

    backend = SubprocessBackend()
    with pytest.raises(NotImplementedError, match="subprocess backend"):
        backend.spawn(
            command=["codex"],
            agent_name="worker",
            agent_id="agent-3",
            agent_type="general-purpose",
            team_name="test-team",
            openclaw_agent="researcher",
        )
