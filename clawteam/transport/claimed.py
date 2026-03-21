"""Claimed-message helpers for transports that support post-claim ack/quarantine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass
class ClaimedMessage:
    """A claimed message that can be acknowledged or quarantined later."""

    data: bytes
    ack: Callable[[], None]
    quarantine: Callable[[str], None]
