from __future__ import annotations

from unittest.mock import patch

from clawteam.services.task_update_service import (
    TaskUpdateRequest,
    execute_task_update,
    execute_task_update_effects,
)
from clawteam.team.mailbox import MailboxManager
from clawteam.team.manager import TeamManager
from clawteam.team.models import TaskStatus
from clawteam.team.tasks import TaskStore


def test_execute_task_update_builds_full_result_and_updates_store(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))

    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    TeamManager.add_member("demo", "dev1", "dev1-id", agent_type="general-purpose")
    TeamManager.add_member("demo", "qa1", "qa1-id", agent_type="general-purpose")

    store = TaskStore("demo")
    impl = store.create("Implement fix", owner="dev1")
    qa = store.create("Regression QA", owner="qa1", metadata={"on_fail": [impl.id]})

    monkeypatch.setattr(
        "clawteam.services.task_update_service.wake_tasks_to_pending",
        lambda *args, **kwargs: [{"taskId": impl.id, "owner": "dev1", "respawned": False}],
    )

    result = execute_task_update(
        team="demo",
        task_id=qa.id,
        caller="qa1",
        store=store,
        request=TaskUpdateRequest(
            status=TaskStatus.failed,
            owner=None,
            subject=None,
            description=None,
            add_blocks=None,
            add_blocked_by=None,
            add_on_fail=None,
            failure_kind="complex",
            failure_note=None,
            failure_root_cause="ownership unclear",
            failure_evidence="cross-cutting regression",
            failure_recommended_next_owner="leader",
            failure_recommended_action="triage owner",
            wake_owner=False,
            message="",
            force=False,
        ),
    )

    assert result.task.status == TaskStatus.failed
    assert result.plan.failed_targets_to_wake == []
    assert result.effects.failure_notice is not None
    assert result.effects.failure_notice["failureNotice"] == "sent"
    leader_messages = MailboxManager("demo").peek("leader")
    assert any("COMPLEX FAIL:" in (msg.content or "") for msg in leader_messages)


def test_execute_task_update_effects_handles_failure_notice_and_reopen_release(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))

    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    TeamManager.add_member("demo", "dev1", "dev1-id", agent_type="general-purpose")
    TeamManager.add_member("demo", "qa1", "qa1-id", agent_type="general-purpose")

    store = TaskStore("demo")
    impl = store.create("Implement fix", owner="dev1")
    qa = store.create("Regression QA", owner="qa1", metadata={"on_fail": [impl.id]})
    with patch("clawteam.spawn.registry.is_agent_alive", return_value=None):
        task = store.update(
            qa.id,
            status=TaskStatus.failed,
            caller="qa1",
            metadata={
                "failure_kind": "complex",
                "failure_root_cause": "ownership unclear",
                "failure_evidence": "cross-cutting regression",
                "failure_recommended_next_owner": "leader",
                "failure_recommended_action": "triage owner",
            },
        )

    monkeypatch.setattr(
        "clawteam.services.task_update_service.wake_tasks_to_pending",
        lambda *args, **kwargs: [{"taskId": impl.id, "owner": "dev1", "respawned": False}],
    )

    effects = execute_task_update_effects(
        team="demo",
        task=task,
        caller="qa1",
        wake_owner=False,
        message="",
        dependent_ids_to_wake=[],
        failed_targets_to_wake=[impl.id],
    )

    assert effects.wake is None
    assert len(effects.auto_releases) == 1
    assert effects.auto_releases[0]["taskId"] == impl.id
    assert effects.failure_notice is not None
    assert effects.failure_notice["failureNotice"] == "sent"
    assert effects.failure_notice["failureLeader"] == "leader"
    leader_messages = MailboxManager("demo").peek("leader")
    assert any("COMPLEX FAIL:" in (msg.content or "") for msg in leader_messages)
