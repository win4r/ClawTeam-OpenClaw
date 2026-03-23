from __future__ import annotations

from typer.testing import CliRunner

from clawteam.cli.commands import app
from clawteam.team.mailbox import MailboxManager
from clawteam.team.tasks import TaskStore


class DummyBackend:
    def spawn(self, **kwargs):
        return f"spawned:{kwargs.get('agent_name')}"

    def list_running(self):
        return []


def test_launch_template_creates_blocked_by_chain(monkeypatch, tmp_path):
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
    by_subject = {task.subject: task for task in tasks}

    scope = by_subject["Scope the task into a minimal deliverable"]
    setup = by_subject["Prepare repo, branch, env, and runnable baseline"]
    backend = by_subject["Implement backend/data changes with real validation"]
    frontend = by_subject["Implement frontend/UI changes with real validation"]
    qa_main = by_subject["Run main-flow QA on the real change"]
    qa_reg = by_subject["Run edge-case and regression QA on the real change"]
    review = by_subject["Review code quality, maintainability, and delivery readiness"]
    deliver = by_subject["Prepare final delivery package and human decision summary"]

    assert scope.blocked_by == []
    assert setup.blocked_by == [scope.id]
    assert backend.blocked_by == [setup.id]
    assert frontend.blocked_by == [setup.id]
    assert qa_main.blocked_by == [backend.id, frontend.id]
    assert qa_reg.blocked_by == [backend.id, frontend.id]
    assert review.blocked_by == [qa_main.id, qa_reg.id]
    assert deliver.blocked_by == [review.id]
    assert qa_main.metadata.get("on_fail") == [backend.id, frontend.id]
    assert "Ship the feature safely" in scope.description
    assert "{goal}" not in scope.description

    assert qa_reg.metadata.get("on_fail") == [backend.id, frontend.id]
    assert review.metadata.get("on_fail") == [backend.id, frontend.id]

    assert scope.status.value == "pending"
    assert setup.status.value == "blocked"
    assert backend.status.value == "blocked"
    assert frontend.status.value == "blocked"
    assert qa_main.status.value == "blocked"
    assert qa_reg.status.value == "blocked"
    assert review.status.value == "blocked"
    assert deliver.status.value == "blocked"

    leader_mail = MailboxManager("delivery-demo").peek("leader")
    wake_keys = {msg.key for msg in leader_mail}
    assert f"task-wake:{scope.id}" in wake_keys
    assert all(f"task-wake:{task.id}" not in wake_keys for task in [setup, backend, frontend, qa_main, qa_reg, review, deliver])


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
