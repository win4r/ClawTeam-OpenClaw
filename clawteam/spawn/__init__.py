"""Spawn backends for launching team agents."""

from __future__ import annotations

import logging
import time

from clawteam.platform_compat import default_spawn_backend, is_windows
from clawteam.spawn.base import SpawnBackend

logger = logging.getLogger(__name__)

_BACKEND_REGISTRY: dict[str, type[SpawnBackend]] = {}


def register_backend(name: str, cls: type[SpawnBackend]) -> None:
    """Register a custom spawn backend (e.g. from a plugin)."""
    _BACKEND_REGISTRY[name] = cls



def normalize_backend_name(name: str | None) -> str:
    """Resolve backend name with a Windows-safe default/fallback."""
    selected = name or default_spawn_backend()
    if is_windows() and selected == "tmux":
        return "subprocess"
    return selected


def get_backend(name: str | None = None) -> SpawnBackend:
    """Factory function to get a spawn backend by name."""
    if name in _BACKEND_REGISTRY:
        return _BACKEND_REGISTRY[name]()
    selected = normalize_backend_name(name)
    if selected == "subprocess":
        from clawteam.spawn.subprocess_backend import SubprocessBackend

        return SubprocessBackend()
    if selected == "tmux":
        from clawteam.spawn.tmux_backend import TmuxBackend

        return TmuxBackend()
    raise ValueError(f"Unknown spawn backend: {selected}. Available: subprocess, tmux")


def spawn_with_retry(
    backend: SpawnBackend,
    max_retries: int = 3,
    backoff_base: float = 1.0,
    backoff_max: float = 30.0,
    **spawn_kwargs,
) -> str:
    """Wrap backend.spawn() with exponential backoff retry.

    Returns the result of a successful spawn, or the last error message.
    """
    last_result = ""
    for attempt in range(max_retries + 1):
        result = backend.spawn(**spawn_kwargs)
        if not result.startswith("Error"):
            return result
        last_result = result
        if attempt < max_retries:
            delay = min(backoff_base * (2 ** attempt), backoff_max)
            logger.warning(
                "Spawn attempt %d/%d failed: %s — retrying in %.1fs",
                attempt + 1, max_retries + 1, result, delay,
            )
            time.sleep(delay)
    return last_result


__all__ = [
    "SpawnBackend",
    "get_backend",
    "normalize_backend_name",
    "register_backend",
    "spawn_with_retry",
]
