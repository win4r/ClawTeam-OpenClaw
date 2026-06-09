"""Board commands for clawteam."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from clawteam.cli._helpers import (
    _json_output,
    _output,
    console,
)

board_app = typer.Typer(help="Team dashboard and kanban board.")


@board_app.command("show")
def board_show(
    team: str = typer.Argument(..., help="Team name"),
):
    """Show detailed kanban board for a single team."""
    from clawteam.board.collector import BoardCollector
    from clawteam.board.renderer import BoardRenderer

    collector = BoardCollector()
    try:
        data = collector.collect_team(team)
    except ValueError as e:
        _output({"error": str(e)}, lambda d: console.print(f"[red]{d['error']}[/red]"))
        raise typer.Exit(1)

    _output(data, lambda d: BoardRenderer(console).render_team_board(d))


@board_app.command("update")
def board_update(
    team: str = typer.Argument(..., help="Team name"),
    agent: Optional[str] = typer.Option(None, "--agent", "-a", help="Compatibility alias; board state is team-wide"),
):
    """Compatibility alias: board state is derived from tasks and inbox messages."""
    from clawteam.board.collector import BoardCollector

    collector = BoardCollector()
    try:
        collector.collect_team(team)
    except ValueError as e:
        _output({"error": str(e)}, lambda d: console.print(f"[red]{d['error']}[/red]"))
        raise typer.Exit(1)

    _output(
        {
            "status": "up_to_date",
            "team": team,
            "agent": agent,
            "note": "Board state is derived automatically from task and inbox updates.",
        },
        lambda d: console.print(
            "[green]OK[/green] Board state is already derived automatically from tasks and inbox messages. "
            "Use `clawteam task create/update` to change it, then `clawteam board show` or `board live` to refresh the view."
        ),
    )


@board_app.command("overview")
def board_overview():
    """Show overview of all teams."""
    from clawteam.board.collector import BoardCollector
    from clawteam.board.renderer import BoardRenderer

    collector = BoardCollector()
    teams = collector.collect_overview()

    _output(teams, lambda d: BoardRenderer(console).render_overview(d))


@board_app.command("live")
def board_live(
    team: str = typer.Argument(..., help="Team name"),
    interval: float = typer.Option(2.0, "--interval", "-i", help="Refresh interval in seconds"),
):
    """Live-refreshing kanban board. Ctrl+C to stop."""
    from clawteam.board.collector import BoardCollector
    from clawteam.board.renderer import BoardRenderer

    collector = BoardCollector()

    # Validate team exists before starting live mode
    try:
        collector.collect_team(team)
    except ValueError as e:
        _output({"error": str(e)}, lambda d: console.print(f"[red]{d['error']}[/red]"))
        raise typer.Exit(1)

    if not _json_output:
        console.print(f"Live board for '{team}' (interval: {interval}s). Ctrl+C to stop.")

    renderer = BoardRenderer(console)
    renderer.render_team_board_live(collector, team, interval=interval)


@board_app.command("serve")
def board_serve(
    team: Optional[str] = typer.Argument(None, help="Team name (optional, shows all if omitted)"),
    port: int = typer.Option(8080, "--port", "-p", help="HTTP server port"),
    host: str = typer.Option("127.0.0.1", "--host", help="Bind address"),
    interval: float = typer.Option(2.0, "--interval", "-i", help="SSE push interval in seconds"),
):
    """Start Web UI dashboard server."""
    from clawteam.board.server import serve

    console.print(f"Starting Web UI on http://{host}:{port}")
    if team:
        console.print(f"Default team: {team}")
    console.print("Press Ctrl+C to stop.")
    serve(host=host, port=port, default_team=team or "", interval=interval)


@board_app.command("attach")
def board_attach(
    team: str = typer.Argument(..., help="Team name"),
):
    """Attach to tmux session with all agent windows tiled side by side.

    Merges all agent tmux windows into a single tiled view so you can
    watch every agent working simultaneously.
    """
    from clawteam.spawn.tmux_backend import TmuxBackend

    result = TmuxBackend.attach_all(team)
    if result.startswith("Error"):
        console.print(f"[red]{result}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]OK[/green] {result}")


@board_app.command("gource")
def board_gource(
    team: str = typer.Argument(..., help="Team name"),
    export: Optional[str] = typer.Option(None, "--export", help="Export video to file (requires FFmpeg)"),
    log_only: bool = typer.Option(False, "--log-only", help="Output Gource custom log to stdout without launching"),
    live: bool = typer.Option(False, "--live", help="Stream new activity into Gource in realtime"),
    interval: float = typer.Option(2.0, "--interval", min=0.2, help="Polling interval in seconds for --live"),
    combine_worktrees: bool = typer.Option(True, "--combine-worktrees/--events-only", help="Combine git worktree logs with event log"),
    repo: Optional[str] = typer.Option(None, "--repo", help="Git repo path for worktree discovery"),
    resolution: Optional[str] = typer.Option(None, "--resolution", "-r", help="Viewport resolution (e.g. 1920x1080)"),
    seconds_per_day: Optional[float] = typer.Option(None, "--speed", "-s", help="Seconds per day (lower = faster)"),
):
    """Launch Gource visualization of team activity.

    Visualizes ClawTeam events (task changes, messages, agent joins) and
    optionally combines git history from all agent worktrees into a unified
    Gource animation showing parallel collaboration.
    """
    import tempfile

    from clawteam.board.gource import (
        append_log_lines,
        collect_live_log_lines,
        find_gource,
        generate_combined_log,
        generate_event_log,
        launch_gource,
        stream_gource_live,
    )

    if live and export:
        _output(
            {"error": "--live cannot be used with --export"},
            lambda d: console.print(f"[red]{d['error']}[/red]"),
        )
        raise typer.Exit(1)

    # Generate log lines
    if combine_worktrees:
        lines = generate_combined_log(team, repo)
    else:
        lines = generate_event_log(team)

    if not lines:
        _output(
            {"error": f"No activity found for team '{team}'"},
            lambda d: console.print(f"[yellow]{d['error']}[/yellow]"),
        )
        raise typer.Exit(1)

    # --log-only: just print the custom log
    if log_only:
        for line in lines:
            print(line)
        return

    # Check gource is available
    gource_bin = find_gource()
    if not gource_bin:
        _output(
            {"error": "Gource not found. Install it (https://gource.io/) or set gource_path in config."},
            lambda d: console.print(f"[red]{d['error']}[/red]"),
        )
        raise typer.Exit(1)

    # Write log to temp file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".log", delete=False, prefix="clawteam-gource-") as f:
        f.write("\n".join(lines) + "\n")
        log_path = Path(f.name)

    try:
        title = f"ClawTeam: {team}"
        proc = launch_gource(
            log_file=None if live else log_path,
            title=title,
            resolution=resolution or "",
            seconds_per_day=seconds_per_day or 0,
            export_path=export,
            live_stream=live,
        )
        if proc is None:
            _output(
                {"error": "Failed to launch Gource" + (" (FFmpeg required for export)" if export else "")},
                lambda d: console.print(f"[red]{d['error']}[/red]"),
            )
            raise typer.Exit(1)

        if export:
            console.print(f"Exporting Gource visualization to [cyan]{export}[/cyan]...")
            proc.wait()
            console.print(f"[green]OK[/green] Video saved to {export}")
        elif live:
            if proc.stdin is None:
                console.print("[red]Failed to open live Gource stream.[/red]")
                raise typer.Exit(1)
            console.print(
                f"Gource live stream launched for team [cyan]{team}[/cyan]. "
                "Close the window or press Ctrl+C to stop."
            )
            seed_lines = collect_live_log_lines(
                set(),
                team,
                combine_worktrees=combine_worktrees,
                repo_path=repo,
            )
            append_log_lines(proc.stdin, seed_lines)
            try:
                stream_gource_live(
                    proc,
                    team,
                    combine_worktrees=combine_worktrees,
                    repo_path=repo,
                    poll_interval=interval,
                )
            except KeyboardInterrupt:
                if proc.poll() is None:
                    proc.terminate()
            finally:
                if proc.stdin is not None:
                    proc.stdin.close()
                proc.wait()
        else:
            console.print(f"Gource launched for team [cyan]{team}[/cyan]. Close the window to exit.")
            proc.wait()
    finally:
        try:
            log_path.unlink()
        except OSError:
            pass


