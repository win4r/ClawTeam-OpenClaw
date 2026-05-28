"""Global EventBus singleton for ClawTeam."""

from __future__ import annotations

from clawteam.events.bus import EventBus

_bus: EventBus | None = None
_initialized: bool = False


def get_event_bus() -> EventBus:
    """Return the global EventBus singleton.

    On first call, loads hooks from config. Subsequent calls return the
    same instance without re-loading.
    """
    global _bus, _initialized
    if _bus is None:
        _bus = EventBus()
    if not _initialized:
        _initialized = True
        _load_hooks_from_config(_bus)
    return _bus


def reset_event_bus() -> None:
    """Reset the global bus (for testing)."""
    global _bus, _initialized
    if _bus is not None:
        _bus.clear()
    _bus = None
    _initialized = False


def _load_hooks_from_config(bus: EventBus) -> None:
    """Load hooks from the user's ClawTeamConfig."""
    try:
        from clawteam.config import load_config
        cfg = load_config()
        hooks = getattr(cfg, "hooks", None)
        if hooks:
            from clawteam.events.hooks import HookManager
            mgr = HookManager(bus)
            mgr.load_hooks(hooks)
    except Exception:
        pass  # config may not exist yet
