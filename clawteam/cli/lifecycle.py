"""Lifecycle commands for clawteam."""

from __future__ import annotations

from typing import Optional

import typer

from clawteam.cli._helpers import (
    _output,
    console,
)

lifecycle_app = typer.Typer(help="Agent lifecycle commands (shutdown protocol)")


@lifecycle_app.command("request-shutdown")
def lifecycle_request_shutdown(
    team: str = typer.Argument(..., help="Team name"),
    from_agent: str = typer.Argument(..., help="Requesting agent name"),
    to_agent: str = typer.Argument(..., help="Target agent name"),
    reason: str = typer.Option("", "--reason", "-r", help="Shutdown reason"),
):
    """Request an agent to shut down (requestShutdown)."""
    from clawteam.team.lifecycle import LifecycleManager
    from clawteam.team.mailbox import MailboxManager

    mailbox = MailboxManager(team)
    lm = LifecycleManager(team, mailbox)
    request_id = lm.request_shutdown(from_agent=from_agent, to_agent=to_agent, reason=reason)

    _output(
        {"status": "requested", "requestId": request_id, "from": from_agent, "to": to_agent},
        lambda d: console.print(f"[green]OK[/green] Shutdown request sent to '{to_agent}' (id: {request_id})"),
    )


@lifecycle_app.command("approve-shutdown")
def lifecycle_approve_shutdown(
    team: str = typer.Argument(..., help="Team name"),
    request_id: str = typer.Argument(..., help="Shutdown request ID"),
    agent: str = typer.Argument(..., help="Agent approving shutdown (self)"),
):
    """Approve a shutdown request (approveShutdown). Agent agrees to shut down."""
    from clawteam.identity import AgentIdentity
    from clawteam.team.lifecycle import LifecycleManager
    from clawteam.team.mailbox import MailboxManager

    identity = AgentIdentity.from_env()
    mailbox = MailboxManager(team)
    lm = LifecycleManager(team, mailbox)
    leader_name = identity.agent_name
    lm.approve_shutdown(agent_name=agent, request_id=request_id, requester_name=leader_name)

    _output(
        {"status": "approved", "requestId": request_id, "agent": agent},
        lambda d: console.print(f"[green]OK[/green] {agent} approved shutdown"),
    )


@lifecycle_app.command("reject-shutdown")
def lifecycle_reject_shutdown(
    team: str = typer.Argument(..., help="Team name"),
    request_id: str = typer.Argument(..., help="Shutdown request ID"),
    agent: str = typer.Argument(..., help="Agent rejecting shutdown"),
    reason: str = typer.Option("", "--reason", "-r", help="Rejection reason"),
):
    """Reject a shutdown request (rejectShutdown)."""
    from clawteam.identity import AgentIdentity
    from clawteam.team.lifecycle import LifecycleManager
    from clawteam.team.mailbox import MailboxManager

    identity = AgentIdentity.from_env()
    mailbox = MailboxManager(team)
    lm = LifecycleManager(team, mailbox)
    lm.reject_shutdown(agent_name=agent, request_id=request_id, requester_name=identity.agent_name, reason=reason)

    _output(
        {"status": "rejected", "requestId": request_id, "agent": agent, "reason": reason},
        lambda d: console.print(f"[green]OK[/green] {agent} rejected shutdown"),
    )


@lifecycle_app.command("idle")
def lifecycle_idle(
    team: str = typer.Argument(..., help="Team name"),
    last_task: Optional[str] = typer.Option(None, "--last-task", help="Last task ID worked on"),
    task_status: Optional[str] = typer.Option(None, "--task-status", help="Status of last task"),
):
    """Send idle notification to leader."""
    from clawteam.identity import AgentIdentity
    from clawteam.team.lifecycle import LifecycleManager
    from clawteam.team.mailbox import MailboxManager
    from clawteam.team.manager import TeamManager

    identity = AgentIdentity.from_env()
    team_name = team
    leader_name = TeamManager.get_leader_name(team_name)
    if not leader_name:
        _output({"error": "No leader found"}, lambda d: console.print(f"[red]{d['error']}[/red]"))
        raise typer.Exit(1)

    mailbox = MailboxManager(team_name)
    lm = LifecycleManager(team_name, mailbox)
    lm.send_idle(
        agent_name=identity.agent_name,
        agent_id=identity.agent_id,
        leader_name=leader_name,
        last_task=last_task or "",
        task_status=task_status or "",
    )

    _output(
        {"status": "idle_sent", "agent": identity.agent_name, "leader": leader_name},
        lambda d: console.print(f"[green]OK[/green] Idle notification sent to '{leader_name}'"),
    )


@lifecycle_app.command("on-exit")
def lifecycle_on_exit(
    team: str = typer.Option(..., "--team", "-t", help="Team name"),
    agent: str = typer.Option(..., "--agent", "-n", help="Agent name"),
):
    """Handle agent process exit: clean up session and reset in_progress tasks.

    This is called automatically as a post-exit hook when an agent process terminates.
    """
    import subprocess

    from clawteam.spawn.registry import (
        get_agent_info,
        is_agent_alive,
        list_dead_agents,
        unregister_agent,
    )
    from clawteam.spawn.sessions import SessionStore
    from clawteam.team.mailbox import MailboxManager
    from clawteam.team.manager import TeamManager
    from clawteam.team.models import TaskStatus
    from clawteam.team.tasks import TaskStore

    # Write exit journal entry for conductor cross-process notification
    try:
        from clawteam.harness.exit_journal import FileExitJournal
        journal = FileExitJournal(team)
        journal.record_exit(agent_name=agent)
    except Exception:
        pass

    # Always clean up the agent's session file, regardless of task status.
    # Without this, session files accumulate indefinitely under
    # ~/.clawteam/sessions/{team}/ after every agent exit.
    SessionStore(team).clear(agent)

    store = TaskStore(team)

    # Release locks held by this agent FIRST — must happen before unregister
    # to avoid a race where is_agent_alive returns None (no registry entry)
    # and causes _acquire_lock to refuse overwriting a stale lock.
    store.release_stale_locks()

    # Find this agent's in_progress tasks and reset them
    tasks = store.list_tasks()
    abandoned = [
        t for t in tasks
        if t.owner == agent and t.status == TaskStatus.in_progress
    ]

    # Save spawn info BEFORE unregistering — needed for auto-respawn.
    saved_spawn_info = get_agent_info(team, agent)

    # Unregister from spawn registry so is_agent_alive returns None for this agent.
    # Guard: only unregister if the agent is already dead (avoids removing a live entry
    # if the hook fires before the process actually exits).
    if is_agent_alive(team, agent) is False:
        unregister_agent(team, agent)

        # Garbage-collect any other dead agents in the same team while we're here.
        for dead in list_dead_agents(team):
            unregister_agent(team, dead)

    if not abandoned:
        # Agent exited cleanly (all tasks already completed or pending)
        # Registry cleanup has already happened above.
        return

    for t in abandoned:
        store.update(t.id, status=TaskStatus.pending)

    exit_detail = ""
    info = get_agent_info(team, agent)
    if info and info.get("backend") == "tmux" and info.get("tmux_target"):
        try:
            pane = subprocess.run(
                ["tmux", "capture-pane", "-p", "-t", info["tmux_target"], "-S", "-80"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if pane.returncode == 0 and pane.stdout.strip():
                lines = [line.rstrip() for line in pane.stdout.splitlines() if line.strip()]
                tail = " | ".join(lines[-6:])
                if tail:
                    exit_detail = f" Last output: {tail[:700]}"
        except (subprocess.TimeoutExpired, OSError):
            exit_detail = ""

    # Notify leader
    leader_name = TeamManager.get_leader_name(team)
    if leader_name:
        mailbox = MailboxManager(team)
        task_subjects = ", ".join(t.subject for t in abandoned)
        mailbox.send(
            from_agent=agent,
            to=leader_name,
            content=f"Agent '{agent}' exited unexpectedly. "
                    f"Reset {len(abandoned)} task(s) to pending: {task_subjects}.{exit_detail}",
        )

    # Emit WorkerExit event
    try:
        from clawteam.events.global_bus import get_event_bus
        from clawteam.events.types import WorkerExit
        get_event_bus().emit(WorkerExit(
            team_name=team, agent_name=agent,
            abandoned_tasks=[t.id for t in abandoned],
        ))
    except Exception:
        pass

    _output(
        {
            "status": "agent_exited",
            "agent": agent,
            "abandoned_tasks": [{"id": t.id, "subject": t.subject} for t in abandoned],
        },
        lambda d: console.print(
            f"[yellow]Agent '{agent}' exited.[/yellow] "
            f"Reset {len(d['abandoned_tasks'])} task(s) to pending."
        ),
    )

    # --- Auto-respawn: attempt to restart the agent if pending tasks remain ---
    pending_tasks = [t for t in store.list_tasks() if t.status == TaskStatus.pending]
    if pending_tasks and saved_spawn_info:
        from clawteam.spawn.respawn import respawn_agent

        respawn_result = respawn_agent(team, agent, spawn_info=saved_spawn_info)
        if respawn_result.startswith("ok:"):
            _output(
                {"status": "agent_respawned", "agent": agent, "detail": respawn_result},
                lambda d: console.print(
                    f"  [green]Auto-respawned agent '{agent}'.[/green] {d['detail']}"
                ),
            )
            if leader_name:
                mailbox.send(
                    from_agent=agent,
                    to=leader_name,
                    content=f"Agent '{agent}' auto-respawned. {respawn_result}",
                )
        else:
            _output(
                {"status": "respawn_failed", "agent": agent, "detail": respawn_result},
                lambda d: console.print(
                    f"  [red]Auto-respawn failed for '{agent}':[/red] {d['detail']}"
                ),
            )
            if leader_name:
                mailbox.send(
                    from_agent=agent,
                    to=leader_name,
                    content=f"Auto-respawn failed for '{agent}': {respawn_result}. "
                            "Manual intervention may be needed.",
                )


def _resolve_spawn_backend_and_command(
    backend: Optional[str],
    command: list[str] | None,
) -> tuple[Optional[str], list[str]]:
    """Pass-through.  upstream removed the silent swap of unrecognized
    backends into the command position so that misordered args (e.g.
    `spawn <team-name> ...`) surface as a clear "Unknown spawn backend"
    error with `_spawn_backend_hint` rather than a confusing
    "command not found in PATH"."""
    return backend, list(command or [])


@lifecycle_app.command("should-keepalive")
def lifecycle_should_keepalive(
    team: str = typer.Option(..., "--team", "-t", help="Team name"),
    agent: str = typer.Option(..., "--agent", "-n", help="Agent name"),
):
    """Exit zero when an agent should auto-resume after a clean exit."""
    from clawteam.team.mailbox import MailboxManager
    from clawteam.team.manager import TeamManager
    from clawteam.team.models import MessageType

    if TeamManager.get_team(team) is None:
        raise typer.Exit(1)

    inbox_name = TeamManager.resolve_inbox(team, agent)
    mailbox = MailboxManager(team)
    for msg in mailbox.peek(inbox_name):
        if msg.type == MessageType.shutdown_approved:
            raise typer.Exit(1)

    raise typer.Exit(0)


@lifecycle_app.command("on-crash")
def lifecycle_on_crash(
    team: str = typer.Option(..., "--team", "-t", help="Team name"),
    agent: str = typer.Option(..., "--agent", "-n", help="Agent name"),
):
    """Handle agent process crash (pane-died). Emits WorkerCrash event."""
    # Reuse the same cleanup logic as on-exit
    lifecycle_on_exit(team=team, agent=agent)

    # Additionally emit a WorkerCrash event
    try:
        from clawteam.events.global_bus import get_event_bus
        from clawteam.events.types import WorkerCrash
        get_event_bus().emit(WorkerCrash(
            team_name=team, agent_name=agent, error="pane-died",
        ))
    except Exception:
        pass


@lifecycle_app.command("check-zombies")
def lifecycle_check_zombies(
    team: str = typer.Option(..., "--team", "-t", help="Team name"),
    max_hours: float = typer.Option(2.0, "--max-hours", help="Warn if agent has been running longer than this many hours"),
):
    """Warn about agents that have been running unusually long (possible zombies).

    Agents that never called on-exit will accumulate as background processes.
    This command helps identify them so you can decide whether to stop them manually.
    """
    from clawteam.spawn.registry import list_zombie_agents

    zombies = list_zombie_agents(team, max_hours=max_hours)

    if not zombies:
        _output(
            {"team": team, "zombies": []},
            lambda d: console.print(f"[green]✓[/green] No zombie agents detected for team '{team}'"),
        )
        return

    def _fmt(d: dict) -> None:
        console.print(
            f"[bold yellow]⚠ {len(d['zombies'])} zombie agent(s) detected in team '{team}':[/bold yellow]"
        )
        for z in d["zombies"]:
            console.print(
                f"  [yellow]• {z['agent_name']}[/yellow]  "
                f"pid={z['pid']}  backend={z['backend']}  "
                f"running={z['running_hours']}h"
            )
        console.print(
            "\n[dim]These processes did not call lifecycle on-exit. "
            "Inspect them manually and terminate them with your process manager if they are truly stuck.[/dim]"
        )

    _output({"team": team, "zombies": zombies}, _fmt)
    raise typer.Exit(1)


# Spawn Command
