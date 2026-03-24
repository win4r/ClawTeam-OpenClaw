"""Tests for spawn --task auto-creation of TaskItem."""

from unittest.mock import patch

from typer.testing import CliRunner

from clawteam.cli.commands import app
from clawteam.team.manager import TeamManager
from clawteam.team.models import TaskStatus
from clawteam.team.tasks import TaskStore


class DummyBackend:
    """Backend that always succeeds."""

    def spawn(self, **kwargs):
        return "Agent spawned"

    def list_running(self):
        return []


def test_spawn_with_task_creates_taskitem(monkeypatch, tmp_path):
    """When spawning with --task, a TaskItem should be created automatically."""
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    TeamManager.create_team(
        name="demo",
        leader_name="leader",
        leader_id="leader001",
    )
    monkeypatch.setattr("clawteam.spawn.get_backend", lambda _: DummyBackend())

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "spawn",
            "tmux",
            "openclaw",
            "--team",
            "demo",
            "--agent-name",
            "worker1",
            "--no-workspace",
            "--task",
            "Fix the bug in the login flow",
        ],
        env={"CLAWTEAM_DATA_DIR": str(tmp_path)},
    )

    assert result.exit_code == 0, result.output

    store = TaskStore("demo")
    tasks = store.list_tasks()

    task = next((t for t in tasks if t.owner == "worker1"), None)
    assert task is not None, "Task should be created for worker1"
    assert task.subject == "Fix the bug in the login flow"
    assert task.status == TaskStatus.in_progress
    assert task.description == "Fix the bug in the login flow"


def test_spawn_with_task_long_description_truncated_in_subject(monkeypatch, tmp_path):
    """Task subject should be truncated to 100 chars, but description keeps full text."""
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    TeamManager.create_team(
        name="demo",
        leader_name="leader",
        leader_id="leader001",
    )
    monkeypatch.setattr("clawteam.spawn.get_backend", lambda _: DummyBackend())

    long_task = "A" * 200

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "spawn",
            "tmux",
            "openclaw",
            "--team",
            "demo",
            "--agent-name",
            "worker1",
            "--no-workspace",
            "--task",
            long_task,
        ],
        env={"CLAWTEAM_DATA_DIR": str(tmp_path)},
    )

    assert result.exit_code == 0, result.output

    store = TaskStore("demo")
    tasks = store.list_tasks()

    task = next((t for t in tasks if t.owner == "worker1"), None)
    assert task is not None
    assert len(task.subject) == 100
    assert task.subject == "A" * 100
    assert task.description == long_task


def test_spawn_with_task_includes_task_id_in_prompt(monkeypatch, tmp_path):
    """When --task is provided, the prompt should include the task ID."""
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    TeamManager.create_team(
        name="demo",
        leader_name="leader",
        leader_id="leader001",
    )

    prompt_captured = {}

    class CaptureBackend:
        def spawn(self, **kwargs):
            prompt_captured["prompt"] = kwargs.get("prompt", "")
            return "Agent spawned"

        def list_running(self):
            return []

    monkeypatch.setattr("clawteam.spawn.get_backend", lambda _: CaptureBackend())

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "spawn",
            "tmux",
            "openclaw",
            "--team",
            "demo",
            "--agent-name",
            "worker1",
            "--no-workspace",
            "--task",
            "Do something",
        ],
        env={"CLAWTEAM_DATA_DIR": str(tmp_path)},
    )

    assert result.exit_code == 0, result.output
    assert "Task ID" in prompt_captured["prompt"]
    assert "worker1" in prompt_captured["prompt"]

    store = TaskStore("demo")
    tasks = store.list_tasks()
    task = next((t for t in tasks if t.owner == "worker1"), None)
    assert task is not None
    assert task.id in prompt_captured["prompt"]
