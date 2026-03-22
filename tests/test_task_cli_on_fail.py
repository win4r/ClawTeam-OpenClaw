from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from clawteam.cli.commands import app
from clawteam.team.manager import TeamManager
from clawteam.team.tasks import TaskStore


def _team_env(tmp_path: Path) -> dict[str, str]:
    return {
        "CLAWTEAM_DATA_DIR": str(tmp_path / ".clawteam"),
        "CLAWTEAM_AGENT_NAME": "leader",
        "CLAWTEAM_AGENT_ID": "leader001",
        "CLAWTEAM_AGENT_TYPE": "leader",
        "CLAWTEAM_AGENT_LEADER": "1",
        "CLAWTEAM_TEAM_NAME": "demo",
    }


def test_task_create_accepts_on_fail(monkeypatch, tmp_path):
    env = _team_env(tmp_path)
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", env["CLAWTEAM_DATA_DIR"])

    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    store = TaskStore("demo")
    impl = store.create("implement", owner="dev1")

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "task",
            "create",
            "demo",
            "review",
            "--owner",
            "review1",
            "--blocked-by",
            impl.id,
            "--on-fail",
            impl.id,
        ],
        env=env,
    )

    assert result.exit_code == 0, result.output

    review = next(task for task in store.list_tasks() if task.subject == "review")
    assert review.blocked_by == [impl.id]
    assert review.metadata.get("on_fail") == [impl.id]
    assert review.status.value == "blocked"


def test_task_update_add_on_fail_merges_without_duplicates(monkeypatch, tmp_path):
    env = _team_env(tmp_path)
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", env["CLAWTEAM_DATA_DIR"])

    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    store = TaskStore("demo")
    backend = store.create("backend", owner="dev1")
    frontend = store.create("frontend", owner="dev2")
    review = store.create("review", owner="review1", metadata={"on_fail": [backend.id]})

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "task",
            "update",
            "demo",
            review.id,
            "--add-on-fail",
            f"{frontend.id},{backend.id}",
        ],
        env=env,
    )

    assert result.exit_code == 0, result.output

    updated = store.get(review.id)
    assert updated is not None
    assert updated.metadata.get("on_fail") == [backend.id, frontend.id]
