"""Template commands for clawteam."""

from __future__ import annotations

import json

import typer
from rich.table import Table

from clawteam.cli._helpers import (
    _output,
    console,
)

template_app = typer.Typer(help="Template management")


@template_app.command("list")
def template_list():
    """List all available templates (builtin + user)."""
    from clawteam.templates import list_templates

    templates = list_templates()

    def _human(data):
        if not data:
            console.print("[dim]No templates found[/dim]")
            return
        table = Table(title="Templates")
        table.add_column("Name", style="cyan")
        table.add_column("Description")
        table.add_column("Source", style="dim")
        for t in data:
            table.add_row(t["name"], t["description"], t["source"])
        console.print(table)

    _output(templates, _human)


@template_app.command("show")
def template_show(
    name: str = typer.Argument(..., help="Template name"),
):
    """Show details of a template."""
    from clawteam.templates import load_template

    try:
        tmpl = load_template(name)
    except FileNotFoundError as e:
        _output({"error": str(e)}, lambda d: console.print(f"[red]{d['error']}[/red]"))
        raise typer.Exit(1)

    data = json.loads(tmpl.model_dump_json(by_alias=True))

    def _human(_data):
        console.print(f"[bold cyan]{tmpl.name}[/bold cyan] — {tmpl.description}")
        console.print(f"  Command: {' '.join(tmpl.command)}")
        console.print(f"  Backend: {tmpl.backend}")
        console.print()

        console.print("[bold]Leader:[/bold]")
        console.print(f"  {tmpl.leader.name} (type: {tmpl.leader.type})")
        console.print()

        if tmpl.agents:
            table = Table(title="Agents")
            table.add_column("Name", style="cyan")
            table.add_column("Type")
            for a in tmpl.agents:
                table.add_row(a.name, a.type)
            console.print(table)

        if tmpl.tasks:
            table = Table(title="Tasks")
            table.add_column("Subject")
            table.add_column("Owner", style="cyan")
            for t in tmpl.tasks:
                table.add_row(t.subject, t.owner)
            console.print(table)

    _output(data, _human)


# Launch Command
