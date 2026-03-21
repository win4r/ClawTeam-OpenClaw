"""Tests for clawteam.team.mailbox — MailboxManager send/receive/broadcast."""

from clawteam.team.mailbox import MailboxManager
from clawteam.team.models import MessageType
from clawteam.transport.file import FileTransport


@staticmethod
def _make_mailbox(team_name: str) -> MailboxManager:
    """Create a mailbox with an explicit FileTransport (skip env/config resolution)."""
    transport = FileTransport(team_name)
    return MailboxManager(team_name, transport=transport)


class TestSendReceive:
    def test_send_and_receive_single(self, team_name):
        mb = _make_mailbox(team_name)
        mb.send(from_agent="alice", to="bob", content="hey")

        msgs = mb.receive("bob")
        assert len(msgs) == 1
        assert msgs[0].from_agent == "alice"
        assert msgs[0].content == "hey"
        assert msgs[0].type == MessageType.message

    def test_receive_consumes_messages(self, team_name):
        mb = _make_mailbox(team_name)
        mb.send(from_agent="alice", to="bob", content="first")

        msgs = mb.receive("bob")
        assert len(msgs) == 1
        # second receive should be empty
        assert mb.receive("bob") == []

    def test_receive_all_messages_present(self, team_name):
        """All sent messages are received. Ordering is by filename (timestamp+uuid)
        which is mostly FIFO, but messages sent within the same ms can swap."""
        mb = _make_mailbox(team_name)
        for i in range(5):
            mb.send(from_agent="alice", to="bob", content=f"msg-{i}")

        msgs = mb.receive("bob", limit=10)
        contents = sorted(m.content for m in msgs)
        assert contents == sorted(f"msg-{i}" for i in range(5))

    def test_receive_limit(self, team_name):
        mb = _make_mailbox(team_name)
        for i in range(5):
            mb.send(from_agent="a", to="b", content=f"{i}")

        msgs = mb.receive("b", limit=3)
        assert len(msgs) == 3
        # remaining 2 should still be there
        rest = mb.receive("b", limit=10)
        assert len(rest) == 2

    def test_send_with_custom_type(self, team_name):
        mb = _make_mailbox(team_name)
        mb.send(
            from_agent="new-guy",
            to="leader",
            msg_type=MessageType.join_request,
            proposed_name="worker-1",
            capabilities="coding",
        )
        msgs = mb.receive("leader")
        assert msgs[0].type == MessageType.join_request
        assert msgs[0].proposed_name == "worker-1"


class TestPeek:
    def test_peek_does_not_consume(self, team_name):
        mb = _make_mailbox(team_name)
        mb.send(from_agent="a", to="b", content="peeked")

        peeked = mb.peek("b")
        assert len(peeked) == 1
        # still there after peek
        peeked_again = mb.peek("b")
        assert len(peeked_again) == 1

    def test_peek_count(self, team_name):
        mb = _make_mailbox(team_name)
        assert mb.peek_count("bob") == 0
        mb.send(from_agent="a", to="bob", content="1")
        mb.send(from_agent="a", to="bob", content="2")
        assert mb.peek_count("bob") == 2


class TestBroadcast:
    def test_broadcast_to_all_except_sender(self, team_name):
        mb = _make_mailbox(team_name)
        # set up inboxes so list_recipients finds them
        from clawteam.team.models import get_data_dir

        for name in ["alice", "bob", "carol"]:
            inbox = get_data_dir() / "teams" / team_name / "inboxes" / name
            inbox.mkdir(parents=True, exist_ok=True)

        sent = mb.broadcast(from_agent="alice", content="announcement")
        recipients = {m.to for m in sent}
        assert "alice" not in recipients  # sender excluded
        assert "bob" in recipients
        assert "carol" in recipients

    def test_broadcast_with_exclude(self, team_name):
        mb = _make_mailbox(team_name)
        from clawteam.team.models import get_data_dir

        for name in ["alice", "bob", "carol", "dave"]:
            inbox = get_data_dir() / "teams" / team_name / "inboxes" / name
            inbox.mkdir(parents=True, exist_ok=True)

        sent = mb.broadcast(from_agent="alice", content="hi", exclude=["carol"])
        recipients = {m.to for m in sent}
        assert "alice" not in recipients
        assert "carol" not in recipients
        assert "bob" in recipients
        assert "dave" in recipients

    def test_broadcast_empty_team(self, team_name):
        mb = _make_mailbox(team_name)
        # no inboxes created, nothing to send to
        sent = mb.broadcast(from_agent="lonely", content="anyone?")
        assert sent == []


class TestEventLog:
    def test_send_logs_event(self, team_name):
        mb = _make_mailbox(team_name)
        mb.send(from_agent="a", to="b", content="logged")

        events = mb.get_event_log()
        assert len(events) == 1
        assert events[0].content == "logged"

    def test_broadcast_logs_per_recipient(self, team_name):
        mb = _make_mailbox(team_name)
        from clawteam.team.models import get_data_dir

        for name in ["x", "y"]:
            inbox = get_data_dir() / "teams" / team_name / "inboxes" / name
            inbox.mkdir(parents=True, exist_ok=True)

        mb.broadcast(from_agent="z", content="bc")
        # z excluded from recipients, so 2 events (x and y)
        events = mb.get_event_log()
        assert len(events) == 2

    def test_event_log_limit(self, team_name):
        mb = _make_mailbox(team_name)
        for i in range(20):
            mb.send(from_agent="a", to="b", content=f"{i}")

        events = mb.get_event_log(limit=5)
        assert len(events) == 5


class TestAcknowledgement:
    def test_receive_can_emit_ack_to_sender(self, team_name):
        mb = _make_mailbox(team_name)
        sent = mb.send(from_agent="alice", to="bob", content="wake up", key="task-wake:t1")

        received = mb.receive("bob", acknowledge=True)
        assert [msg.request_id for msg in received] == [sent.request_id]

        ack_messages = mb.receive("alice")
        assert len(ack_messages) == 1
        ack = ack_messages[0]
        assert ack.type == MessageType.ack
        assert ack.request_id == sent.request_id
        assert ack.from_agent == "bob"
        assert ack.to == "alice"
        assert ack.key == "task-wake:t1"
        assert ack.status == "acknowledged"

    def test_receive_matching_acks_only_selected_task_wake(self, team_name):
        mb = _make_mailbox(team_name)
        wake_1 = mb.send(
            from_agent="leader",
            to="worker",
            content="wake task 1",
            key="task-wake:t1",
            last_task="t1",
        )
        wake_2 = mb.send(
            from_agent="leader",
            to="worker",
            content="wake task 2",
            key="task-wake:t2",
            last_task="t2",
        )

        matched = mb.receive_matching(
            "worker",
            lambda msg: msg.last_task == "t1",
            acknowledge=True,
        )

        assert [msg.request_id for msg in matched] == [wake_1.request_id]
        remaining = mb.peek("worker")
        assert [msg.request_id for msg in remaining] == [wake_2.request_id]

        ack_messages = mb.receive("leader")
        assert [msg.type for msg in ack_messages] == [MessageType.ack]
        assert ack_messages[0].request_id == wake_1.request_id

    def test_ack_event_is_logged_and_carries_task_context(self, team_name):
        mb = _make_mailbox(team_name)
        sent = mb.send(
            from_agent="leader",
            to="worker",
            content="Start task now",
            key="task-wake:task-123",
            last_task="task-123",
            status="pending",
        )

        mb.receive("worker", acknowledge=True)

        events = mb.get_event_log(limit=10)
        sent_event = next(evt for evt in events if evt.request_id == sent.request_id and evt.type == MessageType.message)
        ack_event = next(evt for evt in events if evt.request_id == sent.request_id and evt.type == MessageType.ack)
        assert sent_event.status == "pending"
        assert ack_event.last_task == "task-123"
        assert ack_event.status == "acknowledged"
