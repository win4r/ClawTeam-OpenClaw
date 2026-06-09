"""Workspace commands for clawteam."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.table import Table

from clawteam.cli._helpers import (
    _json_output,
    _output,
    console,
)
from clawteam.timefmt import format_timestamp

workspace_app = typer.Typer(help="Git worktree workspace management")


@workspace_app.command("list")
def workspace_list(
    team: str = typer.Argument(..., help="Team name"),
    repo: Optional[str] = typer.Option(None, "--repo", help="Git repo path"),
):
    """List all active worktree workspaces for a team."""
    from clawteam.workspace import get_workspace_manager

    ws_mgr = get_workspace_manager(repo)
    if ws_mgr is None:
        _output({"error": "Not in a git repo"}, lambda d: console.print(f"[red]{d['error']}[/red]"))
        raise typer.Exit(1)

    workspaces = ws_mgr.list_workspaces(team)
    if _json_output:
        _output(
            {"workspaces": [w.model_dump() for w in workspaces]},
            lambda d: None,
        )
        return

    if not workspaces:
        console.print(f"No active workspaces for team '{team}'.")
        return

    table = Table(title=f"Workspaces — {team}")
    table.add_column("Agent")
    table.add_column("Branch")
    table.add_column("Path")
    table.add_column("Created")
    for ws in workspaces:
        table.add_row(ws.agent_name, ws.branch_name, ws.worktree_path, format_timestamp(ws.created_at))
    console.print(table)


@workspace_app.command("checkpoint")
def workspace_checkpoint(
    team: str = typer.Argument(..., help="Team name"),
    agent: str = typer.Argument(..., help="Agent name"),
    repo: Optional[str] = typer.Option(None, "--repo", help="Git repo path"),
    message: Optional[str] = typer.Option(None, "--message", "-m", help="Commit message"),
):
    """Create a checkpoint (auto-commit) for an agent's workspace."""
    from clawteam.workspace import get_workspace_manager

    ws_mgr = get_workspace_manager(repo)
    if ws_mgr is None:
        console.print("[red]Not in a git repo.[/red]")
        raise typer.Exit(1)

    committed = ws_mgr.checkpoint(team, agent, message)
    if committed:
        _output(
            {"status": "checkpoint_created", "team": team, "agent": agent},
            lambda d: console.print(f"[green]OK[/green] Checkpoint created for '{agent}'."),
        )
    else:
        _output(
            {"status": "no_changes", "team": team, "agent": agent},
            lambda d: console.print(f"[dim]No changes to checkpoint for '{agent}'.[/dim]"),
        )


@workspace_app.command("merge")
def workspace_merge(
    team: str = typer.Argument(..., help="Team name"),
    agent: str = typer.Argument(..., help="Agent name"),
    repo: Optional[str] = typer.Option(None, "--repo", help="Git repo path"),
    target: Optional[str] = typer.Option(None, "--target", help="Target branch (default: base branch)"),
    no_cleanup: bool = typer.Option(False, "--no-cleanup", help="Keep worktree after merge"),
):
    """Merge an agent's workspace branch back to the base branch."""
    from clawteam.workspace import get_workspace_manager

    ws_mgr = get_workspace_manager(repo)
    if ws_mgr is None:
        console.print("[red]Not in a git repo.[/red]")
        raise typer.Exit(1)

    success, output = ws_mgr.merge_workspace(team, agent, target, cleanup_after=not no_cleanup)
    if success:
        _output(
            {"status": "merged", "team": team, "agent": agent, "output": output},
            lambda d: console.print(f"[green]OK[/green] Merged '{agent}' workspace.\n{output}"),
        )
    else:
        _output(
            {"status": "merge_failed", "team": team, "agent": agent, "output": output},
            lambda d: console.print(f"[red]Merge failed[/red] for '{agent}':\n{output}"),
        )
        raise typer.Exit(1)


@workspace_app.command("cleanup")
def workspace_cleanup(
    team: str = typer.Argument(..., help="Team name"),
    agent: Optional[str] = typer.Option(None, "--agent", "-a", help="Agent name (all if omitted)"),
    repo: Optional[str] = typer.Option(None, "--repo", help="Git repo path"),
):
    """Clean up worktree workspace(s) — removes worktree and branch."""
    from clawteam.workspace import get_workspace_manager

    ws_mgr = get_workspace_manager(repo)
    if ws_mgr is None:
        console.print("[red]Not in a git repo.[/red]")
        raise typer.Exit(1)

    if agent:
        ok = ws_mgr.cleanup_workspace(team, agent)
        if ok:
            console.print(f"[green]OK[/green] Cleaned up workspace for '{agent}'.")
        else:
            console.print(f"[yellow]No workspace found for '{agent}'.[/yellow]")
    else:
        count = ws_mgr.cleanup_team(team)
        console.print(f"[green]OK[/green] Cleaned up {count} workspace(s) for team '{team}'.")


@workspace_app.command("status")
def workspace_status(
    team: str = typer.Argument(..., help="Team name"),
    agent: str = typer.Argument(..., help="Agent name"),
    repo: Optional[str] = typer.Option(None, "--repo", help="Git repo path"),
):
    """Show git diff stat for an agent's workspace."""
    from clawteam.workspace import get_workspace_manager, git

    ws_mgr = get_workspace_manager(repo)
    if ws_mgr is None:
        console.print("[red]Not in a git repo.[/red]")
        raise typer.Exit(1)

    ws = ws_mgr.get_workspace(team, agent)
    if ws is None:
        console.print(f"[yellow]No workspace found for '{agent}'.[/yellow]")
        raise typer.Exit(1)

    stat = git.diff_stat(Path(ws.worktree_path))
    console.print(f"[bold]Workspace status — {agent}[/bold] (branch: {ws.branch_name})")
    console.print(stat)


# Context Commands (git context layer)

context_app = typer.Typer(help="Git context: diffs, file ownership, conflicts, cross-branch log")


@context_app.command("diff")
def context_diff(
    team: str = typer.Argument(..., help="Team name"),
    agent: str = typer.Argument(..., help="Agent name"),
    repo: Optional[str] = typer.Option(None, "--repo", help="Git repo path"),
):
    """Show diff statistics for an agent's branch vs. base."""
    from clawteam.workspace.context import agent_diff

    try:
        data = agent_diff(team, agent, repo)
    except Exception as e:
        _output({"error": str(e)}, lambda d: console.print(f"[red]{d['error']}[/red]"))
        raise typer.Exit(1)

    def _human(d):
        console.print(f"[bold]{d['summary']}[/bold]")
        if d["diff_stat"]:
            console.print(d["diff_stat"])

    _output(data, _human)


@context_app.command("files")
def context_files(
    team: str = typer.Argument(..., help="Team name"),
    repo: Optional[str] = typer.Option(None, "--repo", help="Git repo path"),
):
    """Show file ownership map — which agents modify which files."""
    from clawteam.workspace.context import file_owners

    try:
        data = file_owners(team, repo)
    except Exception as e:
        _output({"error": str(e)}, lambda d: console.print(f"[red]{d['error']}[/red]"))
        raise typer.Exit(1)

    def _human(d):
        if not d:
            console.print("[dim]No modified files found.[/dim]")
            return
        table = Table(title=f"File Ownership — {team}")
        table.add_column("File", style="cyan")
        table.add_column("Agents")
        for fname, agents in sorted(d.items()):
            style = "bold red" if len(agents) > 1 else ""
            table.add_row(fname, ", ".join(agents), style=style)
        console.print(table)

    _output(data, _human)


@context_app.command("conflicts")
def context_conflicts(
    team: str = typer.Argument(..., help="Team name"),
    repo: Optional[str] = typer.Option(None, "--repo", help="Git repo path"),
):
    """Detect file overlaps across agent branches."""
    from clawteam.workspace.conflicts import detect_overlaps

    try:
        data = detect_overlaps(team, repo)
    except Exception as e:
        _output({"error": str(e)}, lambda d: console.print(f"[red]{d['error']}[/red]"))
        raise typer.Exit(1)

    def _human(d):
        if not d:
            console.print("[green]No overlaps detected.[/green]")
            return
        table = Table(title=f"File Overlaps — {team}")
        table.add_column("File", style="cyan")
        table.add_column("Agents")
        table.add_column("Severity")
        severity_styles = {"high": "bold red", "medium": "yellow", "low": "dim"}
        for item in d:
            sev = item["severity"]
            table.add_row(
                item["file"],
                ", ".join(item["agents"]),
                f"[{severity_styles.get(sev, '')}]{sev}[/{severity_styles.get(sev, '')}]",
            )
        console.print(table)

    _output(data, _human)


@context_app.command("log")
def context_log(
    team: str = typer.Argument(..., help="Team name"),
    limit: int = typer.Option(50, "--limit", "-n", help="Max entries"),
    repo: Optional[str] = typer.Option(None, "--repo", help="Git repo path"),
):
    """Unified cross-branch commit log for all agents."""
    from clawteam.workspace.context import cross_branch_log

    try:
        data = cross_branch_log(team, limit=limit, repo=repo)
    except Exception as e:
        _output({"error": str(e)}, lambda d: console.print(f"[red]{d['error']}[/red]"))
        raise typer.Exit(1)

    def _human(d):
        if not d:
            console.print("[dim]No commits found.[/dim]")
            return
        for entry in d:
            ts = format_timestamp(entry["timestamp"])
            console.print(
                f"[dim]{ts}[/dim] [cyan]{entry['agent']}[/cyan] "
                f"[yellow]{entry['hash'][:8]}[/yellow] {entry['message']}"
            )
            if entry["files"]:
                for f in entry["files"]:
                    console.print(f"    {f}")

    _output(data, _human)


@context_app.command("inject")
def context_inject(
    team: str = typer.Argument(..., help="Team name"),
    agent: str = typer.Argument(..., help="Target agent name"),
    repo: Optional[str] = typer.Option(None, "--repo", help="Git repo path"),
):
    """Generate context block for injection into an agent's prompt."""
    from clawteam.workspace.context import inject_context

    try:
        text = inject_context(team, agent, repo)
    except Exception as e:
        _output({"error": str(e)}, lambda d: console.print(f"[red]{d['error']}[/red]"))
        raise typer.Exit(1)

    if _json_output:
        _output({"context": text}, None)
    else:
        console.print(text)


