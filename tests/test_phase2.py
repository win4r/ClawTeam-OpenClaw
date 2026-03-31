"""Tests for Phase 2 features: Idempotency, Cost Dashboard, Circuit Breaker, Retry."""

import time

import pytest

from clawteam.spawn.registry import (
    AgentHealth,
    HealthState,
    get_agent_health,
    get_all_health,
    record_outcome,
)
from clawteam.team.costs import CostEvent, CostStore, CostSummary
from clawteam.team.mailbox import MailboxManager
from clawteam.team.manager import TeamManager
from clawteam.team.models import TaskItem, TeamMessage
from clawteam.templates import AgentDef, RetryConfig


def _create_team(name: str) -> None:
    TeamManager.create_team(name=name, leader_name="leader", leader_id="lid")


# ===========================================================================
# PR-5: Idempotency Key
# ===========================================================================


class TestIdempotencyKeyModels:
    def test_task_item_idempotency_key_default_none(self):
        task = TaskItem(subject="test")
        assert task.idempotency_key is None

    def test_task_item_idempotency_key_set(self):
        task = TaskItem(subject="test", idempotency_key="key-123")
        assert task.idempotency_key == "key-123"

    def test_task_item_alias_roundtrip(self):
        task = TaskItem(subject="test", idempotency_key="abc")
        data = task.model_dump(by_alias=True)
        assert data["idempotencyKey"] == "abc"
        restored = TaskItem.model_validate(data)
        assert restored.idempotency_key == "abc"

    def test_team_message_idempotency_key(self):
        msg = TeamMessage(from_agent="a1", idempotency_key="msg-key")
        assert msg.idempotency_key == "msg-key"
        data = msg.model_dump(by_alias=True)
        assert data["idempotencyKey"] == "msg-key"


class TestIdempotencyKeyTaskStore:
    def test_create_with_key_returns_same_task(self, team_name):
        from clawteam.store.file import FileTaskStore

        store = FileTaskStore(team_name)
        t1 = store.create(subject="do X", idempotency_key="idem-1")
        t2 = store.create(subject="do X again", idempotency_key="idem-1")
        assert t1.id == t2.id  # same task returned
        assert t1.subject == t2.subject

    def test_create_without_key_creates_distinct_tasks(self, team_name):
        from clawteam.store.file import FileTaskStore

        store = FileTaskStore(team_name)
        t1 = store.create(subject="task A")
        t2 = store.create(subject="task B")
        assert t1.id != t2.id

    def test_different_keys_create_different_tasks(self, team_name):
        from clawteam.store.file import FileTaskStore

        store = FileTaskStore(team_name)
        t1 = store.create(subject="X", idempotency_key="k1")
        t2 = store.create(subject="X", idempotency_key="k2")
        assert t1.id != t2.id


class TestIdempotencyKeyMailbox:
    def test_send_with_key_returns_same_message(self, team_name):
        _create_team(team_name)
        mb = MailboxManager(team_name)
        m1 = mb.send(from_agent="a1", to="leader", content="hi", idempotency_key="mk-1")
        m2 = mb.send(from_agent="a1", to="leader", content="hi again", idempotency_key="mk-1")
        assert m1.request_id == m2.request_id
        assert m1.idempotency_key == "mk-1"

    def test_send_without_key_creates_distinct(self, team_name):
        _create_team(team_name)
        mb = MailboxManager(team_name)
        m1 = mb.send(from_agent="a1", to="leader", content="first")
        m2 = mb.send(from_agent="a1", to="leader", content="second")
        assert m1.request_id != m2.request_id


# ===========================================================================
# PR-6: Cost Dashboard MVP
# ===========================================================================


class TestCostEventTaskId:
    def test_cost_event_task_id_default(self):
        e = CostEvent(agent_name="w1")
        assert e.task_id == ""

    def test_cost_event_task_id_set(self):
        e = CostEvent(agent_name="w1", task_id="t-abc")
        assert e.task_id == "t-abc"

    def test_cost_event_alias(self):
        e = CostEvent(agent_name="w1", task_id="t-1")
        data = e.model_dump(by_alias=True)
        assert data["taskId"] == "t-1"


class TestCostSummaryDimensions:
    def test_summary_by_model(self, team_name):
        store = CostStore(team_name)
        store.report(agent_name="a1", model="gpt-4", cost_cents=1.0)
        store.report(agent_name="a2", model="claude-3", cost_cents=2.0)
        store.report(agent_name="a1", model="gpt-4", cost_cents=3.0)

        summary = store.summary()
        assert summary.by_model["gpt-4"] == 4.0
        assert summary.by_model["claude-3"] == 2.0

    def test_summary_by_task(self, team_name):
        store = CostStore(team_name)
        store.report(agent_name="a1", task_id="task-1", cost_cents=5.0)
        store.report(agent_name="a2", task_id="task-2", cost_cents=3.0)
        store.report(agent_name="a1", task_id="task-1", cost_cents=2.0)

        summary = store.summary()
        assert summary.by_task["task-1"] == 7.0
        assert summary.by_task["task-2"] == 3.0

    def test_summary_empty_model_not_in_by_model(self, team_name):
        store = CostStore(team_name)
        store.report(agent_name="a1", cost_cents=1.0)  # no model
        summary = store.summary()
        assert summary.by_model == {}

    def test_summary_empty_task_not_in_by_task(self, team_name):
        store = CostStore(team_name)
        store.report(agent_name="a1", cost_cents=1.0)  # no task_id
        summary = store.summary()
        assert summary.by_task == {}

    def test_summary_model_alias(self):
        s = CostSummary(
            team_name="t",
            by_model={"gpt-4": 5.0},
            by_task={"t1": 3.0},
        )
        data = s.model_dump(by_alias=True)
        assert data["byModel"] == {"gpt-4": 5.0}
        assert data["byTask"] == {"t1": 3.0}


class TestCostRate:
    def test_cost_rate_empty(self, team_name):
        store = CostStore(team_name)
        assert store.cost_rate() == 0.0

    def test_cost_rate_recent_events(self, team_name):
        store = CostStore(team_name)
        store.report(agent_name="a1", cost_cents=10.0)
        rate = store.cost_rate(window_minutes=5)
        assert rate == pytest.approx(2.0, abs=0.5)  # 10 cents / 5 min

    def test_report_with_task_id(self, team_name):
        store = CostStore(team_name)
        event = store.report(agent_name="a1", task_id="t-42", cost_cents=1.0)
        assert event.task_id == "t-42"


# ===========================================================================
# PR-7: Circuit Breaker
# ===========================================================================


class TestAgentHealthModel:
    def test_default_healthy(self):
        h = AgentHealth(agent_name="w1")
        assert h.state == HealthState.healthy
        assert h.quality_score == 1.0
        assert h.consecutive_failures == 0
        assert h.is_accepting_tasks is True

    def test_alias_roundtrip(self):
        h = AgentHealth(agent_name="w1", state=HealthState.degraded, quality_score=0.5)
        data = h.model_dump(by_alias=True)
        assert data["agentName"] == "w1"
        assert data["qualityScore"] == 0.5
        restored = AgentHealth.model_validate(data)
        assert restored.state == HealthState.degraded


class TestRecordOutcome:
    def test_success_keeps_healthy(self, team_name):
        _create_team(team_name)
        h = record_outcome(team_name, "w1", success=True)
        assert h.state == HealthState.healthy
        assert h.total_successes == 1
        assert h.consecutive_failures == 0

    def test_single_failure_degrades(self, team_name):
        _create_team(team_name)
        h = record_outcome(team_name, "w1", success=False)
        assert h.state == HealthState.degraded
        assert h.consecutive_failures == 1

    def test_threshold_failures_open_circuit(self, team_name):
        _create_team(team_name)
        for _ in range(3):
            h = record_outcome(team_name, "w1", success=False, failure_threshold=3)
        assert h.state == HealthState.open
        assert h.consecutive_failures == 3
        assert h.is_accepting_tasks is False

    def test_success_after_failures_resets(self, team_name):
        _create_team(team_name)
        record_outcome(team_name, "w1", success=False)
        record_outcome(team_name, "w1", success=False)
        h = record_outcome(team_name, "w1", success=True)
        assert h.state == HealthState.healthy
        assert h.consecutive_failures == 0

    def test_open_allows_after_cooldown(self, team_name):
        _create_team(team_name)
        for _ in range(3):
            record_outcome(team_name, "w1", success=False, failure_threshold=3, cooldown_seconds=0.01)
        h = get_agent_health(team_name, "w1")
        assert h.state == HealthState.open
        time.sleep(0.02)
        assert h.is_accepting_tasks is True  # cooldown passed

    def test_get_all_health(self, team_name):
        _create_team(team_name)
        record_outcome(team_name, "w1", success=True)
        record_outcome(team_name, "w2", success=False)
        health = get_all_health(team_name)
        assert "w1" in health
        assert "w2" in health
        assert health["w1"].state == HealthState.healthy
        assert health["w2"].state == HealthState.degraded

    def test_quality_score_decreases_on_failure(self, team_name):
        _create_team(team_name)
        h = record_outcome(team_name, "w1", success=False)
        assert h.quality_score == pytest.approx(0.8)
        h = record_outcome(team_name, "w1", success=False)
        assert h.quality_score == pytest.approx(0.6)

    def test_quality_score_increases_on_success(self, team_name):
        _create_team(team_name)
        record_outcome(team_name, "w1", success=False)
        record_outcome(team_name, "w1", success=False)
        h = record_outcome(team_name, "w1", success=True)
        assert h.quality_score == pytest.approx(0.7)


# ===========================================================================
# PR-8: Retry with Backoff
# ===========================================================================


class TestRetryConfig:
    def test_default_values(self):
        rc = RetryConfig()
        assert rc.max_retries == 3
        assert rc.backoff_base_seconds == 1.0
        assert rc.backoff_max_seconds == 30.0

    def test_custom_values(self):
        rc = RetryConfig(max_retries=5, backoff_base_seconds=2.0, backoff_max_seconds=60.0)
        assert rc.max_retries == 5

    def test_agent_def_retry_none_by_default(self):
        ad = AgentDef(name="w1")
        assert ad.retry is None

    def test_agent_def_retry_config(self):
        ad = AgentDef(name="w1", retry=RetryConfig(max_retries=2))
        assert ad.retry is not None
        assert ad.retry.max_retries == 2


class TestSpawnWithRetry:
    def test_success_on_first_try(self):
        from clawteam.spawn import spawn_with_retry

        class FakeBackend:
            def spawn(self, **kwargs):
                return "Agent spawned"

        result = spawn_with_retry(
            FakeBackend(), max_retries=3, backoff_base=0.01,
            command=["test"], agent_name="w1", agent_id="id", agent_type="gp",
            team_name="t",
        )
        assert result == "Agent spawned"

    def test_retries_on_error(self):
        from clawteam.spawn import spawn_with_retry

        call_count = 0

        class FlakyBackend:
            def spawn(self, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count < 3:
                    return "Error: tmux not found"
                return "Agent spawned"

        result = spawn_with_retry(
            FlakyBackend(), max_retries=3, backoff_base=0.01,
            command=["test"], agent_name="w1", agent_id="id", agent_type="gp",
            team_name="t",
        )
        assert result == "Agent spawned"
        assert call_count == 3

    def test_gives_up_after_max_retries(self):
        from clawteam.spawn import spawn_with_retry

        class AlwaysFail:
            def spawn(self, **kwargs):
                return "Error: crash"

        result = spawn_with_retry(
            AlwaysFail(), max_retries=2, backoff_base=0.01,
            command=["test"], agent_name="w1", agent_id="id", agent_type="gp",
            team_name="t",
        )
        assert result.startswith("Error")

    def test_exponential_backoff_timing(self):
        from clawteam.spawn import spawn_with_retry

        timestamps = []

        class TimingBackend:
            def spawn(self, **kwargs):
                timestamps.append(time.monotonic())
                if len(timestamps) < 3:
                    return "Error: fail"
                return "OK"

        spawn_with_retry(
            TimingBackend(), max_retries=3, backoff_base=0.05, backoff_max=1.0,
            command=["test"], agent_name="w1", agent_id="id", agent_type="gp",
            team_name="t",
        )
        assert len(timestamps) == 3
        # Second gap should be roughly 2x the first (exponential)
        gap1 = timestamps[1] - timestamps[0]
        gap2 = timestamps[2] - timestamps[1]
        assert gap2 > gap1 * 1.5  # some tolerance
