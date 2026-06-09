"""Hook commands for clawteam."""

from __future__ import annotations

import typer

from clawteam.cli._helpers import (
    console,
)

hook_app = typer.Typer(help="Event hook management")


@hook_app.command("list")
def hook_list(
    as_json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """List all configured hooks."""
    from clawteam.config import load_config

    cfg = load_config()
    hooks = cfg.hooks

    def _human() -> None:
        if not hooks:
            console.print("[dim]No hooks configured.[/dim]")
            return
        for i, h in enumerate(hooks, 1):
            status = "[green]enabled[/green]" if h.enabled else "[red]disabled[/red]"
            console.print(f"  {i}. [bold]{h.event}[/bold] → {h.action}: {h.command}  ({status})")

    def _json() -> None:
        import json as _json
        console.print(_json.dumps([h.model_dump() for h in hooks], indent=2))

    (_json if as_json else _human)()


@hook_app.command("add")
def hook_add(
    event: str = typer.Option(..., "--event", "-e", help="Event type (e.g. WorkerExit)"),
    action: str = typer.Option("shell", "--action", "-a", help="shell or python"),
    command: str = typer.Option(..., "--command", "-c", help="Shell command or Python dotted path"),
    priority: int = typer.Option(0, "--priority", "-p"),
) -> None:
    """Add a new event hook to config."""
    from clawteam.config import HookDef, load_config, save_config

    cfg = load_config()
    hook = HookDef(event=event, action=action, command=command, priority=priority)
    cfg.hooks.append(hook)
    save_config(cfg)
    console.print(f"[green]Hook added:[/green] {event} → {action}: {command}")


@hook_app.command("remove")
def hook_remove(
    event: str = typer.Option(..., "--event", "-e"),
    command: str = typer.Option("", "--command", "-c", help="Remove specific command (or all for event)"),
) -> None:
    """Remove hook(s) from config."""
    from clawteam.config import load_config, save_config

    cfg = load_config()
    before = len(cfg.hooks)
    if command:
        cfg.hooks = [h for h in cfg.hooks if not (h.event == event and h.command == command)]
    else:
        cfg.hooks = [h for h in cfg.hooks if h.event != event]
    removed = before - len(cfg.hooks)
    save_config(cfg)
    console.print(f"[green]Removed {removed} hook(s) for {event}[/green]")


@hook_app.command("test")
def hook_test(
    event: str = typer.Option(..., "--event", "-e", help="Event type to emit"),
    team: str = typer.Option("test", "--team", "-t"),
    agent: str = typer.Option("test-agent", "--agent", "-n"),
) -> None:
    """Emit a synthetic event to test hooks."""
    from clawteam.events.global_bus import get_event_bus
    from clawteam.events.hooks import _resolve_event_type

    event_cls = _resolve_event_type(event)
    if event_cls is None:
        console.print(f"[red]Unknown event type: {event}[/red]")
        raise typer.Exit(1)

    bus = get_event_bus()
    kwargs: dict = {"team_name": team}
    if hasattr(event_cls, "agent_name"):
        kwargs["agent_name"] = agent
    evt = event_cls(**kwargs)
    results = bus.emit(evt)
    console.print(f"[green]Emitted {event}[/green] → {len(results)} handler(s) executed")


# ── Plugin management ──────────────────────────────────────────────────
