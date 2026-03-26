"""Team coordination layer for multi-agent collaboration."""

from importlib import import_module

__all__ = [
    "TeamManager",
    "MailboxManager",
    "TaskStore",
    "PlanManager",
    "LifecycleManager",
    "InboxWatcher",
]


def __getattr__(name: str):
    module_map = {
        "LifecycleManager": ("clawteam.team.lifecycle", "LifecycleManager"),
        "MailboxManager": ("clawteam.team.mailbox", "MailboxManager"),
        "TeamManager": ("clawteam.team.manager", "TeamManager"),
        "PlanManager": ("clawteam.team.plan", "PlanManager"),
        "TaskStore": ("clawteam.team.tasks", "TaskStore"),
        "InboxWatcher": ("clawteam.team.watcher", "InboxWatcher"),
    }
    target = module_map.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = target
    return getattr(import_module(module_name), attr_name)
