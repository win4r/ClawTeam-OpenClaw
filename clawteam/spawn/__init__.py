"""Spawn backends for launching team agents."""

from __future__ import annotations

from clawteam.platform_compat import default_spawn_backend
from clawteam.spawn.base import SpawnBackend


def get_backend(name: str | None = None) -> SpawnBackend:
    """Factory function to get a spawn backend by name."""
    name = name or default_spawn_backend()
    if name == "subprocess":
        from clawteam.spawn.subprocess_backend import SubprocessBackend
        return SubprocessBackend()
    elif name == "tmux":
        from clawteam.spawn.tmux_backend import TmuxBackend
        return TmuxBackend()
    else:
        raise ValueError(f"Unknown spawn backend: {name}. Available: subprocess, tmux")


__all__ = ["SpawnBackend", "get_backend"]
