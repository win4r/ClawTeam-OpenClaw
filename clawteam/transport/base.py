"""Abstract base class for message transport."""

from __future__ import annotations

from abc import ABC, abstractmethod


class Transport(ABC):
    """Transport interface for delivering and fetching raw message bytes."""

    @abstractmethod
    def deliver(self, recipient: str, data: bytes) -> None:
        """Deliver message bytes to a recipient's inbox."""

    @abstractmethod
    def fetch(self, agent_name: str, limit: int = 10, consume: bool = True) -> list[bytes]:
        """Fetch opaque message bytes from a transport-specific inbox.

        Transports only move raw bytes. Higher-level callers such as
        ``MailboxManager.receive()`` are responsible for parsing those bytes
        into ``TeamMessage`` objects and deciding whether malformed payloads
        should be quarantined.
        """

    @abstractmethod
    def count(self, agent_name: str) -> int:
        """Return the number of pending messages."""

    @abstractmethod
    def list_recipients(self) -> list[str]:
        """List all known recipient names (for broadcast)."""

    def close(self) -> None:
        """Release resources. Default is no-op."""
