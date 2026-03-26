import time

import pytest

from clawteam.team.leader_loop import LeaderLoop, LeaderLoopConfig
from clawteam.team.models import TaskItem, TaskStatus


class FakeMailbox:
    def __init__(self):
        self.sent = []
        self._msgs = []

    def receive(self, inbox: str, limit: int = 50):
        out = self._msgs[:limit]
        self._msgs = self._msgs[limit:]
        return out

    def send(self, from_agent: str, to: str, content: str):
        self.sent.append({"from": from_agent, "to": to, "content": content})


class FakeTaskStore:
    def __init__(self, tasks):
        self._tasks = tasks

    def list_tasks(self):
        return list(self._tasks)


@pytest.fixture
def fixed_time(monkeypatch):
    # Make time deterministic
    t = {"now": 1_700_000_000.0, "mono": 0.0}

    def fake_time():
        return t["now"]

    def fake_monotonic():
        return t["mono"]

    def advance(seconds: float):
        t["now"] += seconds
        t["mono"] += seconds

    monkeypatch.setattr(time, "time", fake_time)
    monkeypatch.setattr(time, "monotonic", fake_monotonic)
    return advance


def _task_pending(task_id="t1", owner="a1", created_at=None):
    t = TaskItem(subject="S", owner=owner)
    t.id = task_id
    t.status = TaskStatus.pending
    if created_at:
        t.created_at = created_at
    return t


def _task_in_progress(task_id="t2", owner="a2", started_at=None, created_at=None):
    t = TaskItem(subject="S2", owner=owner)
    t.id = task_id
    t.status = TaskStatus.in_progress
    if started_at:
        t.started_at = started_at
    if created_at:
        t.created_at = created_at
    return t


def test_ping_triggers_after_ping_after(fixed_time, monkeypatch):
    # created 40s ago -> should ping when ping_after=30
    created_iso = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.time() - 40))
    task = _task_pending(created_at=created_iso)

    mb = FakeMailbox()
    store = FakeTaskStore([task])

    cfg = LeaderLoopConfig(poll_interval=0.0, ping_after=30.0, nudge_after=9999, timeout=0.0)
    loop = LeaderLoop(team_name="t", leader_inbox="leader", mailbox=mb, task_store=store, cfg=cfg)

    # Prevent sleep from blocking
    monkeypatch.setattr(time, "sleep", lambda *_: None)

    loop.run()

    assert len(mb.sent) == 1
    assert mb.sent[0]["to"] == "a1"
    assert "PING" in mb.sent[0]["content"]


def test_nudge_triggers_after_nudge_after(fixed_time, monkeypatch):
    started_iso = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.time() - 400))
    task = _task_in_progress(started_at=started_iso)

    mb = FakeMailbox()
    store = FakeTaskStore([task])

    cfg = LeaderLoopConfig(poll_interval=0.0, ping_after=9999, nudge_after=180.0, timeout=0.0)
    loop = LeaderLoop(team_name="t", leader_inbox="leader", mailbox=mb, task_store=store, cfg=cfg)

    monkeypatch.setattr(time, "sleep", lambda *_: None)
    loop.run()

    assert len(mb.sent) == 1
    assert mb.sent[0]["to"] == "a2"
    assert "NUDGE" in mb.sent[0]["content"]


def test_timeout_exits_loop(fixed_time, monkeypatch):
    # no tasks; just ensure returns when timeout hits
    mb = FakeMailbox()
    store = FakeTaskStore([])

    # timeout=0 means immediate exit on first check
    cfg = LeaderLoopConfig(poll_interval=9999, timeout=0.0)
    loop = LeaderLoop(team_name="t", leader_inbox="leader", mailbox=mb, task_store=store, cfg=cfg)

    monkeypatch.setattr(time, "sleep", lambda *_: None)
    loop.run()

    assert mb.sent == []


def test_dedup_prevents_spam(fixed_time, monkeypatch):
    created_iso = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.time() - 60))
    task = _task_pending(created_at=created_iso)

    mb = FakeMailbox()
    store = FakeTaskStore([task])

    # Allow multiple iterations: stop after 2 seconds monotonic
    cfg = LeaderLoopConfig(poll_interval=0.0, ping_after=30.0, nudge_after=9999, timeout=2.0)
    loop = LeaderLoop(team_name="t", leader_inbox="leader", mailbox=mb, task_store=store, cfg=cfg)

    # Each loop sleep advances time a bit (simulate polling)
    def fake_sleep(_):
        fixed_time(1.0)

    monkeypatch.setattr(time, "sleep", fake_sleep)
    loop.run()

    # With dedup, even though we loop twice, we should not send more than 1 ping
    assert len([m for m in mb.sent if "PING" in m["content"]]) == 1


def test_ping_with_z_suffix_timestamp(monkeypatch):
    # Regression: ISO strings with trailing 'Z' should be parsed and trigger ping.
    now = 1_700_000_000.0
    monkeypatch.setattr(time, "time", lambda: now)
    monkeypatch.setattr(time, "monotonic", lambda: 0.0)
    monkeypatch.setattr(time, "sleep", lambda *_: None)

    created_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now - 61))
    task = _task_pending(created_at=created_iso)

    mb = FakeMailbox()
    store = FakeTaskStore([task])

    cfg = LeaderLoopConfig(poll_interval=0.0, ping_after=30.0, nudge_after=9999, timeout=0.0)
    loop = LeaderLoop(team_name="t", leader_inbox="leader", mailbox=mb, task_store=store, cfg=cfg)

    loop.run()

    assert len(mb.sent) == 1
    assert "PING" in mb.sent[0]["content"]
