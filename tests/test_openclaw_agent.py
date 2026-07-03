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


def test_normalize_bare_openclaw_to_tui():
    """Bare `openclaw` must normalize to the resident TUI form, not the
    single-turn `agent --local` form (OpenClaw >= 2026.6 exits immediately
    without a session target)."""
    from clawteam.spawn.command_validation import normalize_spawn_command

    assert normalize_spawn_command(["openclaw"]) == ["openclaw", "tui"]
    # Explicit subcommands must pass through untouched.
    assert normalize_spawn_command(["openclaw", "tui"]) == ["openclaw", "tui"]
    assert normalize_spawn_command(["openclaw", "agent", "--local"]) == [
        "openclaw",
        "agent",
        "--local",
    ]


def test_tmux_backend_bare_openclaw_spawns_tui_with_session(monkeypatch):
    """Bare `openclaw` spawn must run `openclaw tui` with per-agent --session
    isolation and the task injected via --message."""
    from clawteam.spawn.tmux_backend import TmuxBackend

    captured: dict = {}
    _make_tmux_mocks(monkeypatch, captured)

    backend = TmuxBackend()
    backend.spawn(
        command=["openclaw"],
        agent_name="w1",
        agent_id="agent-tui",
        agent_type="general-purpose",
        team_name="reltest",
        prompt="do the thing",
        openclaw_agent=None,
    )

    spawn_cmd = captured.get("spawn_cmd", [])
    full_shell_cmd = spawn_cmd[-1] if spawn_cmd else ""
    openclaw_segment = next(
        (seg for seg in full_shell_cmd.split(";") if "openclaw" in seg and "lifecycle" not in seg),
        "",
    )
    assert " tui " in openclaw_segment or openclaw_segment.rstrip().endswith(" tui"), (
        f"Expected 'openclaw tui' form, got: {openclaw_segment!r}"
    )
    assert "--session clawteam-reltest-w1" in openclaw_segment, (
        f"Expected per-agent --session key, got: {openclaw_segment!r}"
    )
    assert "--message" in openclaw_segment, (
        f"Expected task injected via --message, got: {openclaw_segment!r}"
    )
    assert "agent --local" not in openclaw_segment, (
        f"Single-turn `agent --local` form must not be used: {openclaw_segment!r}"
    )


def test_tmux_backend_respawn_command_is_idempotent(monkeypatch):
    """respawn_agent re-runs the recorded final_command, which already carries
    --session/--message. The openclaw flag expansion must not append duplicates."""
    from clawteam.spawn.tmux_backend import TmuxBackend

    captured: dict = {}
    _make_tmux_mocks(monkeypatch, captured)

    backend = TmuxBackend()
    backend.spawn(
        command=[
            "openclaw", "tui",
            "--session", "clawteam-reltest-w1",
            "--message", "recorded prompt",
        ],
        agent_name="w1",
        agent_id="agent-r",
        agent_type="general-purpose",
        team_name="reltest",
        prompt=None,
        openclaw_agent=None,
    )

    spawn_cmd = captured.get("spawn_cmd", [])
    full_shell_cmd = spawn_cmd[-1] if spawn_cmd else ""
    assert full_shell_cmd.count("--session") == 1, (
        f"--session must not be duplicated on respawn, got: {full_shell_cmd!r}"
    )
    assert full_shell_cmd.count("--message") == 1, (
        f"--message must not be duplicated on respawn, got: {full_shell_cmd!r}"
    )


def test_kill_stale_same_name_windows_skips_own_window(monkeypatch):
    """Stale same-name windows are killed, but never the window the current
    process (the dying agent's trap handler) runs in."""
    from clawteam.spawn.tmux_backend import _kill_stale_same_name_windows

    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        result = MagicMock()
        result.returncode = 0
        if cmd[:2] == ["tmux", "list-windows"]:
            result.stdout = "@1 w3\n@2 w3\n@3 other\n"
        elif cmd[:2] == ["tmux", "display-message"]:
            result.stdout = "@1\n"
        else:
            result.stdout = ""
        return result

    monkeypatch.setattr("clawteam.spawn.tmux_backend.subprocess.run", fake_run)
    monkeypatch.setenv("TMUX_PANE", "%0")

    _kill_stale_same_name_windows("clawteam-reltest", "w3")

    killed = [c[-1] for c in calls if c[:2] == ["tmux", "kill-window"]]
    assert killed == ["@2"], f"Expected only stale @2 killed (own @1 kept, @3 other name), got: {killed}"


def test_inject_runtime_message_prefers_registry_target(monkeypatch):
    """inject must address the precise window id recorded at spawn time, not the
    ambiguous session:window_name form."""
    from clawteam.spawn.tmux_backend import TmuxBackend

    probed: list[str] = []

    def fake_run(cmd, **kwargs):
        result = MagicMock()
        result.returncode = 0
        if cmd[:2] == ["tmux", "list-panes"]:
            probed.append(cmd[cmd.index("-t") + 1])
            result.stdout = "%9\n"
        else:
            result.stdout = ""
        return result

    monkeypatch.setattr("clawteam.spawn.tmux_backend.shutil.which", lambda name: "/usr/bin/tmux")
    monkeypatch.setattr("clawteam.spawn.tmux_backend.subprocess.run", fake_run)
    monkeypatch.setattr(
        "clawteam.spawn.registry.get_agent_info",
        lambda team, agent: {"backend": "tmux", "tmux_target": "@7"},
    )
    monkeypatch.setattr(
        "clawteam.spawn.tmux_backend._inject_prompt_via_buffer", lambda *a, **kw: None
    )

    backend = TmuxBackend()
    envelope = MagicMock()
    envelope.source, envelope.channel, envelope.priority = "system", "direct", "medium"
    envelope.summary, envelope.evidence, envelope.recommended_next_action = "hi", [], None
    envelope.message_type = "manual"
    ok, status = backend.inject_runtime_message("reltest", "w3", envelope)

    assert ok, f"inject should succeed, got: {status}"
    assert probed == ["@7"], f"Expected probe against registry target @7, got: {probed}"


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
    # Env vars now live in a sourced temp file (upstream PR #154 — avoids the
    # ~16k tmux command-length limit), so we extract that path and check the
    # file contents instead of the inline shell string.
    import re
    m = re.search(r"\. (/[^\s;]+\.env\.sh)", full_shell_cmd)
    assert m, f"No env file source in {full_shell_cmd!r}"
    env_file_path = m.group(1)
    env_content = open(env_file_path).read()
    assert "OPENCLAW_WORKSPACE=" in env_content, (
        f"Expected OPENCLAW_WORKSPACE in env file, got: {env_content!r}"
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
