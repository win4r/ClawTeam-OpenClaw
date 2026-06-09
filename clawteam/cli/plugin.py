"""Plugin commands for clawteam."""

from __future__ import annotations

import typer

from clawteam.cli._helpers import (
    console,
)

plugin_app = typer.Typer(help="Plugin management")


@plugin_app.command("list")
def plugin_list(
    as_json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """List installed plugins."""
    from clawteam.plugins.manager import PluginManager

    mgr = PluginManager()
    plugins = mgr.discover()

    def _human() -> None:
        if not plugins:
            console.print("[dim]No plugins found.[/dim]")
            return
        for name, info in plugins.items():
            console.print(f"  [bold]{name}[/bold] v{info.get('version', '?')} — {info.get('description', '')}")

    def _json() -> None:
        import json as _json
        console.print(_json.dumps(plugins, indent=2))

    (_json if as_json else _human)()


@plugin_app.command("info")
def plugin_info(name: str = typer.Argument(..., help="Plugin name")) -> None:
    """Show details for a specific plugin."""
    from clawteam.plugins.manager import PluginManager

    mgr = PluginManager()
    info = mgr.get_info(name)
    if info is None:
        console.print(f"[red]Plugin not found: {name}[/red]")
        raise typer.Exit(1)
    for key, value in info.items():
        console.print(f"  [bold]{key}:[/bold] {value}")


# ── Harness commands ───────────────────────────────────────────────────
