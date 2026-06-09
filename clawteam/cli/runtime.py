"""Runtime commands for clawteam."""

from __future__ import annotations

from typing import Optional

import typer

from clawteam.cli._helpers import (
    _json_output,
    _output,
    console,
)

runtime_app = typer.Typer(help="Runtime routing and live injection for supported interactive backends")


def _resolve_runtime_backend(team: str, agent_name: str):
    from clawteam.spawn import get_backend
    from clawteam.spawn.registry import get_registry

    info = get_registry(team).get(agent_name, {})
    backend_name = info.get("backend", "tmux") or "tmux"
    return backend_name, get_backend(backend_name)



@runtime_app.command("inject")
def runtime_inject(
    team: str = typer.Argument(..., help="Team name"),
    agent: str = typer.Argument(..., help="Target agent name"),
    source: str = typer.Option("system", "--source", "-s", help="Runtime notification source"),
    channel: str = typer.Option("direct", "--channel", help="Runtime notification channel"),
    priority: str = typer.Option("medium", "--priority", help="Runtime notification priority"),
    summary: str = typer.Option(..., "--summary", help="Summary text for the injected notification"),
    evidence: list[str] = typer.Option([], "--evidence", "-e", help="Repeatable evidence line"),
    recommended_next_action: Optional[str] = typer.Option(
        None,
        "--recommended-next-action",
        help="Optional recommended next action",
    ),
):
    """Inject a structured runtime notification into a running agent session."""
    from clawteam.team.routing_policy import RuntimeEnvelope

    envelope = RuntimeEnvelope(
        source=source,
        target=agent,
        channel=channel,
        priority=priority,
        message_type="manual",
        summary=summary,
        evidence=list(evidence),
        recommended_next_action=recommended_next_action,
    )
    backend_name, backend = _resolve_runtime_backend(team, agent)
    if not hasattr(backend, "inject_runtime_message"):
        console.print(f"[red]Backend '{backend_name}' does not support runtime injection.[/red]")
        raise typer.Exit(1)

    ok, status = backend.inject_runtime_message(team, agent, envelope)
    if not ok:
        console.print(f"[red]{status}[/red]")
        raise typer.Exit(1)

    _output(
        {"team": team, "agent": agent, "backend": backend_name, "status": status},
        lambda data: console.print(f"[green]OK[/green] {data['status']}"),
    )


@runtime_app.command("watch")
def runtime_watch(
    team: str = typer.Argument(..., help="Team name"),
    agent: Optional[str] = typer.Option(None, "--agent", "-a", help="Agent name (default: from env)"),
    poll_interval: float = typer.Option(1.0, "--poll-interval", "-p", help="Poll interval in seconds"),
    exec_cmd: Optional[str] = typer.Option(
        None,
        "--exec",
        "-e",
        help="Shell command to run for each new message (msg data in env vars)",
    ),
):
    """Watch an inbox and route new messages into the running agent session."""
    from clawteam.identity import AgentIdentity
    from clawteam.team.mailbox import MailboxManager
    from clawteam.team.manager import TeamManager
    from clawteam.team.router import RuntimeRouter
    from clawteam.team.watcher import InboxWatcher

    identity = AgentIdentity.from_env()
    session_agent_name = agent or identity.agent_name
    backend_name, _ = _resolve_runtime_backend(team, session_agent_name)
    if backend_name == "subprocess":
        console.print(
            "[red]runtime watch is not supported for subprocess agents.[/red]\n"
            "Use `runtime inject` for headless delivery or rely on the normal inbox polling loop."
        )
        raise typer.Exit(1)

    agent_name = TeamManager.resolve_inbox(team, session_agent_name, identity.user)
    mailbox = MailboxManager(team)
    router = RuntimeRouter(
        team_name=team,
        agent_name=agent_name,
        session_agent_name=session_agent_name,
    )

    if not _json_output:
        console.print(
            f"Watching runtime routes for '{agent_name}' in team '{team}'... (Ctrl+C to stop)"
        )
        if exec_cmd:
            console.print(f"  exec: {exec_cmd}")

    watcher = InboxWatcher(
        team_name=team,
        agent_name=agent_name,
        mailbox=mailbox,
        poll_interval=poll_interval,
        json_output=_json_output,
        exec_cmd=exec_cmd,
        runtime_router=router,
    )
    watcher.watch()


@runtime_app.command("state")
def runtime_state(
    team: str = typer.Argument(..., help="Team name"),
):
    """Show persisted Phase 1 runtime throttle and dispatch state."""
    from clawteam.team.routing_policy import DefaultRoutingPolicy

    state = DefaultRoutingPolicy(team_name=team).read_state()

    def _human(data):
        console.print(
            f"Runtime state for '{data['team']}' (throttle={data['throttleSeconds']}s)"
        )
        routes = data.get("routes", {})
        if not routes:
            console.print("[dim]No runtime route state.[/dim]")
            return
        for key in sorted(routes):
            route = routes[key]
            console.print(
                f"  {route.get('source', '?')} -> {route.get('target', '?')} "
                f"pending={route.get('pendingCount', 0)} "
                f"status={route.get('lastDispatchStatus', 'idle')} "
                f"flushAfter={route.get('flushAfter', '') or '-'}"
            )

    _output(state, _human)


