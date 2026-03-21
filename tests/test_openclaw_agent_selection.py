from __future__ import annotations

import sys

from clawteam.spawn.tmux_backend import TmuxBackend


class Result:
    def __init__(self, returncode: int = 0, stdout: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = ""


def test_tmux_backend_passes_configured_openclaw_agent(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("CLAWTEAM_OPENCLAW_AGENT", "data-analyst")
    clawteam_bin = tmp_path / "venv" / "bin" / "clawteam"
    clawteam_bin.parent.mkdir(parents=True)
    clawteam_bin.write_text("#!/bin/sh\n")
    monkeypatch.setattr(sys, "argv", [str(clawteam_bin)])

    run_calls: list[list[str]] = []

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
        lambda name, path=None: "/usr/bin/tmux" if name == "tmux" else original_which(name),
    )
    monkeypatch.setattr(
        "clawteam.spawn.command_validation.shutil.which",
        lambda name, path=None: "/usr/bin/openclaw" if name == "openclaw" else original_which(name),
    )
    monkeypatch.setattr("clawteam.spawn.tmux_backend.subprocess.run", fake_run)
    monkeypatch.setattr("clawteam.spawn.tmux_backend.time.sleep", lambda *_: None)
    monkeypatch.setattr("clawteam.spawn.registry.register_agent", lambda **_: None)

    backend = TmuxBackend()
    backend.spawn(
        command=["openclaw"],
        agent_name="worker1",
        agent_id="agent-1",
        agent_type="general-purpose",
        team_name="demo-team",
        prompt="do work",
        cwd="/tmp/demo",
        skip_permissions=False,
    )

    new_session = next(call for call in run_calls if call[:3] == ["tmux", "new-session", "-d"])
    full_cmd = new_session[-1]
    assert "openclaw agent --agent data-analyst --session-id clawteam-demo-team-worker1 --message 'do work'" in full_cmd
