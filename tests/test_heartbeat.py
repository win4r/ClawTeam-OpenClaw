"""Tests for clawteam.team.heartbeat."""
from __future__ import annotations

from datetime import datetime, timezone


def test_write_heartbeat_creates_json_with_required_fields(tmp_path):
    from clawteam.team.heartbeat import read_heartbeat, write_heartbeat

    write_heartbeat(tmp_path, agent="worker1", alive=True, turn_count=3, task_id="t-1")
    hb = read_heartbeat(tmp_path, "worker1")
    assert hb is not None
    assert hb.alive is True
    assert hb.turn_count == 3
    assert hb.task_id == "t-1"
    assert (datetime.now(timezone.utc) - hb.last_turn_at).total_seconds() < 5


def test_read_missing_heartbeat_returns_none(tmp_path):
    from clawteam.team.heartbeat import read_heartbeat

    assert read_heartbeat(tmp_path, "ghost") is None


def test_write_heartbeat_overwrites_atomically(tmp_path):
    from clawteam.team.heartbeat import read_heartbeat, write_heartbeat

    write_heartbeat(tmp_path, agent="w1", alive=True, turn_count=1)
    write_heartbeat(tmp_path, agent="w1", alive=True, turn_count=5)
    assert read_heartbeat(tmp_path, "w1").turn_count == 5


def test_list_heartbeats_returns_all(tmp_path):
    from clawteam.team.heartbeat import list_heartbeats, write_heartbeat

    write_heartbeat(tmp_path, agent="w1", alive=True, turn_count=1)
    write_heartbeat(tmp_path, agent="w2", alive=False, turn_count=7)
    hbs = list_heartbeats(tmp_path)
    assert len(hbs) == 2
    assert {h.agent for h in hbs} == {"w1", "w2"}


def test_list_heartbeats_empty_dir(tmp_path):
    from clawteam.team.heartbeat import list_heartbeats

    assert list_heartbeats(tmp_path) == []


def test_heartbeat_task_id_optional(tmp_path):
    from clawteam.team.heartbeat import read_heartbeat, write_heartbeat

    write_heartbeat(tmp_path, agent="w1", alive=True, turn_count=2)
    assert read_heartbeat(tmp_path, "w1").task_id is None


def test_heartbeat_negative_turn_count_allowed(tmp_path):
    """turn_count=-1 is the tmux pane-focus-in sentinel."""
    from clawteam.team.heartbeat import read_heartbeat, write_heartbeat

    write_heartbeat(tmp_path, agent="w1", alive=True, turn_count=-1)
    assert read_heartbeat(tmp_path, "w1").turn_count == -1
