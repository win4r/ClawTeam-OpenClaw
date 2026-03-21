"""Spawn backends for launching team agents."""

from __future__ import annotations

import os

from clawteam.spawn.base import SpawnBackend


def normalize_backend_name(name: str | None) -> str:
    """Resolve backend name with a Windows-safe default/fallback."""
    selected = name or ("subprocess" if os.name == "nt" else "tmux")
    if os.name == "nt" and selected == "tmux":
        return "subprocess"
    return selected


def get_backend(name: str = "tmux") -> SpawnBackend:
    """Factory function to get a spawn backend by name."""
    selected = normalize_backend_name(name)
    if selected == "subprocess":
        from clawteam.spawn.subprocess_backend import SubprocessBackend

        return SubprocessBackend()
    if selected == "tmux":
        from clawteam.spawn.tmux_backend import TmuxBackend

        return TmuxBackend()
    raise ValueError(f"Unknown spawn backend: {selected}. Available: subprocess, tmux")


__all__ = ["SpawnBackend", "get_backend", "normalize_backend_name"]
