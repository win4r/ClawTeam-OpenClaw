from __future__ import annotations

from clawteam.delivery.release_notifier import notify_task_release
from clawteam.team.mailbox import MailboxManager
from clawteam.team.manager import TeamManager
from clawteam.team.tasks import TaskStore


def test_notify_task_release_sends_wake_message_to_owner(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))

    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    TeamManager.add_member("demo", "qa1", "qa1-id", agent_type="general-purpose")

    task = TaskStore("demo").create("Regression QA", owner="qa1")

    result = notify_task_release("demo", task, "leader", "Start immediately")

    assert result is not None
    assert result["messageSent"] is True
    assert result["message"] == "Start immediately"
    assert result["messageId"]

    owner_messages = MailboxManager("demo").peek("qa1")
    assert any((msg.content or "") == "Start immediately" for msg in owner_messages)
    assert any(msg.key == f"task-wake:{task.id}" for msg in owner_messages)
