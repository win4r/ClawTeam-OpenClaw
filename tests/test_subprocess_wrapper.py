from __future__ import annotations

from clawteam.spawn import subprocess_wrapper


class Result:
    def __init__(self, returncode: int):
        self.returncode = returncode


def test_subprocess_wrapper_runs_command_and_invokes_lifecycle(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(command, check=False):
        calls.append(command)
        if len(calls) == 1:
            return Result(returncode=7)
        return Result(returncode=0)

    monkeypatch.setenv("CLAWTEAM_BIN", "clawteam")
    monkeypatch.setattr("clawteam.spawn.subprocess_wrapper.subprocess.run", fake_run)

    exit_code = subprocess_wrapper.main(
        ["--team", "demo-team", "--agent", "worker1", "--", "codex", "fix the bug"]
    )

    assert exit_code == 7
    assert calls == [
        ["codex", "fix the bug"],
        ["clawteam", "lifecycle", "on-exit", "--team", "demo-team", "--agent", "worker1"],
    ]


def test_subprocess_wrapper_returns_2_when_command_missing():
    assert subprocess_wrapper.main(["--team", "demo-team", "--agent", "worker1"]) == 2
