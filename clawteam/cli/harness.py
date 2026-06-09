"""Harness commands for clawteam."""

from __future__ import annotations

import typer

from clawteam.cli._helpers import (
    _output,
    console,
)

harness_app = typer.Typer(help="Plan-then-execute harness orchestration")


@harness_app.command("start")
def harness_start(
    goal: str = typer.Option(..., "--goal", "-g", help="What to build"),
    team: str = typer.Option("default", "--team", "-t"),
    cli: str = typer.Option("claude", "--cli", "-c", help="Underlying CLI agent"),
    agents: int = typer.Option(3, "--agents", "-n", help="Number of executor agents"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Start a new harness run with plan-then-execute workflow."""
    from clawteam.harness.orchestrator import HarnessOrchestrator

    orch = HarnessOrchestrator(
        team_name=team, goal=goal, cli=cli, agent_count=agents,
    )
    harness_id = orch.start()

    def _human() -> None:
        console.print(f"[green]Harness started:[/green] {harness_id}")
        console.print(f"  Team: {team}")
        console.print(f"  Goal: {goal}")
        console.print(f"  Phase: {orch.state.current_phase.value}")
        console.print(f"\nAdvance: clawteam harness advance {team}")

    _output({"harness_id": harness_id, "team": team, "phase": orch.state.current_phase.value}, _human)


@harness_app.command("status")
def harness_status(
    team: str = typer.Argument(..., help="Team name"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Show current harness status."""
    from clawteam.harness.orchestrator import HarnessOrchestrator

    orch = HarnessOrchestrator.find_latest(team)
    if orch is None:
        console.print(f"[red]No harness run found for team '{team}'[/red]")
        raise typer.Exit(1)

    info = orch.status()

    def _human() -> None:
        console.print(f"[bold]Harness:[/bold] {info['harness_id']}")
        console.print(f"[bold]Phase:[/bold]   {info['phase']}")
        adv = "[green]yes[/green]" if info["can_advance"] else f"[red]no[/red] — {info['gate_reason']}"
        console.print(f"[bold]Advance:[/bold] {adv}")
        if info["artifacts"]:
            console.print(f"[bold]Artifacts:[/bold] {', '.join(info['artifacts'])}")

    _output(info, _human)


@harness_app.command("advance")
def harness_advance(
    team: str = typer.Argument(..., help="Team name"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Advance the harness to the next phase."""
    from clawteam.harness.orchestrator import HarnessOrchestrator

    orch = HarnessOrchestrator.find_latest(team)
    if orch is None:
        console.print(f"[red]No harness run found for team '{team}'[/red]")
        raise typer.Exit(1)

    new_phase = orch.advance()
    if new_phase is None:
        ok, reason = orch.runner.can_advance()
        console.print(f"[yellow]Cannot advance:[/yellow] {reason or 'already at final phase'}")
        raise typer.Exit(1)

    _output(
        {"phase": new_phase.value, "harness_id": orch.state.harness_id},
        lambda: console.print(f"[green]Advanced to phase:[/green] {new_phase.value}"),
    )


@harness_app.command("contracts")
def harness_contracts(
    team: str = typer.Argument(..., help="Team name"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """List sprint contracts for the current harness run."""
    from clawteam.harness.orchestrator import HarnessOrchestrator

    orch = HarnessOrchestrator.find_latest(team)
    if orch is None:
        console.print(f"[red]No harness run found for team '{team}'[/red]")
        raise typer.Exit(1)

    artifacts = orch.artifacts.list_artifacts()
    contracts = [a for a in artifacts if "sprint-contract" in a["name"]]

    def _human() -> None:
        if not contracts:
            console.print("[dim]No sprint contracts yet.[/dim]")
            return
        for c in contracts:
            console.print(f"  {c['name']} ({c['size']} bytes)")

    _output(contracts, _human)


@harness_app.command("abort")
def harness_abort(
    team: str = typer.Argument(..., help="Team name"),
) -> None:
    """Abort the current harness run."""
    from clawteam.harness.orchestrator import HarnessOrchestrator

    orch = HarnessOrchestrator.find_latest(team)
    if orch is None:
        console.print(f"[red]No harness run found for team '{team}'[/red]")
        raise typer.Exit(1)

    orch.abort()
    console.print(f"[yellow]Harness aborted:[/yellow] {orch.state.harness_id}")


@harness_app.command("approve")
def harness_approve(
    team: str = typer.Argument(..., help="Team name"),
) -> None:
    """Approve the current phase for advancement (human-in-the-loop gate)."""
    import json as _json

    from clawteam.harness.orchestrator import HarnessOrchestrator

    orch = HarnessOrchestrator.find_latest(team)
    if orch is None:
        console.print(f"[red]No harness run found for team '{team}'[/red]")
        raise typer.Exit(1)

    phase = orch.state.current_phase
    artifact_name = f"approval-{phase}.json"
    orch.artifacts.write(artifact_name, _json.dumps({"approved": True, "phase": phase}))
    orch.register_artifact(artifact_name, str(artifact_name))
    console.print(f"[green]Approved phase:[/green] {phase}")


@harness_app.command("conduct")
def harness_conduct(
    team: str = typer.Argument(..., help="Team name"),
    goal: str = typer.Option(..., "--goal", "-g", help="What to build"),
    cli: str = typer.Option("claude", "--cli", "-c", help="Underlying CLI agent"),
    agents: int = typer.Option(3, "--agents", "-n", help="Number of executor agents"),
    poll: float = typer.Option(5.0, "--poll", help="Poll interval in seconds"),
) -> None:
    """Run the full harness automatically (plan -> execute -> verify -> ship).

    This starts a conductor loop that drives the harness through phases.
    Press Ctrl+C to stop gracefully.
    """
    from clawteam.harness.conductor import HarnessConductor
    from clawteam.harness.orchestrator import HarnessOrchestrator
    from clawteam.harness.spawner import PhaseRoleSpawner

    orch = HarnessOrchestrator(
        team_name=team, goal=goal, cli=cli, agent_count=agents,
    )
    orch.start()

    spawner = PhaseRoleSpawner(cli=cli)
    conductor = HarnessConductor(
        orchestrator=orch,
        spawn_strategy=spawner,
        poll_interval=poll,
    )

    # Load plugins with full context
    try:
        from clawteam.plugins.manager import PluginManager
        ctx = conductor.build_context()
        mgr = PluginManager()
        mgr._build_context = lambda: ctx  # inject conductor's context
        mgr.load_all_from_config()
    except Exception:
        pass

    console.print(f"[green]Harness started:[/green] {orch.state.harness_id}")
    console.print(f"  Goal: {goal}")
    console.print(f"  CLI: {cli}, Agents: {agents}")
    console.print(f"  Phases: {' → '.join(orch.state.phases)}")
    console.print()

    conductor.run()


# ── Wrap / Run commands ────────────────────────────────────────────────
