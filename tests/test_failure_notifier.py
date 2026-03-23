from __future__ import annotations

from clawteam.delivery.failure_notifier import notify_task_failure
from clawteam.team.mailbox import MailboxManager
from clawteam.team.manager import TeamManager
from clawteam.team.tasks import TaskStore


def test_notify_task_failure_sends_complex_failure_to_leader(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))

    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    TeamManager.add_member("demo", "qa1", "qa1-id", agent_type="general-purpose")

    store = TaskStore("demo")
    task = store.create(
        "Regression QA",
        owner="qa1",
        metadata={
            "failure_kind": "complex",
            "failure_root_cause": "ownership unclear",
            "failure_evidence": "cross-cutting regression",
            "failure_recommended_next_owner": "leader",
            "failure_recommended_action": "triage owner",
        },
    )

    result = notify_task_failure("demo", task, "qa1")

    assert result is not None
    assert result["failureNotice"] == "sent"
    assert result["failureLeader"] == "leader"
    leader_messages = MailboxManager("demo").peek("leader")
    assert any("COMPLEX FAIL:" in (msg.content or "") for msg in leader_messages)


def test_notify_task_failure_skips_non_complex_failures(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))

    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    TeamManager.add_member("demo", "qa1", "qa1-id", agent_type="general-purpose")

    store = TaskStore("demo")
    task = store.create("Regression QA", owner="qa1", metadata={"failure_kind": "regular"})

    result = notify_task_failure("demo", task, "qa1")

    assert result == {"failureNotice": "skipped", "failureKind": "regular"}
    assert MailboxManager("demo").peek("leader") == []
