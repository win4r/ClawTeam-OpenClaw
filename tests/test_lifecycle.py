"""Tests for clawteam.team.lifecycle — LifecycleManager shutdown/idle protocol."""

from clawteam.team.lifecycle import LifecycleManager
from clawteam.team.mailbox import MailboxManager
from clawteam.team.manager import TeamManager
from clawteam.team.models import MessageType
from clawteam.transport.file import FileTransport


def _setup(team_name: str) -> tuple[LifecycleManager, MailboxManager]:
    TeamManager.create_team(
        name=team_name, leader_name="leader", leader_id="lid",
    )
    TeamManager.add_member(team_name, "worker", "wid")
    transport = FileTransport(team_name)
    mailbox = MailboxManager(team_name, transport=transport)
    return LifecycleManager(team_name, mailbox), mailbox


class TestRequestShutdown:
    def test_sends_shutdown_request(self, team_name):
        lm, mailbox = _setup(team_name)
        request_id = lm.request_shutdown(from_agent="leader", to_agent="worker", reason="done")
        assert request_id

        msgs = mailbox.receive("worker")
        assert len(msgs) == 1
        assert msgs[0].type == MessageType.shutdown_request
        assert "done" in (msgs[0].content or "")

    def test_request_id_is_unique(self, team_name):
        lm, _ = _setup(team_name)
        id1 = lm.request_shutdown(from_agent="leader", to_agent="worker")
        id2 = lm.request_shutdown(from_agent="leader", to_agent="worker")
        assert id1 != id2


class TestApproveShutdown:
    def test_sends_approval_to_requester(self, team_name):
        lm, mailbox = _setup(team_name)
        lm.approve_shutdown(agent_name="worker", request_id="req-1", requester_name="leader")

        msgs = mailbox.receive("leader")
        assert len(msgs) == 1
        assert msgs[0].type == MessageType.shutdown_approved
        assert msgs[0].request_id == "req-1"


class TestRejectShutdown:
    def test_sends_rejection_with_reason(self, team_name):
        lm, mailbox = _setup(team_name)
        lm.reject_shutdown(
            agent_name="worker", request_id="req-2",
            requester_name="leader", reason="still busy",
        )

        msgs = mailbox.receive("leader")
        assert len(msgs) == 1
        assert msgs[0].type == MessageType.shutdown_rejected
        assert "still busy" in (msgs[0].content or "")

    def test_rejection_without_reason(self, team_name):
        lm, mailbox = _setup(team_name)
        lm.reject_shutdown(agent_name="worker", request_id="req-3", requester_name="leader")

        msgs = mailbox.receive("leader")
        assert len(msgs) == 1
        assert msgs[0].type == MessageType.shutdown_rejected


class TestSendIdle:
    def test_idle_notification_reaches_leader(self, team_name):
        lm, mailbox = _setup(team_name)
        lm.send_idle(
            agent_name="worker", agent_id="wid",
            leader_name="leader", last_task="task-1", task_status="completed",
        )

        msgs = mailbox.receive("leader")
        assert len(msgs) == 1
        assert msgs[0].type == MessageType.idle
        assert msgs[0].from_agent == "worker"

    def test_idle_without_task_info(self, team_name):
        lm, mailbox = _setup(team_name)
        lm.send_idle(agent_name="worker", agent_id="wid", leader_name="leader")

        msgs = mailbox.receive("leader")
        assert len(msgs) == 1
        assert msgs[0].type == MessageType.idle


class TestSendWorkerHeartbeat:
    def test_worker_heartbeat_reaches_leader(self, team_name):
        lm, mailbox = _setup(team_name)
        lm.send_worker_heartbeat(
            agent_name="worker",
            agent_id="wid",
            leader_name="leader",
            task="task-1",
            status="in_progress",
        )

        msgs = mailbox.receive("leader")
        assert len(msgs) == 1
        assert msgs[0].type == MessageType.message
        assert msgs[0].from_agent == "worker"
        assert msgs[0].key == "worker_heartbeat"
        assert msgs[0].status == "in_progress"
        assert "task=task-1" in (msgs[0].content or "")
