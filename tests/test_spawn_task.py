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


def test_spawn_with_task_id_links_to_existing_task(monkeypatch, tmp_path):
    """--task-id binds to existing task, not create new task."""
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    TeamManager.create_team(
        name="demo",
        leader_name="leader",
        leader_id="leader001",
    )
    monkeypatch.setattr("clawteam.spawn.get_backend", lambda _: DummyBackend())

    store = TaskStore("demo")
    task_obj = store.create(subject="Test task", description="Test description", owner="worker1")

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
            "--task-id",
            task_obj.id,
        ],
        env={"CLAWTEAM_DATA_DIR": str(tmp_path)},
    )

    assert result.exit_code == 0, result.output

    tasks = store.list_tasks()
    task = next((t for t in tasks if t.id == task_obj.id), None)
    assert task is not None
    assert task.status == TaskStatus.in_progress
    assert task.locked_by == "worker1"

    all_tasks = store.list_tasks()
    assert len(all_tasks) == 1


def test_spawn_with_task_id_not_found(monkeypatch, tmp_path):
    """--task-id with non-existent task should error."""
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
            "--task-id",
            "nonexistent",
        ],
        env={"CLAWTEAM_DATA_DIR": str(tmp_path)},
    )

    assert result.exit_code == 1
    assert "not found" in result.output.lower()


def test_spawn_with_task_id_already_completed(monkeypatch, tmp_path):
    """--task-id with completed task should error."""
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    TeamManager.create_team(
        name="demo",
        leader_name="leader",
        leader_id="leader001",
    )
    monkeypatch.setattr("clawteam.spawn.get_backend", lambda _: DummyBackend())

    store = TaskStore("demo")
    task_obj = store.create(subject="Test task", description="Test description", owner="worker1")
    store.update(task_obj.id, status=TaskStatus.completed)

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
            "--task-id",
            task_obj.id,
        ],
        env={"CLAWTEAM_DATA_DIR": str(tmp_path)},
    )

    assert result.exit_code == 1
    assert "already completed" in result.output.lower()


def test_spawn_dedup_reuses_pending_task(monkeypatch, tmp_path):
    """With same owner pending task, reuse instead of create."""
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    TeamManager.create_team(
        name="demo",
        leader_name="leader",
        leader_id="leader001",
    )
    monkeypatch.setattr("clawteam.spawn.get_backend", lambda _: DummyBackend())

    store = TaskStore("demo")
    existing = store.create(subject="Existing task", description="Old description", owner="worker1")

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
            "New task description",
        ],
        env={"CLAWTEAM_DATA_DIR": str(tmp_path)},
    )

    assert result.exit_code == 0, result.output

    tasks = store.list_tasks()
    assert len(tasks) == 1
    task = tasks[0]
    assert task.id == existing.id
    assert task.status == TaskStatus.in_progress
    assert task.locked_by == "worker1"


def test_spawn_dedup_creates_when_no_duplicate(monkeypatch, tmp_path):
    """No duplicate task, create new task."""
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
            "New task description",
        ],
        env={"CLAWTEAM_DATA_DIR": str(tmp_path)},
    )

    assert result.exit_code == 0, result.output

    store = TaskStore("demo")
    tasks = store.list_tasks()
    assert len(tasks) == 1
    assert tasks[0].status == TaskStatus.in_progress


def test_spawn_dedup_reuses_blocked_task(monkeypatch, tmp_path):
    """With same owner blocked task, reuse instead of create."""
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    TeamManager.create_team(
        name="demo",
        leader_name="leader",
        leader_id="leader001",
    )
    monkeypatch.setattr("clawteam.spawn.get_backend", lambda _: DummyBackend())

    store = TaskStore("demo")
    existing = store.create(
        subject="Blocked task",
        description="Old description",
        owner="worker1",
        blocked_by=["abc123"],
    )

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
            "New task description",
        ],
        env={"CLAWTEAM_DATA_DIR": str(tmp_path)},
    )

    assert result.exit_code == 0, result.output

    tasks = store.list_tasks()
    assert len(tasks) == 1
    task = tasks[0]
    assert task.id == existing.id
    assert task.status == TaskStatus.in_progress
    assert task.locked_by == "worker1"


def test_spawn_dedup_sequential(monkeypatch, tmp_path):
    """Sequential spawns with same owner - first claims pending, others create new."""
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    TeamManager.create_team(
        name="demo",
        leader_name="leader",
        leader_id="leader001",
    )
    monkeypatch.setattr("clawteam.spawn.get_backend", lambda _: DummyBackend())

    store = TaskStore("demo")
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
            "worker",
            "--no-workspace",
            "--task",
            "Task 0",
        ],
        env={"CLAWTEAM_DATA_DIR": str(tmp_path)},
    )
    assert result.exit_code == 0

    tasks = store.list_tasks()
    assert len(tasks) == 1
    task_id_0 = tasks[0].id

    for i in range(1, 4):
        result = runner.invoke(
            app,
            [
                "spawn",
                "tmux",
                "openclaw",
                "--team",
                "demo",
                "--agent-name",
                "worker",
                "--no-workspace",
                "--task",
                f"Task {i}",
            ],
            env={"CLAWTEAM_DATA_DIR": str(tmp_path)},
        )
        assert result.exit_code == 0, result.output

    tasks = store.list_tasks()
    assert len(tasks) == 4
    assert any(t.id == task_id_0 for t in tasks)
