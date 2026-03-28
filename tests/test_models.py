"""Tests for clawteam.team.models — Pydantic models and data types."""

import json

from clawteam.team.models import (
    MemberStatus,
    MessageType,
    TaskItem,
    TaskStatus,
    TeamConfig,
    TeamMember,
    TeamMessage,
)


class TestTaskItem:
    def test_defaults(self):
        t = TaskItem(subject="do something")
        assert t.subject == "do something"
        assert t.status == TaskStatus.pending
        assert t.owner == ""
        assert t.blocks == []
        assert t.blocked_by == []
        assert len(t.id) == 8  # uuid hex[:8]

    def test_alias_serialization(self):
        t = TaskItem(subject="x", blocked_by=["a"], locked_by="agent-1")
        data = json.loads(t.model_dump_json(by_alias=True))
        assert "blockedBy" in data
        assert "lockedBy" in data
        assert "completedAt" in data

    def test_populate_by_name(self):
        """Should accept both field names and aliases."""
        t1 = TaskItem(subject="x", blocked_by=["a"])
        t2 = TaskItem(subject="x", blockedBy=["a"])
        assert t1.blocked_by == t2.blocked_by

    def test_metadata_dict(self):
        t = TaskItem(subject="x", metadata={"priority": "high", "labels": ["bug"]})
        assert t.metadata["priority"] == "high"

    def test_roundtrip_via_json(self):
        original = TaskItem(subject="deploy", description="ship it", owner="alice")
        dumped = original.model_dump_json(by_alias=True)
        restored = TaskItem.model_validate_json(dumped)
        assert restored.subject == original.subject
        assert restored.owner == original.owner


class TestTeamMember:
    def test_auto_agent_id(self):
        m = TeamMember(name="worker-1")
        assert len(m.agent_id) == 12

    def test_alias_roundtrip(self):
        m = TeamMember(name="lead", agent_type="leader", user="bob")
        data = json.loads(m.model_dump_json(by_alias=True))
        assert data["agentType"] == "leader"
        restored = TeamMember.model_validate(data)
        assert restored.agent_type == "leader"


class TestTeamConfig:
    def test_basic_creation(self):
        member = TeamMember(name="lead", agent_id="abc123")
        cfg = TeamConfig(name="alpha", members=[member], lead_agent_id="abc123")
        assert cfg.name == "alpha"
        assert len(cfg.members) == 1
        assert cfg.budget_cents == 0.0

    def test_alias_fields(self):
        cfg = TeamConfig(name="t", lead_agent_id="x", budget_cents=500.0)
        data = json.loads(cfg.model_dump_json(by_alias=True))
        assert data["leadAgentId"] == "x"
        assert data["budgetCents"] == 500.0


class TestTeamMessage:
    def test_basic_message(self):
        msg = TeamMessage(from_agent="alice", to="bob", content="hello")
        assert msg.type == MessageType.message
        assert msg.from_agent == "alice"
        assert msg.to == "bob"

    def test_from_alias(self):
        """'from' is a Python keyword so it's aliased to from_agent."""
        data = {"from": "alice", "to": "bob", "content": "hi", "type": "message"}
        msg = TeamMessage.model_validate(data)
        assert msg.from_agent == "alice"

    def test_serialization_uses_from_alias(self):
        msg = TeamMessage(from_agent="a", to="b", content="c")
        dumped = json.loads(msg.model_dump_json(by_alias=True, exclude_none=True))
        assert "from" in dumped
        # from_agent should not appear as a key
        assert "from_agent" not in dumped

    def test_join_request_fields(self):
        msg = TeamMessage(
            type=MessageType.join_request,
            from_agent="new-agent",
            to="leader",
            proposed_name="worker-1",
            capabilities="coding, testing",
        )
        assert msg.proposed_name == "worker-1"
        assert msg.capabilities == "coding, testing"

    def test_exclude_none_drops_optional_fields(self):
        msg = TeamMessage(from_agent="a", to="b", content="hi")
        dumped = json.loads(msg.model_dump_json(by_alias=True, exclude_none=True))
        # optional fields that weren't set should be gone
        assert "plan" not in dumped
        assert "feedback" not in dumped
        assert "assignedName" not in dumped


class TestEnums:
    def test_task_status_values(self):
        assert TaskStatus.pending.value == "pending"
        assert TaskStatus.blocked.value == "blocked"
        assert TaskStatus.in_progress.value == "in_progress"
        assert TaskStatus.completed.value == "completed"
        assert TaskStatus.failed.value == "failed"

    def test_member_status_values(self):
        assert MemberStatus.active.value == "active"
        assert MemberStatus.shutdown.value == "shutdown"

    def test_message_type_values(self):
        # just spot check a few
        assert MessageType.broadcast.value == "broadcast"
        assert MessageType.join_request.value == "join_request"
        assert MessageType.idle.value == "idle"
