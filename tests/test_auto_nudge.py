"""Tests for harness/auto_nudge.py — permission-seeking detector + NudgeTracker."""
import pytest

# ---------------------------------------------------------------------------
# Task 2.1 — is_permission_seeking regex detector
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("Would you like me to continue with the refactor?", True),
    ("Shall I proceed with the next step?", True),
    ("If you want, I can implement option B.", True),
    ("Just let me know how you want to handle this.", True),
    ("Do you want me to continue?", True),
    ("Should I move forward with the migration?", True),
    ("I have completed the task.", False),
    ("Running tests now.", False),
    ("```python\nprint('hi')\n```", False),
    ("Error: file not found", False),
])
def test_is_permission_seeking(text, expected):
    from clawteam.harness.auto_nudge import is_permission_seeking
    assert is_permission_seeking(text) is expected


# ---------------------------------------------------------------------------
# Task 2.2 — NudgeTracker stall-signature dedup
# ---------------------------------------------------------------------------

def test_nudge_tracker_skips_same_signature_twice():
    from clawteam.harness.auto_nudge import NudgeTracker
    t = NudgeTracker()
    assert t.should_nudge("worker1", "shall I proceed?") is True
    assert t.should_nudge("worker1", "shall I proceed?") is False


def test_nudge_tracker_nudges_again_after_signature_changes():
    from clawteam.harness.auto_nudge import NudgeTracker
    t = NudgeTracker()
    t.should_nudge("worker1", "shall I proceed?")
    assert t.should_nudge("worker1", "should I continue with the refactor?") is True


def test_nudge_tracker_independent_per_worker():
    from clawteam.harness.auto_nudge import NudgeTracker
    t = NudgeTracker()
    assert t.should_nudge("worker1", "shall I proceed?") is True
    # Same text but different worker — must nudge
    assert t.should_nudge("worker2", "shall I proceed?") is True


def test_nudge_tracker_fresh_instance_always_nudges():
    from clawteam.harness.auto_nudge import NudgeTracker
    t = NudgeTracker()
    assert t.should_nudge("worker1", "shall I proceed?") is True
