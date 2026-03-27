from __future__ import annotations

from typer.testing import CliRunner

from clawteam.cli.commands import app
from clawteam.team.mailbox import MailboxManager
from clawteam.team.tasks import TaskStore


class DummyBackend:
    def __init__(self):
        self.calls = []

    def spawn(self, **kwargs):
        self.calls.append(kwargs)
        return f"spawned:{kwargs.get('agent_name')}"

    def list_running(self):
        return []


class FailingBackend:
    def spawn(self, **kwargs):
        return "Error: agent command 'openclaw' exited immediately after launch."

    def list_running(self):
        return []


def test_launch_template_post_scope_only_materializes_scope_root(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("clawteam.spawn.get_backend", lambda _: DummyBackend())

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "launch",
            "five-step-delivery",
            "--team-name",
            "delivery-demo",
            "--goal",
            "Ship the feature safely",
            "--no-workspace",
        ],
        env={"CLAWTEAM_DATA_DIR": str(tmp_path)},
    )

    assert result.exit_code == 0, result.output

    store = TaskStore("delivery-demo")
    tasks = store.list_tasks()
    assert len(tasks) == 1

    scope = tasks[0]
    assert scope.subject == "Scope the task into a minimal deliverable"
    assert scope.blocked_by == []
    assert scope.metadata.get("template_stage") == "scope"
    assert scope.metadata.get("feature_scope_required") is True
    assert scope.metadata.get("materialization_mode") == "post-scope"
    assert scope.metadata.get("deferred_materialization_state") == "pending_scope_completion"
    workflow_definition = scope.metadata.get("workflow_definition")
    assert workflow_definition["template_name"] == "five-step-delivery"
    assert workflow_definition["preserved_definition"] is True
    assert workflow_definition["materialized_subjects"] == ["Scope the task into a minimal deliverable"]
    assert "Prepare repo, branch, env, and runnable baseline" in workflow_definition["deferred_subjects"]
    assert any(task["stage"] == "deliver" for task in workflow_definition["tasks"])
    assert "Ship the feature safely" in scope.description
    assert "{goal}" not in scope.description
    assert "## Source Request" in scope.description
    assert "## Scoped Brief" in scope.description
    assert "## Unknowns" in scope.description
    assert "## Leader Assumptions" in scope.description
    assert "## Out of Scope" in scope.description
    assert "## Brief Format" in scope.description
    assert "## Interpretation Rules" in scope.description
    assert scope.metadata.get("launch_brief", {}).get("format") in {"structured_sections", "prose_fallback", "empty"}
    assert scope.metadata.get("launch_brief", {}).get("sections", {}).get("source_request") == "Ship the feature safely"
    assert scope.status.value == "pending"

    leader_mail = MailboxManager("delivery-demo").peek("leader")
    wake_keys = {msg.key for msg in leader_mail}
    assert wake_keys == {f"task-wake:{scope.id}"}


def test_launch_template_fails_closed_when_agent_spawn_errors(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("clawteam.spawn.get_backend", lambda _: FailingBackend())

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "launch",
            "five-step-delivery",
            "--team-name",
            "launch-fail-demo",
            "--goal",
            "fail closed on spawn error",
            "--no-workspace",
        ],
        env={"CLAWTEAM_DATA_DIR": str(tmp_path)},
    )

    assert result.exit_code == 1
    assert "Failed to spawn agent 'leader' during launch" in result.output
    assert "launch-fail-demo" not in result.output or "launched from template" not in result.output

    store = TaskStore("launch-fail-demo")
    tasks = store.list_tasks()
    assert len(tasks) == 1
    leader_mail = MailboxManager("launch-fail-demo").peek("leader")
    assert leader_mail == []


def test_launch_template_bootstraps_multiple_root_tasks(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("clawteam.spawn.get_backend", lambda _: DummyBackend())

    template_dir = tmp_path / "templates"
    template_dir.mkdir()
    monkeypatch.setattr("clawteam.templates._USER_DIR", template_dir)
    (template_dir / "multi-root.toml").write_text(
        """
[template]
name = "multi-root"
description = "Multi-root launch bootstrap test"
backend = "tmux"
command = ["openclaw"]

[template.leader]
name = "leader"
type = "leader"
task = "Lead"

[[template.agents]]
name = "worker1"
type = "general-purpose"
task = "Do root A"

[[template.agents]]
name = "worker2"
type = "general-purpose"
task = "Do root B"

[[template.tasks]]
subject = "Root A"
owner = "worker1"
description = "A"

[[template.tasks]]
subject = "Root B"
owner = "worker2"
description = "B"

[[template.tasks]]
subject = "Blocked tail"
owner = "leader"
description = "tail"
blocked_by = ["Root A", "Root B"]
""".strip(),
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["launch", "multi-root", "--team-name", "multi-root-demo", "--goal", "bootstrap roots", "--no-workspace"],
        env={"CLAWTEAM_DATA_DIR": str(tmp_path)},
    )

    assert result.exit_code == 0, result.output

    store = TaskStore("multi-root-demo")
    tasks = {task.subject: task for task in store.list_tasks()}
    root_a = tasks["Root A"]
    root_b = tasks["Root B"]
    tail = tasks["Blocked tail"]

    assert root_a.status.value == "pending"
    assert root_b.status.value == "pending"
    assert tail.status.value == "blocked"

    worker1_mail = MailboxManager("multi-root-demo").peek("worker1")
    worker2_mail = MailboxManager("multi-root-demo").peek("worker2")
    leader_mail = MailboxManager("multi-root-demo").peek("leader")

    assert any(msg.key == f"task-wake:{root_a.id}" for msg in worker1_mail)
    assert any(msg.key == f"task-wake:{root_b.id}" for msg in worker2_mail)
    assert all(msg.key != f"task-wake:{tail.id}" for msg in leader_mail)
