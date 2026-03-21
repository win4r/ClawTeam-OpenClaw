from __future__ import annotations

from typer.testing import CliRunner

from clawteam.cli.commands import app
from clawteam.team.tasks import TaskStore


class DummyBackend:
    def spawn(self, **kwargs):
        return {"ok": True, "agent": kwargs.get("agent_name")}

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
