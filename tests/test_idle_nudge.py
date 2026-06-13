"""Tests for the idle-pane detector module."""

from __future__ import annotations

import time

import pytest

# ---------------------------------------------------------------------------
# pane_looks_idle — parametrized truth table
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text,expected",
    [
        # Shell prompts → idle
        ("some output\n$ ", True),
        ("output line\n❯ ", True),
        ("root output\n# ", True),
        ("some output\n> ", True),
        # Active task markers → not idle
        ("working on it ⚙ ...", False),
        ("Running tool foo ...", False),
        ("Thinking about next step", False),
        ("tool_use_id abc123 executing", False),
        # Edge cases
        ("", False),
        ("just some text without prompt", False),
        # Codex review fix: ANSI color codes around prompt must not block match
        ("output\n\x1b[32m$ \x1b[0m", True),
        ("output\n\x1b[1;31muser@host:~$ \x1b[0m", True),
        # Codex review fix: long mid-stream line ending in '>' must NOT match
        # (e.g. a tool output line that happens to contain '>' near the end)
        (
            "some intermediate diagnostic line that is way too long to be a "
            "real shell prompt and happens to terminate with a greater-than "
            "character even though it is plainly not an idle prompt >",
            False,
        ),
    ],
)
def test_pane_looks_idle(text: str, expected: bool) -> None:
    from clawteam.harness.idle_nudge import pane_looks_idle

    assert pane_looks_idle(text) is expected


# ---------------------------------------------------------------------------
# IdleNudgeTracker
# ---------------------------------------------------------------------------


def test_tracker_no_nudge_within_scan_throttle() -> None:
    """Second call within 5 s scan throttle returns False (not yet ready)."""
    from clawteam.harness.idle_nudge import IdleNudgeTracker

    tracker = IdleNudgeTracker()
    # Force last_scan_at into the future to simulate throttle still active
    tracker.last_scan_at = time.monotonic() + 100.0
    assert tracker.should_scan() is False


def test_tracker_ready_to_scan_after_throttle() -> None:
    """First call (no prior scan) is immediately ready."""
    from clawteam.harness.idle_nudge import IdleNudgeTracker

    tracker = IdleNudgeTracker()
    assert tracker.should_scan() is True


def test_tracker_grace_period_blocks_nudge() -> None:
    """Nudge is suppressed when pane first went idle < 30 s ago."""
    from clawteam.harness.idle_nudge import IdleNudgeTracker

    tracker = IdleNudgeTracker()
    pane_id = "w1"
    # Record idle start as "just now"
    tracker.first_idle_at[pane_id] = time.monotonic()
    assert tracker.should_nudge(pane_id) is False


def test_tracker_nudge_allowed_after_grace() -> None:
    """Nudge is allowed when pane has been idle > 30 s."""
    from clawteam.harness.idle_nudge import IdleNudgeTracker

    tracker = IdleNudgeTracker()
    pane_id = "w1"
    # Simulate pane went idle 31 s ago
    tracker.first_idle_at[pane_id] = time.monotonic() - 31.0
    assert tracker.should_nudge(pane_id) is True


def test_tracker_max_nudges_enforced() -> None:
    """No nudge beyond max (3) per pane."""
    from clawteam.harness.idle_nudge import IdleNudgeTracker

    tracker = IdleNudgeTracker()
    pane_id = "w2"
    tracker.first_idle_at[pane_id] = time.monotonic() - 31.0
    tracker.nudge_count[pane_id] = 3  # already at max
    assert tracker.should_nudge(pane_id) is False


def test_tracker_record_nudge_increments_count() -> None:
    """record_nudge increments the per-pane nudge counter."""
    from clawteam.harness.idle_nudge import IdleNudgeTracker

    tracker = IdleNudgeTracker()
    pane_id = "w3"
    tracker.record_nudge(pane_id)
    tracker.record_nudge(pane_id)
    assert tracker.nudge_count[pane_id] == 2


def test_tracker_reset_on_active() -> None:
    """reset_pane clears first_idle_at and nudge_count for a pane."""
    from clawteam.harness.idle_nudge import IdleNudgeTracker

    tracker = IdleNudgeTracker()
    pane_id = "w4"
    tracker.first_idle_at[pane_id] = time.monotonic() - 60.0
    tracker.nudge_count[pane_id] = 2
    tracker.reset_pane(pane_id)
    assert pane_id not in tracker.first_idle_at
    assert tracker.nudge_count.get(pane_id, 0) == 0


def test_tracker_mark_scan_updates_timestamp() -> None:
    """mark_scan records the current monotonic time."""
    from clawteam.harness.idle_nudge import IdleNudgeTracker

    tracker = IdleNudgeTracker()
    before = time.monotonic()
    tracker.mark_scan()
    assert tracker.last_scan_at >= before


def test_tracker_nudge_gap_suppresses_back_to_back_nudges() -> None:
    """Codex review of PR #12: without an inter-nudge cooldown, after grace
    expires the leader's 5 s cycle would fire all 3 nudges in 10 s. The
    nudge_gap (default = grace = 30 s) must keep them spaced.
    """
    from clawteam.harness.idle_nudge import IdleNudgeTracker

    tracker = IdleNudgeTracker()
    pane_id = "w-back-to-back"
    # Pane went idle long enough ago for grace to be satisfied
    tracker.first_idle_at[pane_id] = time.monotonic() - 31.0

    assert tracker.should_nudge(pane_id) is True
    tracker.record_nudge(pane_id)
    # Immediately try again — must be blocked by nudge_gap
    assert tracker.should_nudge(pane_id) is False
    # Simulate gap elapsed (default gap = grace = 30 s)
    tracker.last_nudge_at[pane_id] = time.monotonic() - 31.0
    assert tracker.should_nudge(pane_id) is True


def test_tracker_reset_pane_clears_last_nudge_at() -> None:
    """reset_pane must also clear the new last_nudge_at entry."""
    from clawteam.harness.idle_nudge import IdleNudgeTracker

    tracker = IdleNudgeTracker()
    pane_id = "w-reset"
    tracker.first_idle_at[pane_id] = time.monotonic() - 60.0
    tracker.nudge_count[pane_id] = 1
    tracker.last_nudge_at[pane_id] = time.monotonic() - 5.0
    tracker.reset_pane(pane_id)
    assert pane_id not in tracker.first_idle_at
    assert pane_id not in tracker.nudge_count
    assert pane_id not in tracker.last_nudge_at
