"""Tests for clawteam.team.mailbox — MailboxManager send/receive/broadcast."""

import fcntl
import json
from pathlib import Path

from clawteam.team.mailbox import MailboxManager
from clawteam.team.manager import TeamManager
from clawteam.team.models import MessageType, get_data_dir
from clawteam.transport.file import FileTransport


@staticmethod
def _make_mailbox(team_name: str) -> MailboxManager:
    """Create a mailbox with an explicit FileTransport (skip env/config resolution)."""
    transport = FileTransport(team_name)
    return MailboxManager(team_name, transport=transport)


def _inbox_path(team_name: str, agent_name: str) -> Path:
    inbox = get_data_dir() / "teams" / team_name / "inboxes" / agent_name
    inbox.mkdir(parents=True, exist_ok=True)
    return inbox


def _dead_letter_root(team_name: str, agent_name: str) -> Path:
    return get_data_dir() / "teams" / team_name / "dead_letters" / agent_name


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

    def test_peek_skips_corrupt_messages(self, team_name):
        mb = _make_mailbox(team_name)
        mb.send(from_agent="a", to="bob", content="good")

        from clawteam.team.models import get_data_dir

        inbox = get_data_dir() / "teams" / team_name / "inboxes" / "bob"
        (inbox / "msg-corrupt.json").write_text("not valid json", encoding="utf-8")

        peeked = mb.peek("bob")
        assert len(peeked) == 1
        assert peeked[0].content == "good"


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

    def test_broadcast_excludes_namespaced_inboxes(self, team_name):
        TeamManager.create_team(
            name=team_name,
            leader_name="lead",
            leader_id="leader001",
            user="alice",
        )
        TeamManager.add_member(team_name, "worker", agent_id="worker001", user="alice")
        TeamManager.add_member(team_name, "reviewer", agent_id="review001", user="alice")

        mb = _make_mailbox(team_name)
        sent = mb.broadcast(from_agent="worker", content="hi", exclude=["reviewer"])

        recipients = {m.to for m in sent}
        assert "alice_worker" not in recipients
        assert "alice_reviewer" not in recipients
        assert "alice_lead" in recipients

    def test_receive_skips_corrupt_messages(self, team_name):
        mb = _make_mailbox(team_name)
        mb.send(from_agent="a", to="bob", content="good")

        from clawteam.team.models import get_data_dir

        inbox = get_data_dir() / "teams" / team_name / "inboxes" / "bob"
        (inbox / "msg-corrupt.json").write_text("not valid json", encoding="utf-8")

        received = mb.receive("bob")
        assert len(received) == 1
        assert received[0].content == "good"

    def test_broadcast_empty_team(self, team_name):
        mb = _make_mailbox(team_name)
        # no inboxes created, nothing to send to
        sent = mb.broadcast(from_agent="lonely", content="anyone?")
        assert sent == []


class TestReceiveQuarantine:
    def test_receive_quarantines_schema_invalid_message_and_returns_valid_message(self, team_name):
        mb = _make_mailbox(team_name)
        inbox = _inbox_path(team_name, "bob")

        mb.send(from_agent="a", to="bob", content="good")
        (inbox / "msg-invalid.json").write_text(
            json.dumps({"type": "message"}), encoding="utf-8"
        )

        received = mb.receive("bob", limit=10)

        assert [msg.content for msg in received] == ["good"]
        assert list(inbox.glob("msg-*.json")) == []

        dead_letters = _dead_letter_root(team_name, "bob")
        assert dead_letters.exists()
        assert len(list(dead_letters.glob("*.json"))) >= 1
        assert len(list(dead_letters.glob("*.meta.json"))) >= 1

    def test_receive_limit_preserves_current_file_budget_with_invalid_first(self, team_name):
        mb = _make_mailbox(team_name)
        inbox = _inbox_path(team_name, "bob")

        (inbox / "msg-0001-invalid.json").write_text(
            json.dumps({"type": "message"}), encoding="utf-8"
        )
        (inbox / "msg-0002-valid.json").write_text(
            json.dumps(
                {
                    "type": "message",
                    "from": "alice",
                    "to": "bob",
                    "content": "later",
                }
            ),
            encoding="utf-8",
        )

        first = mb.receive("bob", limit=1)
        second = mb.receive("bob", limit=1)

        assert first == []
        assert [msg.content for msg in second] == ["later"]
        dead_letters = _dead_letter_root(team_name, "bob")
        assert dead_letters.exists()

    def test_peek_schema_invalid_message_does_not_quarantine_or_consume(self, team_name):
        mb = _make_mailbox(team_name)
        inbox = _inbox_path(team_name, "bob")

        (inbox / "msg-invalid.json").write_text(
            json.dumps({"type": "message"}), encoding="utf-8"
        )

        peeked = mb.peek("bob")

        assert peeked == []
        assert (inbox / "msg-invalid.json").exists()
        assert not _dead_letter_root(team_name, "bob").exists()

    def test_p2p_offline_fallback_receive_matches_file_quarantine_behavior(self, team_name):
        from clawteam.transport.p2p import P2PTransport

        transport = P2PTransport(team_name)
        mb = MailboxManager(team_name, transport=transport)
        inbox = _inbox_path(team_name, "bob")

        mb.send(from_agent="a", to="bob", content="good")
        (inbox / "msg-invalid.json").write_text(
            json.dumps({"type": "message"}), encoding="utf-8"
        )

        received = mb.receive("bob", limit=10)

        assert [msg.content for msg in received] == ["good"]
        assert list(inbox.glob("msg-*.json")) == []
        assert _dead_letter_root(team_name, "bob").exists()
        transport.close()

    def test_receive_recovers_preclaimed_consumed_message(self, team_name):
        mb = _make_mailbox(team_name)
        inbox = _inbox_path(team_name, "bob")

        (inbox / "msg-0001-valid.json").write_text(
            json.dumps(
                {
                    "type": "message",
                    "from": "alice",
                    "to": "bob",
                    "content": "recovered",
                }
            ),
            encoding="utf-8",
        )
        (inbox / "msg-0001-valid.json").rename(inbox / "msg-0001-valid.consumed")

        received = mb.receive("bob", limit=10)

        assert [msg.content for msg in received] == ["recovered"]

    def test_peek_count_includes_preclaimed_consumed_message(self, team_name):
        mb = _make_mailbox(team_name)
        inbox = _inbox_path(team_name, "bob")

        (inbox / "msg-0001-valid.json").write_text(
            json.dumps(
                {
                    "type": "message",
                    "from": "alice",
                    "to": "bob",
                    "content": "recovered",
                }
            ),
            encoding="utf-8",
        )
        (inbox / "msg-0001-valid.json").rename(inbox / "msg-0001-valid.consumed")

        assert mb.peek_count("bob") == 1

    def test_receive_skips_locked_preclaimed_consumed_message(self, team_name):
        mb = _make_mailbox(team_name)
        inbox = _inbox_path(team_name, "bob")
        consumed = inbox / "msg-0001-valid.consumed"

        consumed.write_text(
            json.dumps(
                {
                    "type": "message",
                    "from": "alice",
                    "to": "bob",
                    "content": "locked",
                }
            ),
            encoding="utf-8",
        )

        with consumed.open("rb") as locked_file:
            fcntl.flock(locked_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            assert mb.receive("bob", limit=10) == []
            assert consumed.exists()

        received = mb.receive("bob", limit=10)
        assert [msg.content for msg in received] == ["locked"]

    def test_peek_and_count_skip_locked_preclaimed_consumed_message(self, team_name):
        mb = _make_mailbox(team_name)
        inbox = _inbox_path(team_name, "bob")
        consumed = inbox / "msg-0001-valid.consumed"

        consumed.write_text(
            json.dumps(
                {
                    "type": "message",
                    "from": "alice",
                    "to": "bob",
                    "content": "locked",
                }
            ),
            encoding="utf-8",
        )

        with consumed.open("rb") as locked_file:
            fcntl.flock(locked_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            assert mb.peek("bob") == []
            assert mb.peek_count("bob") == 0


class TestFileTransport:
    def test_fetch_consume_skips_message_if_claim_fails(self, team_name, monkeypatch):
        transport = FileTransport(team_name)
        transport.deliver("bob", b'{"type":"message","from":"alice","to":"bob","content":"hello"}')

        from clawteam.team.models import get_data_dir

        inbox = get_data_dir() / "teams" / team_name / "inboxes" / "bob"
        message_files = list(inbox.glob("msg-*.json"))
        assert len(message_files) == 1

        original_rename = Path.rename

        def fake_rename(self, target):
            if self == message_files[0]:
                raise OSError("claimed by another consumer")
            return original_rename(self, target)

        monkeypatch.setattr(Path, "rename", fake_rename)

        assert transport.fetch("bob", consume=True) == []
        assert len(list(inbox.glob("msg-*.json"))) == 1


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
