"""Session commands for clawteam."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.table import Table

from clawteam.cli._helpers import (
    _dump,
    _output,
    console,
)
from clawteam.timefmt import format_timestamp

session_app = typer.Typer(help="Session persistence for agent resume")


@session_app.command("save")
def session_save(
    team: str = typer.Argument(..., help="Team name"),
    session_id: str = typer.Option("", "--session-id", "-s", help="Native client session ID"),
    last_task: str = typer.Option("", "--last-task", help="Last task ID worked on"),
    agent: Optional[str] = typer.Option(None, "--agent", "-a", help="Agent name (default: from env)"),
    client: str = typer.Option("", "--client", help="Client name such as claude, codex, gemini"),
    cwd: str = typer.Option("", "--cwd", help="Workspace directory for this session"),
):
    """Save agent session for later resume."""
    from clawteam.identity import AgentIdentity
    from clawteam.spawn.sessions import SessionStore

    agent_name = agent or AgentIdentity.from_env().agent_name
    store = SessionStore(team)
    session = store.save(
        agent_name=agent_name,
        session_id=session_id,
        last_task_id=last_task,
        state={
            "client": client,
            "source": "manual",
            "cwd": cwd,
            "confidence": "exact" if session_id else "",
        },
    )
    data = _dump(session)
    _output(data, lambda d: console.print(f"[green]OK[/green] Session saved for '{agent_name}'"))


@session_app.command("show")
def session_show(
    team: str = typer.Argument(..., help="Team name"),
    agent: Optional[str] = typer.Option(None, "--agent", "-a", help="Filter by agent"),
):
    """Show saved sessions."""
    from clawteam.spawn.sessions import SessionStore

    store = SessionStore(team)
    if agent:
        session = store.load(agent)
        if not session:
            _output({"error": f"No session for '{agent}'"}, lambda d: console.print(f"[dim]{d['error']}[/dim]"))
            return
        data = _dump(session)
        state = data.get("state") or {}
        _output(data, lambda d: (
            console.print(f"Session: [cyan]{d.get('agentName', '')}[/cyan]"),
            console.print(f"  Session ID: {d.get('sessionId', '')}"),
            console.print(f"  Client:     {state.get('client', '')}"),
            console.print(f"  Source:     {state.get('source', '')} ({state.get('confidence', '')})"),
            console.print(f"  CWD:        {state.get('cwd', '')}"),
            console.print(f"  Last task:  {d.get('lastTaskId', '')}"),
            console.print(f"  Saved at:   {format_timestamp(d.get('savedAt', ''))}"),
        ))
    else:
        sessions = store.list_sessions()
        data = [_dump(s) for s in sessions]

        def _human(items):
            if not items:
                console.print("[dim]No saved sessions[/dim]")
                return
            table = Table(title=f"Sessions — {team}")
            table.add_column("Agent", style="cyan")
            table.add_column("Client")
            table.add_column("Confidence")
            table.add_column("Session ID")
            table.add_column("Last Task", style="dim")
            table.add_column("Saved At", style="dim")
            for s in items:
                state = s.get("state") or {}
                table.add_row(
                    s.get("agentName", ""),
                    state.get("client", ""),
                    state.get("confidence", ""),
                    s.get("sessionId", ""),
                    s.get("lastTaskId", ""),
                    format_timestamp(s.get("savedAt")),
                )
            console.print(table)

        _output(data, _human)


@session_app.command("clear")
def session_clear(
    team: str = typer.Argument(..., help="Team name"),
    agent: Optional[str] = typer.Option(None, "--agent", "-a", help="Agent name (default: all)"),
):
    """Clear saved sessions."""
    from clawteam.spawn.sessions import SessionStore

    store = SessionStore(team)
    if agent:
        if store.clear(agent):
            _output({"status": "cleared", "agent": agent}, lambda d: console.print(f"[green]OK[/green] Session cleared for '{agent}'"))
        else:
            _output({"status": "not_found", "agent": agent}, lambda d: console.print(f"[dim]No session for '{agent}'[/dim]"))
    else:
        sessions = store.list_sessions()
        count = 0
        for s in sessions:
            if store.clear(s.agent_name):
                count += 1
        _output({"status": "cleared", "count": count}, lambda d: console.print(f"[green]OK[/green] Cleared {count} session(s)"))


plan_app = typer.Typer(help="Plan management commands")


@plan_app.command("submit")
def plan_submit(
    team: str = typer.Argument(..., help="Team name"),
    agent: str = typer.Argument(..., help="Agent name submitting the plan"),
    plan: str = typer.Argument(..., help="Plan content or path to a file"),
    summary: str = typer.Option("", "--summary", "-s", help="Brief plan summary"),
):
    """Submit a plan for leader approval (triggers plan_approval_request)."""
    from clawteam.team.mailbox import MailboxManager
    from clawteam.team.manager import TeamManager
    from clawteam.team.plan import PlanManager

    plan_content = plan
    p = Path(plan)
    if p.exists() and p.is_file():
        plan_content = p.read_text(encoding="utf-8")

    leader_name = TeamManager.get_leader_name(team)
    if not leader_name:
        _output({"error": "No leader found"}, lambda d: console.print(f"[red]{d['error']}[/red]"))
        raise typer.Exit(1)

    mailbox = MailboxManager(team)
    pm = PlanManager(team, mailbox)
    plan_id = pm.submit_plan(agent_name=agent, leader_name=leader_name, plan_content=plan_content, summary=summary)

    _output(
        {"status": "submitted", "planId": plan_id, "agent": agent},
        lambda d: console.print(f"[green]OK[/green] Plan {d['planId']} submitted by {d['agent']}"),
    )


@plan_app.command("approve")
def plan_approve(
    team: str = typer.Argument(..., help="Team name"),
    plan_id: str = typer.Argument(..., help="Plan ID (requestId from plan_approval_request)"),
    agent: str = typer.Argument(..., help="Agent who submitted the plan (target_agent_id)"),
    feedback: str = typer.Option("", "--feedback", "-f", help="Optional feedback"),
):
    """Approve a submitted plan (approvePlan)."""
    from clawteam.identity import AgentIdentity
    from clawteam.team.mailbox import MailboxManager
    from clawteam.team.plan import PlanManager

    identity = AgentIdentity.from_env()
    mailbox = MailboxManager(team)
    pm = PlanManager(team, mailbox)
    pm.approve_plan(leader_name=identity.agent_name, plan_id=plan_id, agent_name=agent, feedback=feedback)

    _output(
        {"status": "approved", "planId": plan_id},
        lambda d: console.print(f"[green]OK[/green] Plan {plan_id} approved"),
    )


@plan_app.command("reject")
def plan_reject(
    team: str = typer.Argument(..., help="Team name"),
    plan_id: str = typer.Argument(..., help="Plan ID (requestId from plan_approval_request)"),
    agent: str = typer.Argument(..., help="Agent who submitted the plan (target_agent_id)"),
    feedback: str = typer.Option("", "--feedback", "-f", help="Rejection feedback"),
):
    """Reject a submitted plan (rejectPlan)."""
    from clawteam.identity import AgentIdentity
    from clawteam.team.mailbox import MailboxManager
    from clawteam.team.plan import PlanManager

    identity = AgentIdentity.from_env()
    mailbox = MailboxManager(team)
    pm = PlanManager(team, mailbox)
    pm.reject_plan(leader_name=identity.agent_name, plan_id=plan_id, agent_name=agent, feedback=feedback)

    _output(
        {"status": "rejected", "planId": plan_id},
        lambda d: console.print(f"[green]OK[/green] Plan {plan_id} rejected"),
    )


