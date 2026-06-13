"""Detect when an LLM agent is asking for permission to continue.

Regex bundle ported from:
  oh-my-codex/src/scripts/notify-hook/auto-nudge.ts:308-366 (PERMISSION_SEEKING_STALL_PATTERNS)
"""
from __future__ import annotations

import hashlib
import re

# Patterns ported verbatim from the TS PERMISSION_SEEKING_STALL_PATTERNS array.
# Each plain-string pattern is anchored with \b and compiled re.IGNORECASE.
_PERMISSION_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bif\s+you\s+want\b",
        r"\bwould\s+you\s+like\b",
        r"\bshall\s+i\b",
        r"\bshould\s+i\b",
        r"\bdo\s+you\s+want\s+me\s+to\b",
        r"\bdo\s+you\s+want\b",
        r"\bwant\s+me\s+to\b",
        r"\blet\s+me\s+know\s+if\b",
        r"\blet\s+me\s+know\b",
        r"\bjust\s+let\s+me\s+know\b",
        r"\bi\s+can\s+also\b",
        r"\bi\s+could\s+also\b",
        r"\bnext\s+i\s+can\b",
        r"\bwhenever\s+you\b",
        r"\bsay\s+go\b",
        r"\bsay\s+yes\b",
        r"\btype\s+continue\b",
        r"\bproceed\s+from\s+here\b",
    )
)

# Inspect only the tail of the text to avoid false positives in long outputs.
_TAIL_CHARS = 800


def is_permission_seeking(text: str) -> bool:
    """Return True if *text* ends with a permission-seeking phrase.

    Only the last ``_TAIL_CHARS`` characters (last 3 non-empty lines) are
    scanned, matching the normalisation used in oh-my-codex.
    """
    if not text:
        return False
    tail = text[-_TAIL_CHARS:]
    lines = [ln for ln in tail.splitlines() if ln.strip()]
    last_lines = "\n".join(lines[-3:])
    return any(p.search(last_lines) for p in _PERMISSION_PATTERNS)


# ---------------------------------------------------------------------------
# Task 2.2 — NudgeTracker: per-worker stall-signature dedup
# ---------------------------------------------------------------------------

def _signature(text: str) -> str:
    """sha1 of normalised tail — lowercase, whitespace-collapsed, last 200 chars."""
    tail = text[-200:].lower()
    collapsed = " ".join(tail.split())
    return hashlib.sha1(collapsed.encode()).hexdigest()


class NudgeTracker:
    """Deduplicate auto-nudges by stall-signature per worker.

    Single-threaded use only (owned by LeaderWatcher loop — see plan thread-safety note).
    """

    def __init__(self) -> None:
        self._last_sig: dict[str, str] = {}

    def should_nudge(self, agent: str, text: str) -> bool:
        """Return True and record signature if this text is a new stall for *agent*."""
        sig = _signature(text)
        if self._last_sig.get(agent) == sig:
            return False
        self._last_sig[agent] = sig
        return True
