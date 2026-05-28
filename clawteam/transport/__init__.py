"""Pluggable transport backends for message delivery."""

from __future__ import annotations

from clawteam.transport.base import Transport

_TRANSPORT_REGISTRY: dict[str, type[Transport]] = {}


def register_transport(name: str, cls: type[Transport]) -> None:
    """Register a custom transport backend (e.g. from a plugin)."""
    _TRANSPORT_REGISTRY[name] = cls


def get_transport(name: str, team_name: str, **kwargs) -> Transport:
    """Factory: create a transport by name."""
    if name in _TRANSPORT_REGISTRY:
        return _TRANSPORT_REGISTRY[name](team_name, **kwargs)
    if name == "p2p":
        from clawteam.transport.p2p import P2PTransport
        return P2PTransport(team_name, **kwargs)
    from clawteam.transport.file import FileTransport
    return FileTransport(team_name)


__all__ = ["Transport", "get_transport", "register_transport"]
