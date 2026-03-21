from __future__ import annotations

import os
import subprocess
from pathlib import Path

from clawteam.spawn.subprocess_backend import SubprocessBackend
from clawteam.team.mailbox import MailboxManager
from clawteam.team.manager import TeamManager
from clawteam.team.tasks import TaskStore
from clawteam.worker_runtime import build_openclaw_agent_command, run_worker_iteration


class _Completed:
    def __init__(self, returncode=0, stdout="ok", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _seed_team(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))
    TeamManager.create_team("demo", "leader", "leader-1")
    TeamManager.add_member("demo", "qa1", "qa1-id")


def test_build_openclaw_agent_command_uses_headless_agent_mode():
    cmd = build_openclaw_agent_command(
        base_command=["openclaw"],
        session_key="clawteam-demo-qa1",
        prompt="hello",
        timeout_seconds=123,
    )
    assert cmd[:2] == ["openclaw", "agent"]
    assert "--session-id" in cmd
    assert "clawteam-demo-qa1" in cmd
    assert "--message" in cmd
    assert "hello" in cmd


def test_run_worker_iteration_claims_and_dispatches_openclaw(monkeypatch, tmp_path):
    _seed_team(tmp_path, monkeypatch)
    monkeypatch.setenv("CLAWTEAM_AGENT_NAME", "qa1")
    monkeypatch.setenv("CLAWTEAM_TEAM_NAME", "demo")
    monkeypatch.setenv("CLAWTEAM_AGENT_ID", "qa1-id")
    monkeypatch.setenv("CLAWTEAM_WORKSPACE_DIR", str(tmp_path / "ws"))

    mailbox = MailboxManager("demo")
    mailbox.send("leader", "qa1", "start now", key="task-wake:t1", last_task="t1")

    task = TaskStore("demo").create(subject="Fix thing", description="Real task", owner="qa1")

    called = {}

    def fake_run(command, cwd=None, env=None, capture_output=None, text=None):
        called["command"] = command
        called["cwd"] = cwd
        called["env"] = env
        return _Completed()

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = run_worker_iteration(team_name="demo", agent_name="qa1", base_command=["openclaw"])

    assert result["status"] == "dispatched"
    assert result["taskId"] == task.id
    assert result["messages"] == 1
    assert called["command"][:2] == ["openclaw", "agent"]
    assert "--session-id" in called["command"]
    assert f"clawteam-demo-qa1" in called["command"]

    updated = TaskStore("demo").get(task.id)
    assert updated is not None
    assert updated.status.value == "in_progress"
    assert updated.locked_by == "qa1"


def test_subprocess_backend_wraps_openclaw_in_worker_runtime(monkeypatch, tmp_path):
    _seed_team(tmp_path, monkeypatch)
    monkeypatch.setenv("CLAWTEAM_AGENT_NAME", "leader")
    monkeypatch.setenv("CLAWTEAM_TEAM_NAME", "demo")
    monkeypatch.setenv("CLAWTEAM_AGENT_ID", "leader-1")

    captured = {}

    class DummyProc:
        pid = 43210

        def poll(self):
            return None

    def fake_popen(shell_cmd, shell=None, env=None, stdout=None, stderr=None, cwd=None):
        captured["shell_cmd"] = shell_cmd
        captured["env"] = env
        captured["cwd"] = cwd
        return DummyProc()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)

    backend = SubprocessBackend()
    message = backend.spawn(
        command=["openclaw"],
        agent_name="qa1",
        agent_id="qa1-id",
        agent_type="general-purpose",
        team_name="demo",
        prompt="startup rules",
        cwd=str(tmp_path / "ws"),
    )

    assert "spawned as subprocess" in message
    assert "worker run demo --agent qa1 --command openclaw" in captured["shell_cmd"]
    assert "--startup-prompt-file" in captured["shell_cmd"]
