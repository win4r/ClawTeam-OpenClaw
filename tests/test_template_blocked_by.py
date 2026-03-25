"""Tests for template launch with blocked_by dependencies."""

import pytest
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


def test_launch_template_blocked_by_resolves_to_task_ids(monkeypatch, tmp_path):
    """TOML blocked_by references should resolve to actual task IDs, not strings."""
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("clawteam.spawn.get_backend", lambda _: DummyBackend())

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "launch",
            "swarm-thinking",
            "--goal",
            "test research",
            "--no-workspace",
            "--team-name",
            "test-swarm",
        ],
        env={"CLAWTEAM_DATA_DIR": str(tmp_path)},
    )

    assert result.exit_code == 0, f"Exit code: {result.exit_code}\nOutput: {result.output}"

    store = TaskStore("test-swarm")
    tasks = store.list_tasks()

    task_subjects = {t.subject: t for t in tasks}
    assert len(tasks) == 5, f"Expected 5 tasks, got {len(tasks)}"

    write_report_task = task_subjects["Write comprehensive report"]
    assert write_report_task.status == TaskStatus.blocked, (
        f"Write comprehensive report should be blocked, got {write_report_task.status}"
    )

    blocked_by_ids = write_report_task.blocked_by
    assert len(blocked_by_ids) == 3, f"Expected 3 blocking tasks, got {len(blocked_by_ids)}"

    arch_task = task_subjects["Architecture research"]
    workflow_task = task_subjects["Workflow research"]
    risk_task = task_subjects["Risk assessment"]

    assert arch_task.id in blocked_by_ids, f"Architecture research task ID should be in blocked_by"
    assert workflow_task.id in blocked_by_ids, f"Workflow research task ID should be in blocked_by"
    assert risk_task.id in blocked_by_ids, f"Risk assessment task ID should be in blocked_by"

    for tid in blocked_by_ids:
        task = store.get(tid)
        assert task is not None, f"Task ID {tid} should exist"
        assert task.status == TaskStatus.pending, (
            f"Blocking task {task.subject} should be pending, got {task.status}"
        )

    integrate_task = task_subjects["Integrate final report"]
    assert integrate_task.status == TaskStatus.blocked
    assert integrate_task.blocked_by == [write_report_task.id]


def test_launch_template_blocked_by_handles_missing_reference(monkeypatch, tmp_path, capsys):
    """Missing blocked_by reference should warn but not fail."""
    import clawteam.templates as tmod

    user_tpl_dir = tmp_path / ".clawteam" / "templates"
    user_tpl_dir.mkdir(parents=True)

    toml_content = """\
[template]
name = "test-missing-ref"
description = "Test template"
command = ["openclaw"]
backend = "tmux"

[template.leader]
name = "leader"
type = "general-purpose"

[[template.tasks]]
subject = "task-a"

[[template.tasks]]
subject = "task-b"
blocked_by = ["non-existent-task"]
"""
    (user_tpl_dir / "test-missing-ref.toml").write_text(toml_content)

    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("clawteam.spawn.get_backend", lambda _: DummyBackend())

    import clawteam.templates as tmod

    monkeypatch.setattr(tmod, "_USER_DIR", user_tpl_dir)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "launch",
            "test-missing-ref",
            "--no-workspace",
        ],
        env={"CLAWTEAM_DATA_DIR": str(tmp_path)},
    )

    assert result.exit_code == 0, f"Exit code: {result.exit_code}\nOutput: {result.output}"
    assert "Warning" in result.output or "warning" in result.output.lower()


def test_template_parsed_blocked_by_field(monkeypatch, tmp_path):
    """Verify TaskDef correctly parses blocked_by from TOML."""
    import clawteam.templates as tmod

    user_tpl_dir = tmp_path / ".clawteam" / "templates"
    user_tpl_dir.mkdir(parents=True)

    toml_content = """\
[template]
name = "test-parse"
description = "Test"
command = ["openclaw"]
backend = "tmux"

[template.leader]
name = "leader"

[[template.tasks]]
subject = "first"
blocked_by = ["second", "third"]

[[template.tasks]]
subject = "second"

[[template.tasks]]
subject = "third"
"""
    (user_tpl_dir / "test-parse.toml").write_text(toml_content)

    monkeypatch.setattr(tmod, "_USER_DIR", user_tpl_dir)

    tmpl = tmod.load_template("test-parse")
    assert len(tmpl.tasks) == 3

    first_task = next(t for t in tmpl.tasks if t.subject == "first")
    assert first_task.blocked_by == ["second", "third"]

    second_task = next(t for t in tmpl.tasks if t.subject == "second")
    assert second_task.blocked_by == []
