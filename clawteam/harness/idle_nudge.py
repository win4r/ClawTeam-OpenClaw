"""Detect worker panes idle at a shell prompt (no active task).

Single-threaded use only. Wiring into LeaderWatcher happens in Stream H.
"""

from __future__ import annotations

import re
import time
from typing import Dict

# CSI escape sequences (ANSI color/cursor codes). Stripped before prompt match
# because real terminal panes emit `\x1b[32m$ \x1b[0m`-style prompts.
_ANSI_CSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_SHELL_PROMPT_RE = re.compile(r"[\$#❯>]\s*$")
_ACTIVE_TASK_MARKERS = ("Running", "Thinking", "tool_use_id", "⚙")
_PROMPT_LINE_MAX_LEN = 120  # last-line length cap; longer lines aren't prompts

_SCAN_THROTTLE_S: float = 5.0   # minimum seconds between scans
_GRACE_S: float = 30.0          # seconds a pane must be idle before first nudge
_MAX_NUDGES: int = 3            # maximum nudges per pane before giving up


def _last_non_empty_line(text: str) -> str:
    for ln in reversed(text.splitlines()):
        if ln.strip():
            return ln
    return ""


def pane_looks_idle(text: str) -> bool:
    """Return True when *text* shows a shell prompt with no active-task marker.

    Strips ANSI CSI escape sequences first, then rejects on any active-task
    marker in the last 400 chars, then requires the last non-empty line to be
    short (<=200 chars) and end in a prompt char. The length cap prevents
    mid-stream output like 'Running tool foo >' from masquerading as a prompt.
    """
    if not text:
        return False
    text = _ANSI_CSI_RE.sub("", text)
    tail = text[-400:]
    if any(m in tail for m in _ACTIVE_TASK_MARKERS):
        return False
    last_line = _last_non_empty_line(text)
    if not last_line or len(last_line) > _PROMPT_LINE_MAX_LEN:
        return False
    return bool(_SHELL_PROMPT_RE.search(last_line))


class IdleNudgeTracker:
    """Track per-pane idle state with scan throttle, grace period, and nudge cap.

    Attributes are public so callers (and tests) can inject timestamps directly.
    """

    def __init__(
        self,
        scan_throttle: float = _SCAN_THROTTLE_S,
        grace: float = _GRACE_S,
        max_nudges: int = _MAX_NUDGES,
        nudge_gap: float | None = None,
    ) -> None:
        self.scan_throttle = scan_throttle
        self.grace = grace
        self.max_nudges = max_nudges
        # Minimum spacing between consecutive nudges to the same pane.
        # Defaults to `grace` so 3 nudges over 90 s instead of 10 s.
        self.nudge_gap = grace if nudge_gap is None else nudge_gap

        self.last_scan_at: float = float("-inf")
        # pane_id → monotonic time when pane first appeared idle
        self.first_idle_at: Dict[str, float] = {}
        # pane_id → number of nudges sent so far
        self.nudge_count: Dict[str, int] = {}
        # pane_id → monotonic time of most recent nudge
        self.last_nudge_at: Dict[str, float] = {}

    # ------------------------------------------------------------------
    # Scan-level helpers
    # ------------------------------------------------------------------

    def should_scan(self) -> bool:
        """True when enough time has elapsed since the last scan."""
        return (time.monotonic() - self.last_scan_at) >= self.scan_throttle

    def mark_scan(self) -> None:
        """Record that a scan just happened."""
        self.last_scan_at = time.monotonic()

    # ------------------------------------------------------------------
    # Per-pane helpers
    # ------------------------------------------------------------------

    def mark_idle(self, pane_id: str) -> None:
        """Record that *pane_id* looks idle (called when pane_looks_idle is True).

        Only sets first_idle_at if not already tracking this pane.
        """
        if pane_id not in self.first_idle_at:
            self.first_idle_at[pane_id] = time.monotonic()

    def should_nudge(self, pane_id: str) -> bool:
        """True when a nudge should be sent to *pane_id*.

        Requires:
        - pane has been idle for at least *grace* seconds
        - at least *nudge_gap* seconds elapsed since last nudge to this pane
        - nudge count has not reached *max_nudges*
        """
        if self.nudge_count.get(pane_id, 0) >= self.max_nudges:
            return False
        first_idle = self.first_idle_at.get(pane_id)
        if first_idle is None:
            return False
        now = time.monotonic()
        if (now - first_idle) < self.grace:
            return False
        last_nudge = self.last_nudge_at.get(pane_id)
        if last_nudge is not None and (now - last_nudge) < self.nudge_gap:
            return False
        return True

    def record_nudge(self, pane_id: str) -> None:
        """Increment the nudge counter and timestamp for *pane_id*."""
        self.nudge_count[pane_id] = self.nudge_count.get(pane_id, 0) + 1
        self.last_nudge_at[pane_id] = time.monotonic()

    def reset_pane(self, pane_id: str) -> None:
        """Clear idle tracking for *pane_id* (pane became active again)."""
        self.first_idle_at.pop(pane_id, None)
        self.nudge_count.pop(pane_id, None)
        self.last_nudge_at.pop(pane_id, None)
