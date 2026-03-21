from __future__ import annotations

import os
from pathlib import Path

from typer.testing import CliRunner

from clawteam.cli.commands import app
from clawteam.team.mailbox import MailboxManager
from clawteam.team.manager import TeamManager
from clawteam.team.models import TaskStatus
from clawteam.team.tasks import TaskStore


class RecordingBackend:
    def __init__(self):
        self.calls: list[dict] = []

    def spawn(self, **kwargs):
        self.calls.append(kwargs)
        return f"Agent '{kwargs['agent_name']}' spawned"

    def list_running(self):
        return []


def _write_workspace_registry(team: str, agent: str, worktree_path: Path, repo_root: Path) -> None:
    data_dir = Path(os.environ["CLAWTEAM_DATA_DIR"])
    path = data_dir / "workspaces" / team / "workspace-registry.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """
{
  "team_name": "%s",
  "repo_root": "%s",
  "workspaces": [
    {
      "agent_name": "%s",
      "agent_id": "qa1-id",
      "team_name": "%s",
      "branch_name": "clawteam/%s/%s",
      "worktree_path": "%s",
      "repo_root": "%s",
      "base_branch": "main",
      "created_at": "2026-03-21T00:00:00+00:00"
    }
  ]
}
        """.strip()
        % (team, repo_root, agent, team, team, agent, worktree_path, repo_root),
        encoding="utf-8",
    )


def _team_env(tmp_path: Path) -> dict[str, str]:
    return {
        "CLAWTEAM_DATA_DIR": str(tmp_path / ".clawteam"),
        "CLAWTEAM_AGENT_NAME": "leader",
        "CLAWTEAM_AGENT_ID": "leader001",
        "CLAWTEAM_AGENT_TYPE": "leader",
        "CLAWTEAM_AGENT_LEADER": "1",
        "CLAWTEAM_TEAM_NAME": "demo",
    }


def test_task_release_respawns_dead_owner_in_existing_workspace(monkeypatch, tmp_path):
    env = _team_env(tmp_path)
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", env["CLAWTEAM_DATA_DIR"])

    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    TeamManager.add_member("demo", "qa1", "qa1-id", agent_type="general-purpose")

    store = TaskStore("demo")
    task = store.create("Functional QA", description="Check company directory", owner="qa1")

    workspace = tmp_path / "qa1-worktree"
    workspace.mkdir()
    _write_workspace_registry("demo", "qa1", workspace, tmp_path)

    backend = RecordingBackend()
    monkeypatch.setattr("clawteam.spawn.get_backend", lambda _: backend)
    monkeypatch.setattr("clawteam.spawn.registry.is_agent_alive", lambda *_: False)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["task", "release", "demo", task.id, "--message", "Start immediately"],
        env=env,
    )

    assert result.exit_code == 0, result.output
    assert len(backend.calls) == 1
    call = backend.calls[0]
    assert call["agent_name"] == "qa1"
    assert call["cwd"] == str(workspace)
    assert "Functional QA" in call["prompt"]
    assert "Start immediately" in call["prompt"]

    inbox = MailboxManager("demo")
    messages = inbox.peek("qa1")
    assert any("Start immediately" in (msg.content or "") for msg in messages)


def test_task_update_wake_owner_respawns_dead_worker(monkeypatch, tmp_path):
    env = _team_env(tmp_path)
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", env["CLAWTEAM_DATA_DIR"])

    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    TeamManager.add_member("demo", "qa1", "qa1-id", agent_type="general-purpose")

    store = TaskStore("demo")
    task = store.create(
        "Regression QA",
        description="Verify navigation and failure states",
        owner="qa1",
        blocked_by=["dep-1"],
    )

    workspace = tmp_path / "qa1-worktree"
    workspace.mkdir()
    _write_workspace_registry("demo", "qa1", workspace, tmp_path)

    backend = RecordingBackend()
    monkeypatch.setattr("clawteam.spawn.get_backend", lambda _: backend)
    monkeypatch.setattr("clawteam.spawn.registry.is_agent_alive", lambda *_: False)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "task",
            "update",
            "demo",
            task.id,
            "--status",
            "pending",
            "--wake-owner",
            "--message",
            "Release QA now",
        ],
        env=env,
    )

    assert result.exit_code == 0, result.output
    assert len(backend.calls) == 1
    call = backend.calls[0]
    assert call["agent_name"] == "qa1"
    assert call["cwd"] == str(workspace)
    assert "Regression QA" in call["prompt"]
    assert "Release QA now" in call["prompt"]
    assert TaskStore("demo").get(task.id).status.value == "pending"


def test_task_complete_auto_notifies_and_respawns_unblocked_owner(monkeypatch, tmp_path):
    env = _team_env(tmp_path)
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", env["CLAWTEAM_DATA_DIR"])

    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    TeamManager.add_member("demo", "dev1", "dev1-id", agent_type="general-purpose")
    TeamManager.add_member("demo", "qa1", "qa1-id", agent_type="general-purpose")

    store = TaskStore("demo")
    impl = store.create("Implement fix", owner="dev1")
    qa = store.create("Regression QA", description="Verify the fix", owner="qa1", blocked_by=[impl.id])

    workspace = tmp_path / "qa1-worktree"
    workspace.mkdir()
    _write_workspace_registry("demo", "qa1", workspace, tmp_path)

    backend = RecordingBackend()
    monkeypatch.setattr("clawteam.spawn.get_backend", lambda _: backend)
    monkeypatch.setattr("clawteam.spawn.registry.is_agent_alive", lambda team, agent: False if agent == "qa1" else True)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["task", "update", "demo", impl.id, "--status", "completed"],
        env=env,
    )

    assert result.exit_code == 0, result.output
    assert len(backend.calls) == 1
    call = backend.calls[0]
    assert call["agent_name"] == "qa1"
    assert call["cwd"] == str(workspace)
    assert "Regression QA" in call["prompt"]
    assert "unblocked because dependency" in call["prompt"]

    qa_after = TaskStore("demo").get(qa.id)
    assert qa_after.status.value == "pending"
    assert qa_after.blocked_by == []

    inbox = MailboxManager("demo")
    messages = inbox.peek("qa1")
    assert any("unblocked because dependency" in (msg.content or "") for msg in messages)


def test_task_failed_auto_notifies_and_respawns_reopened_owner(monkeypatch, tmp_path):
    env = _team_env(tmp_path)
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", env["CLAWTEAM_DATA_DIR"])

    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    TeamManager.add_member("demo", "dev1", "dev1-id", agent_type="general-purpose")
    TeamManager.add_member("demo", "qa1", "qa1-id", agent_type="general-purpose")

    store = TaskStore("demo")
    impl = store.create("Implement fix", description="Fix the broken path", owner="dev1")
    qa = store.create(
        "Regression QA",
        owner="qa1",
        blocked_by=[impl.id],
        metadata={"on_fail": [impl.id]},
    )
    store.update(impl.id, status=TaskStatus.completed)

    workspace = tmp_path / "dev1-worktree"
    workspace.mkdir()
    _write_workspace_registry("demo", "dev1", workspace, tmp_path)

    backend = RecordingBackend()
    monkeypatch.setattr("clawteam.spawn.get_backend", lambda _: backend)
    monkeypatch.setattr("clawteam.spawn.registry.is_agent_alive", lambda team, agent: False if agent == "dev1" else True)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "task", "update", "demo", qa.id,
            "--status", "failed",
            "--failure-kind", "regular",
            "--failure-note", "Repro is clear; send back to implement",
        ],
        env=env,
    )

    assert result.exit_code == 0, result.output
    assert len(backend.calls) == 1
    call = backend.calls[0]
    assert call["agent_name"] == "dev1"
    assert call["cwd"] == str(workspace)
    assert "Implement fix" in call["prompt"]
    assert "reopened because task" in call["prompt"]

    impl_after = TaskStore("demo").get(impl.id)
    assert impl_after.status.value == "pending"
    assert qa.id in impl_after.blocked_by

    inbox = MailboxManager("demo")
    messages = inbox.peek("dev1")
    assert any("reopened because task" in (msg.content or "") for msg in messages)


def test_task_update_failed_complex_notifies_leader(monkeypatch, tmp_path):
    env = _team_env(tmp_path)
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", env["CLAWTEAM_DATA_DIR"])

    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    TeamManager.add_member("demo", "qa1", "qa1-id", agent_type="general-purpose")

    store = TaskStore("demo")
    task = store.create("Regression QA", owner="qa1")

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "task", "update", "demo", task.id,
            "--status", "failed",
            "--failure-kind", "complex",
            "--failure-root-cause", "Owner and reroute are unclear",
            "--failure-evidence", "Both backend and frontend changed; QA cannot isolate",
            "--failure-recommended-next-owner", "leader",
            "--failure-recommended-action", "Decide whether dev1 or dev2 owns the next fix",
        ],
        env=env,
    )

    assert result.exit_code == 0, result.output
    updated = TaskStore("demo").get(task.id)
    assert updated.status.value == "failed"
    assert updated.metadata["failure_kind"] == "complex"
    assert updated.metadata["failure_root_cause"] == "Owner and reroute are unclear"
    assert updated.metadata["failure_evidence"] == "Both backend and frontend changed; QA cannot isolate"
    assert updated.metadata["failure_recommended_next_owner"] == "leader"
    assert updated.metadata["failure_recommended_action"] == "Decide whether dev1 or dev2 owns the next fix"

    inbox = MailboxManager("demo")
    messages = inbox.peek("leader")
    assert any("COMPLEX FAIL" in (msg.content or "") for msg in messages)
    assert any("Root cause: Owner and reroute are unclear" in (msg.content or "") for msg in messages)
    assert any(task.id in (msg.content or "") for msg in messages)


def test_task_update_failed_regular_does_not_notify_leader(monkeypatch, tmp_path):
    env = _team_env(tmp_path)
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", env["CLAWTEAM_DATA_DIR"])

    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    TeamManager.add_member("demo", "qa1", "qa1-id", agent_type="general-purpose")

    store = TaskStore("demo")
    task = store.create("Regression QA", owner="qa1")

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "task", "update", "demo", task.id,
            "--status", "failed",
            "--failure-kind", "regular",
            "--failure-note", "Clear repro, return to implement",
            "--failure-root-cause", "Validation mismatch",
            "--failure-evidence", "Regression reproduced twice",
            "--failure-recommended-next-owner", "dev1",
            "--failure-recommended-action", "Fix API contract and rerun QA",
        ],
        env=env,
    )

    assert result.exit_code == 0, result.output
    updated = TaskStore("demo").get(task.id)
    assert updated.metadata["failure_kind"] == "regular"
    assert updated.metadata["failure_root_cause"] == "Validation mismatch"

    inbox = MailboxManager("demo")
    messages = inbox.peek("leader")
    assert messages == []


def test_task_update_failed_complex_requires_structured_fields(monkeypatch, tmp_path):
    env = _team_env(tmp_path)
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", env["CLAWTEAM_DATA_DIR"])

    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    TeamManager.add_member("demo", "qa1", "qa1-id", agent_type="general-purpose")

    task = TaskStore("demo").create("Regression QA", owner="qa1")

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "task", "update", "demo", task.id,
            "--status", "failed",
            "--failure-kind", "complex",
            "--failure-root-cause", "Owner unclear",
        ],
        env=env,
    )

    assert result.exit_code == 1, result.output
    assert "complex fail requires" in result.output
