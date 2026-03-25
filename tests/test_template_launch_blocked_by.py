from __future__ import annotations

from typer.testing import CliRunner

from clawteam.cli.commands import app
from clawteam.team.mailbox import MailboxManager
from clawteam.team.models import TaskStatus
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
    assert all(
        f"task-wake:{task.id}" not in wake_keys
        for task in [setup, backend, frontend, qa_main, qa_reg, review, deliver]
    )


def test_five_step_delivery_pass_with_risk_completion_still_unblocks_review(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("clawteam.spawn.get_backend", lambda _: DummyBackend())

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "launch",
            "five-step-delivery",
            "--team-name",
            "delivery-pass-with-risk",
            "--goal",
            "Validate pass_with_risk routing",
            "--no-workspace",
        ],
        env={"CLAWTEAM_DATA_DIR": str(tmp_path)},
    )

    assert result.exit_code == 0, result.output

    store = TaskStore("delivery-pass-with-risk")
    by_subject = {task.subject: task for task in store.list_tasks()}

    backend = by_subject["Implement backend/data changes with real validation"]
    frontend = by_subject["Implement frontend/UI changes with real validation"]
    qa_main = by_subject["Run main-flow QA on the real change"]
    qa_reg = by_subject["Run edge-case and regression QA on the real change"]
    review = by_subject["Review code quality, maintainability, and delivery readiness"]

    store.update(backend.id, status=TaskStatus.completed, caller="dev1")
    store.update(frontend.id, status=TaskStatus.completed, caller="dev2")
    store.update(qa_main.id, status=TaskStatus.completed, caller="qa1")
    store.update(
        qa_reg.id,
        status=TaskStatus.completed,
        caller="qa2",
        metadata={
            "qa_result_status": "pass_with_risk",
            "qa_risk_note": "main goal validated; failed-branch evidence unavailable on real host",
        },
    )

    refreshed_review = store.get(review.id)
    refreshed_backend = store.get(backend.id)
    refreshed_frontend = store.get(frontend.id)
    refreshed_qa_reg = store.get(qa_reg.id)

    assert refreshed_review is not None
    assert refreshed_review.status == TaskStatus.pending
    assert refreshed_review.blocked_by == []
    assert refreshed_backend is not None
    assert refreshed_backend.status == TaskStatus.completed
    assert refreshed_frontend is not None
    assert refreshed_frontend.status == TaskStatus.completed
    assert refreshed_qa_reg is not None
    assert refreshed_qa_reg.metadata["qa_result_status"] == "pass_with_risk"


def test_task_update_cli_persists_pass_with_risk_metadata_and_unblocks_review(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("clawteam.spawn.get_backend", lambda _: DummyBackend())

    runner = CliRunner()
    launch = runner.invoke(
        app,
        [
            "launch",
            "five-step-delivery",
            "--team-name",
            "delivery-pass-with-risk-cli",
            "--goal",
            "Validate pass_with_risk routing",
            "--no-workspace",
        ],
        env={"CLAWTEAM_DATA_DIR": str(tmp_path)},
    )
    assert launch.exit_code == 0, launch.output

    store = TaskStore("delivery-pass-with-risk-cli")
    by_subject = {task.subject: task for task in store.list_tasks()}
    backend = by_subject["Implement backend/data changes with real validation"]
    frontend = by_subject["Implement frontend/UI changes with real validation"]
    qa_main = by_subject["Run main-flow QA on the real change"]
    qa_reg = by_subject["Run edge-case and regression QA on the real change"]
    review = by_subject["Review code quality, maintainability, and delivery readiness"]

    store.update(backend.id, status=TaskStatus.in_progress, caller="dev1")
    store.update(frontend.id, status=TaskStatus.in_progress, caller="dev2")
    store.update(qa_main.id, status=TaskStatus.in_progress, caller="qa1")
    store.update(qa_reg.id, status=TaskStatus.in_progress, caller="qa2")

    env = {
        "CLAWTEAM_DATA_DIR": str(tmp_path),
        "CLAWTEAM_AGENT_NAME": "qa2",
        "CLAWTEAM_AGENT_ID": "qa2-id",
        "CLAWTEAM_AGENT_TYPE": "general-purpose",
        "CLAWTEAM_TEAM_NAME": "delivery-pass-with-risk-cli",
        "CLAWTEAM_TASK_EXECUTION_ID": store.get(qa_reg.id).active_execution_id,
    }

    store.update(backend.id, status=TaskStatus.completed, caller="dev1", execution_id=store.get(backend.id).active_execution_id)
    store.update(frontend.id, status=TaskStatus.completed, caller="dev2", execution_id=store.get(frontend.id).active_execution_id)
    store.update(qa_main.id, status=TaskStatus.completed, caller="qa1", execution_id=store.get(qa_main.id).active_execution_id)

    result = runner.invoke(
        app,
        [
            "task",
            "update",
            "delivery-pass-with-risk-cli",
            qa_reg.id,
            "--status",
            "completed",
            "--qa-result-status",
            "pass_with_risk",
            "--qa-risk-note",
            "main goal validated; failed-branch evidence unavailable on real host",
        ],
        env=env,
    )

    assert result.exit_code == 0, result.output

    refreshed_qa_reg = store.get(qa_reg.id)
    refreshed_review = store.get(review.id)
    assert refreshed_qa_reg is not None
    assert refreshed_qa_reg.metadata["qa_result_status"] == "pass_with_risk"
    assert refreshed_qa_reg.metadata["qa_risk_note"] == "main goal validated; failed-branch evidence unavailable on real host"
    assert refreshed_review is not None
    assert refreshed_review.status == TaskStatus.pending
    assert refreshed_review.blocked_by == []


def test_launch_template_instantiates_agent_prompt_and_task_description(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path))

    spawned_prompts: list[dict[str, str]] = []

    class CaptureBackend(DummyBackend):
        def spawn(self, **kwargs):
            spawned_prompts.append({
                "agent_name": kwargs.get("agent_name", ""),
                "prompt": kwargs.get("prompt", ""),
            })
            return super().spawn(**kwargs)

    monkeypatch.setattr("clawteam.spawn.get_backend", lambda _: CaptureBackend())

    template_dir = tmp_path / "templates"
    template_dir.mkdir()
    monkeypatch.setattr("clawteam.templates._USER_DIR", template_dir)
    (template_dir / "instantiation-demo.toml").write_text(
        """
[template]
name = "instantiation-demo"
description = "Instantiation contract test"
backend = "tmux"
command = ["openclaw"]

[template.leader]
name = "leader"
type = "leader"
task = "Lead {goal} for {team_name}"

[[template.agents]]
name = "dev1"
type = "general-purpose"
task = "Implement {goal} as {agent_name} for {team_name}"

[[template.tasks]]
subject = "Build {goal}"
owner = "dev1"
description = "Ship {goal} for {team_name} via {agent_name}"
""".strip(),
        encoding="utf-8",
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["launch", "instantiation-demo", "--team-name", "inst-demo", "--goal", "search", "--no-workspace"],
        env={"CLAWTEAM_DATA_DIR": str(tmp_path)},
    )

    assert result.exit_code == 0, result.output

    store = TaskStore("inst-demo")
    tasks = {task.subject: task for task in store.list_tasks()}
    assert "Build search" in tasks
    assert tasks["Build search"].description == "Ship search for inst-demo via dev1"

    dev_prompt = next(item["prompt"] for item in spawned_prompts if item["agent_name"] == "dev1")
    assert "Implement search as dev1 for inst-demo" in dev_prompt
    assert "{goal}" not in dev_prompt
    assert "{team_name}" not in dev_prompt


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
