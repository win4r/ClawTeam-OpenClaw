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


def test_notify_task_failure_includes_repair_packet_details(monkeypatch, tmp_path):
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
            "failure_target_files": ["clawteam/board/static/index.html"],
            "failure_repro_steps": "Open board at 1600x1200",
            "failure_expected_result": "Render 5 tracks",
            "failure_candidate_patch": "Existing local diff is candidate only",
        },
    )

    notify_task_failure("demo", task, "qa1")

    leader_messages = MailboxManager("demo").peek("leader")
    content = "\n".join((msg.content or "") for msg in leader_messages)
    assert "Repair packet / target files:" in content
    assert "clawteam/board/static/index.html" in content
    assert "Repair packet / repro steps: Open board at 1600x1200" in content
    assert "Repair packet / expected result: Render 5 tracks" in content
    assert "Repair packet / candidate patch: Existing local diff is candidate only" in content


def test_notify_task_failure_skips_non_complex_failures(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / "data"))

    TeamManager.create_team(name="demo", leader_name="leader", leader_id="leader001")
    TeamManager.add_member("demo", "qa1", "qa1-id", agent_type="general-purpose")

    store = TaskStore("demo")
    task = store.create("Regression QA", owner="qa1", metadata={"failure_kind": "regular"})

    result = notify_task_failure("demo", task, "qa1")

    assert result == {"failureNotice": "skipped", "failureKind": "regular"}
    assert MailboxManager("demo").peek("leader") == []
