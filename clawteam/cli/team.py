"""Team commands for clawteam."""

from __future__ import annotations

import json
import time
import uuid
from typing import Optional

import typer
from rich.table import Table

from clawteam.cli._helpers import (
    _dump,
    _json_output,
    _output,
    console,
)
from clawteam.timefmt import format_timestamp

team_app = typer.Typer(help="Team management commands")


@team_app.command("spawn-team")
def team_spawn_team(
    name: str = typer.Argument(..., help="Team name"),
    description: str = typer.Option("", "--description", "-d", help="Team description"),
    agent_name: str = typer.Option("leader", "--agent-name", "-n", help="Leader agent name"),
    agent_type: str = typer.Option("leader", "--agent-type", help="Leader agent type"),
):
    """Create a new team and register the leader (spawnTeam)."""
    from clawteam.identity import AgentIdentity
    from clawteam.spawn.session_capture import save_current_agent_session
    from clawteam.team.manager import TeamManager

    identity = AgentIdentity.from_env()
    leader_id = identity.agent_id
    leader_name = agent_name or identity.agent_name

    try:
        TeamManager.create_team(
            name=name,
            leader_name=leader_name,
            leader_id=leader_id,
            description=description,
            user=identity.user,
        )
        result = {
            "status": "created",
            "team": name,
            "leadAgentId": leader_id,
            "leaderName": leader_name,
        }
        session_id = save_current_agent_session(name, leader_name)
        if session_id:
            result["sessionId"] = session_id
        if identity.user:
            result["user"] = identity.user
        _output(result, lambda d: (
            console.print(f"[green]OK[/green] Team '{name}' created"),
            console.print(f"  Leader: {leader_name} (id: {leader_id})"),
            console.print(f"  Session: {d['sessionId']}") if d.get("sessionId") else None,
        ))
    except ValueError as e:
        if _json_output:
            print(json.dumps({"error": str(e)}))
        else:
            console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@team_app.command("discover")
def team_discover():
    """List all teams (discoverTeams)."""
    from clawteam.team.manager import TeamManager

    teams = TeamManager.discover_teams()

    def _human(data):
        if not data:
            console.print("[dim]No teams found[/dim]")
            return
        table = Table(title="Teams")
        table.add_column("Name", style="cyan")
        table.add_column("Description")
        table.add_column("Members", justify="right")
        for t in data:
            table.add_row(t["name"], t["description"], str(t["memberCount"]))
        console.print(table)

    _output(teams, _human)


@team_app.command("request-join")
def team_request_join(
    team: str = typer.Argument(..., help="Team name"),
    proposed_name: str = typer.Argument(..., help="Proposed agent name"),
    capabilities: str = typer.Option("", "--capabilities", "-c", help="Agent capabilities"),
    timeout: int = typer.Option(300, "--timeout", "-t", help="Timeout in seconds while waiting for leader response"),
    wait_for_response: bool = typer.Option(True, "--wait/--no-wait", help="Wait for leader approval before returning"),
):
    """Request to join a team (requestJoin). Blocks waiting for leader response."""
    from clawteam.identity import AgentIdentity
    from clawteam.team.mailbox import MailboxManager
    from clawteam.team.manager import TeamManager
    from clawteam.team.models import MessageType

    AgentIdentity.from_env()
    config = TeamManager.get_team(team)
    if not config:
        _output({"error": f"Team '{team}' not found"}, lambda d: console.print(f"[red]{d['error']}[/red]"))
        raise typer.Exit(1)

    leader_inbox = TeamManager.get_leader_inbox(team)
    leader_name = TeamManager.get_leader_name(team)
    if not leader_name or not leader_inbox:
        _output({"error": "No leader found"}, lambda d: console.print(f"[red]{d['error']}[/red]"))
        raise typer.Exit(1)

    mailbox = MailboxManager(team)
    request_id = f"join-{uuid.uuid4().hex[:12]}"
    temp_inbox_name = f"_pending_{proposed_name}"

    mailbox.send(
        from_agent=proposed_name,
        to=leader_inbox,
        msg_type=MessageType.join_request,
        request_id=request_id,
        proposed_name=proposed_name,
        capabilities=capabilities or None,
    )

    pending_result = {
        "status": "pending",
        "requestId": request_id,
        "teamName": team,
        "proposedName": proposed_name,
    }

    if not wait_for_response:
        _output(
            pending_result,
            lambda d: console.print(
                f"[green]OK[/green] Join request sent to leader '{leader_name}'. "
                f"Request id: {d['requestId']}. Check later with "
                f"`clawteam team join-status {team} {d['requestId']} --proposed-name {proposed_name}`"
            ),
        )
        return

    if not _json_output:
        console.print(f"Join request sent to leader '{leader_name}'. Waiting for response...")

    start = time.time()
    while time.time() - start < timeout:
        messages = mailbox.receive(temp_inbox_name, limit=10)
        for msg in messages:
            if msg.request_id == request_id:
                if msg.type == MessageType.join_approved:
                    result = {
                        "status": "approved",
                        "requestId": request_id,
                        "assignedName": msg.assigned_name or proposed_name,
                        "agentId": msg.agent_id or "",
                        "teamName": team,
                    }
                    _output(result, lambda d: console.print(
                        f"[green]Approved![/green] Joined as '{d['assignedName']}'"
                    ))
                    return
                elif msg.type == MessageType.join_rejected:
                    reason = msg.reason or msg.content or ""
                    _output(
                        {"status": "rejected", "requestId": request_id, "reason": reason},
                        lambda d: console.print(f"[red]Rejected.[/red] {reason}"),
                    )
                    raise typer.Exit(1)
        time.sleep(1.0)

    _output(
        pending_result,
        lambda d: console.print(
            "[yellow]Still pending.[/yellow] The join request was sent successfully but no leader response "
            f"arrived within {timeout}s. Check later with "
            f"`clawteam team join-status {team} {d['requestId']} --proposed-name {proposed_name}`."
        ),
    )


@team_app.command("join-status")
def team_join_status(
    team: str = typer.Argument(..., help="Team name"),
    request_id: str = typer.Argument(..., help="Join request ID"),
    proposed_name: Optional[str] = typer.Option(None, "--proposed-name", help="Proposed agent name used when requesting access"),
):
    """Check the status of a join request without resubmitting it."""
    from clawteam.identity import AgentIdentity
    from clawteam.team.mailbox import MailboxManager
    from clawteam.team.models import MessageType

    identity = AgentIdentity.from_env()
    mailbox = MailboxManager(team)
    temp_inbox_name = f"_pending_{proposed_name or identity.agent_name}"
    messages = mailbox.peek(temp_inbox_name)

    for msg in messages:
        if msg.request_id != request_id:
            continue
        if msg.type == MessageType.join_approved:
            _output(
                {
                    "status": "approved",
                    "requestId": request_id,
                    "assignedName": msg.assigned_name or proposed_name or identity.agent_name,
                    "agentId": msg.agent_id or "",
                    "teamName": msg.team_name or team,
                },
                lambda d: console.print(
                    f"[green]Approved![/green] Joined as '{d['assignedName']}'"
                ),
            )
            return
        if msg.type == MessageType.join_rejected:
            _output(
                {
                    "status": "rejected",
                    "requestId": request_id,
                    "reason": msg.reason or msg.content or "",
                },
                lambda d: console.print(f"[red]Rejected.[/red] {d['reason']}"),
            )
            return

    _output(
        {
            "status": "pending",
            "requestId": request_id,
            "teamName": team,
            "proposedName": proposed_name or identity.agent_name,
        },
        lambda d: console.print(
            f"[yellow]Pending.[/yellow] No approval or rejection found yet for request '{request_id}'."
        ),
    )


@team_app.command("approve-join")
def team_approve_join(
    team: str = typer.Argument(..., help="Team name"),
    request_id: str = typer.Argument(..., help="Join request ID"),
    assigned_name: Optional[str] = typer.Option(None, "--assigned-name", help="Override proposed name"),
):
    """Approve a join request (approveJoin)."""
    from clawteam.identity import AgentIdentity
    from clawteam.team.mailbox import MailboxManager
    from clawteam.team.manager import TeamManager
    from clawteam.team.models import MessageType

    identity = AgentIdentity.from_env()
    mailbox = MailboxManager(team)

    leader_inbox = TeamManager.get_leader_inbox(team) or identity.agent_name
    messages = mailbox.peek(leader_inbox)
    join_req = None
    for msg in messages:
        if msg.request_id == request_id and msg.type == MessageType.join_request:
            join_req = msg
            break

    if join_req is None:
        _output(
            {"error": f"No join request found with id '{request_id}'"},
            lambda d: console.print(f"[red]Error: {d['error']}[/red]"),
        )
        raise typer.Exit(1)

    proposed_name = join_req.proposed_name
    final_name = assigned_name or proposed_name
    new_agent_id = uuid.uuid4().hex[:12]

    try:
        TeamManager.add_member(
            team_name=team,
            member_name=final_name,
            agent_id=new_agent_id,
            agent_type="general-purpose",
            user=identity.user,
        )
    except ValueError:
        pass  # already a member

    temp_inbox_name = f"_pending_{proposed_name}"
    mailbox.send(
        from_agent=identity.agent_name,
        to=temp_inbox_name,
        msg_type=MessageType.join_approved,
        request_id=request_id,
        assigned_name=final_name,
        agent_id=new_agent_id,
        team_name=team,
    )

    # Schedule cleanup of the _pending_ inbox directory after the joining agent
    # has had time to consume the approval message. We do a best-effort immediate
    # cleanup here since the message was just delivered; the joining agent will
    # pick it up from the permanent inbox if it misses the temp one.
    import shutil

    from clawteam.team.models import get_data_dir

    pending_dir = get_data_dir() / "teams" / team / "inboxes" / temp_inbox_name
    if pending_dir.exists():
        try:
            shutil.rmtree(pending_dir)
        except OSError:
            pass

    _output(
        {"status": "approved", "requestId": request_id, "assignedName": final_name, "agentId": new_agent_id, "teamName": team},
        lambda d: console.print(f"[green]OK[/green] Approved '{final_name}' (id: {new_agent_id})"),
    )


@team_app.command("add-member")
def team_add_member(
    team: str = typer.Argument(..., help="Team name"),
    member_name: str = typer.Argument(..., help="Member name"),
    agent_type: str = typer.Option("general-purpose", "--agent-type", help="Agent type"),
    agent_id: Optional[str] = typer.Option(None, "--agent-id", help="Agent ID (default: auto-generated)"),
):
    """Directly add a member to a team without request/approve handshake."""
    from clawteam.identity import AgentIdentity
    from clawteam.team.manager import TeamManager

    identity = AgentIdentity.from_env()
    resolved_agent_id = agent_id or uuid.uuid4().hex[:12]

    try:
        member = TeamManager.add_member(
            team_name=team,
            member_name=member_name,
            agent_id=resolved_agent_id,
            agent_type=agent_type,
            user=identity.user,
        )
    except ValueError as e:
        _output({"error": str(e)}, lambda d: console.print(f"[red]Error: {d['error']}[/red]"))
        raise typer.Exit(1)

    _output(
        {"status": "added", "team": team, "member": _dump(member)},
        lambda d: console.print(
            f"[green]OK[/green] Added member '{d['member']['name']}' to team '{d['team']}'"
        ),
    )


@team_app.command("reject-join")
def team_reject_join(
    team: str = typer.Argument(..., help="Team name"),
    request_id: str = typer.Argument(..., help="Join request ID"),
    reason: str = typer.Option("", "--reason", "-r", help="Rejection reason"),
):
    """Reject a join request (rejectJoin)."""
    from clawteam.identity import AgentIdentity
    from clawteam.team.mailbox import MailboxManager
    from clawteam.team.manager import TeamManager
    from clawteam.team.models import MessageType

    identity = AgentIdentity.from_env()
    mailbox = MailboxManager(team)

    leader_inbox = TeamManager.get_leader_inbox(team) or identity.agent_name
    messages = mailbox.peek(leader_inbox)
    proposed_name = None
    for msg in messages:
        if msg.request_id == request_id and msg.type == MessageType.join_request:
            proposed_name = msg.proposed_name
            break

    proposed_name = proposed_name or f"agent-{request_id[:6]}"
    temp_inbox_name = f"_pending_{proposed_name}"

    mailbox.send(
        from_agent=identity.agent_name,
        to=temp_inbox_name,
        msg_type=MessageType.join_rejected,
        request_id=request_id,
        reason=reason or None,
    )

    # Clean up the _pending_ inbox directory
    import shutil

    from clawteam.team.models import get_data_dir

    pending_dir = get_data_dir() / "teams" / team / "inboxes" / temp_inbox_name
    if pending_dir.exists():
        try:
            shutil.rmtree(pending_dir)
        except OSError:
            pass

    _output(
        {"status": "rejected", "requestId": request_id, "reason": reason},
        lambda d: console.print(f"[green]OK[/green] Rejected request {request_id}"),
    )


@team_app.command("cleanup")
def team_cleanup(
    team: str = typer.Argument(..., help="Team name"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
):
    """Delete a team and all its data (cleanup)."""
    from clawteam.team.manager import TeamManager

    if not force and not _json_output:
        if not typer.confirm(f"Delete team '{team}' and all its data?"):
            raise typer.Abort()

    if TeamManager.cleanup(team):
        _output({"status": "cleaned", "team": team}, lambda d: console.print(f"[green]OK[/green] Team '{team}' deleted"))
    else:
        _output({"status": "not_found", "team": team}, lambda d: console.print(f"[yellow]Team '{team}' not found[/yellow]"))


def _workspace_cwd_from_info(repo: str | None, ws_info) -> str:
    from pathlib import Path as _Path

    cwd = ws_info.worktree_path
    subpath = getattr(ws_info, "repo_subpath", "") or ""
    if subpath:
        return str((_Path(ws_info.worktree_path) / subpath).resolve())
    if repo:
        requested_repo = _Path(repo).expanduser().resolve()
        repo_root = _Path(ws_info.repo_root).resolve()
        try:
            relative_repo = requested_repo.relative_to(repo_root)
        except ValueError:
            relative_repo = None
        if relative_repo and str(relative_repo) != ".":
            return str((_Path(ws_info.worktree_path) / relative_repo).resolve())
    return cwd


@team_app.command("status")
def team_status(
    team: str = typer.Argument(..., help="Team name"),
):
    """Show team status and members."""
    from clawteam.spawn.registry import is_agent_alive
    from clawteam.team.manager import TeamManager

    config = TeamManager.get_team(team)
    if not config:
        _output({"error": f"Team '{team}' not found"}, lambda d: console.print(f"[red]{d['error']}[/red]"))
        raise typer.Exit(1)

    data = {
        "name": config.name,
        "description": config.description,
        "leadAgentId": config.lead_agent_id,
        "createdAt": config.created_at,
        "members": [
            {
                **m.model_dump(by_alias=True),
                "alive": is_agent_alive(team, m.name),
            }
            for m in config.members
        ],
    }

    def _human(d):
        console.print(f"\nTeam: [cyan]{d['name']}[/cyan]")
        if d['description']:
            console.print(f"  {d['description']}")
        console.print(f"  Created: {format_timestamp(d['createdAt'])}")
        has_user = any(m.get("user") for m in d["members"])
        table = Table(title="Members")
        table.add_column("Name", style="cyan")
        if has_user:
            table.add_column("User", style="magenta")
        table.add_column("ID", style="dim")
        table.add_column("Type")
        table.add_column("Alive")
        table.add_column("Joined", style="dim")
        for m in d["members"]:
            row = [m.get("name", "")]
            if has_user:
                row.append(m.get("user", ""))
            alive = m.get("alive")
            alive_label = "yes" if alive is True else "no" if alive is False else "unknown"
            row.extend([
                m.get("agentId", ""),
                m.get("agentType", ""),
                alive_label,
                format_timestamp(m.get("joinedAt")),
            ])
            table.add_row(*row)
        console.print(table)

    _output(data, _human)


@team_app.command("watch")
def team_watch(
    team: str = typer.Argument(..., help="Team name"),
    leader: Optional[str] = typer.Option(None, "--leader", "-l", help="Leader agent name (default: from team config)"),
    interval: float = typer.Option(60.0, "--interval", "-i", help="Polling fallback interval in seconds"),
    heartbeat_interval: float = typer.Option(
        300.0,
        "--heartbeat-interval",
        help="Periodic reminder interval in seconds even when state is unchanged",
    ),
    redis_mode: str = typer.Option(
        "auto",
        "--redis",
        help="Redis wakeup mode: auto, off, or redis://host:port/db",
    ),
):
    """Watch team state and periodically wake the leader agent."""
    from clawteam.team.leader_watcher import LeaderWatcher
    from clawteam.team.manager import TeamManager

    config = TeamManager.get_team(team)
    if not config:
        _output({"error": f"Team '{team}' not found"}, lambda d: console.print(f"[red]{d['error']}[/red]"))
        raise typer.Exit(1)

    leader_name = leader or TeamManager.get_leader_name(team)
    if not leader_name:
        _output({"error": f"No leader found for team '{team}'"}, lambda d: console.print(f"[red]{d['error']}[/red]"))
        raise typer.Exit(1)

    watcher = LeaderWatcher(
        team_name=team,
        leader_name=leader_name,
        interval=interval,
        heartbeat_interval=heartbeat_interval,
        redis_mode=redis_mode,
        json_output=_json_output,
        verbose=not _json_output,
    )
    if not _json_output:
        console.print(
            f"Watching team '[cyan]{team}[/cyan]' for leader '[cyan]{leader_name}[/cyan]' "
            f"(interval: {interval}s, heartbeat: {heartbeat_interval}s, redis: {redis_mode})."
        )
    watcher.run()


@team_app.command("snapshot")
def team_snapshot(
    team: str = typer.Argument(..., help="Team name"),
    tag: str = typer.Option("", "--tag", "-t", help="Label for this snapshot"),
):
    """Save a snapshot of the entire team state (config, tasks, events, sessions, costs)."""
    from clawteam.team.snapshot import SnapshotManager

    try:
        meta = SnapshotManager(team).create(tag=tag)
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)

    data = json.loads(meta.model_dump_json(by_alias=True))

    def _human(d):
        console.print(f"[green]OK[/green] Snapshot [cyan]{d['id']}[/cyan] created")
        console.print(
            f"  {d['taskCount']} tasks, {d['eventCount']} events, "
            f"{d['sessionCount']} sessions, {d['costEventCount']} cost events"
        )

    _output(data, _human)


@team_app.command("snapshots")
def team_snapshots(
    team: str = typer.Argument(..., help="Team name"),
):
    """List available snapshots for a team."""
    from clawteam.team.snapshot import SnapshotManager

    snaps = SnapshotManager(team).list_snapshots()
    data = [json.loads(s.model_dump_json(by_alias=True)) for s in snaps]

    def _human(items):
        if not items:
            console.print("[dim]No snapshots found[/dim]")
            return
        table = Table(title=f"Snapshots for {team}")
        table.add_column("ID", style="cyan")
        table.add_column("Tag")
        table.add_column("Members", justify="right")
        table.add_column("Tasks", justify="right")
        table.add_column("Events", justify="right")
        table.add_column("Created", style="dim")
        for s in items:
            table.add_row(
                s["id"],
                s.get("tag", ""),
                str(s["memberCount"]),
                str(s["taskCount"]),
                str(s["eventCount"]),
                format_timestamp(s["createdAt"]),
            )
        console.print(table)

    _output(data, _human)


@team_app.command("restore")
def team_restore(
    team: str = typer.Argument(..., help="Team name"),
    snapshot_id: str = typer.Argument(..., help="Snapshot ID to restore"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview without writing"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
):
    """Restore team state from a snapshot."""
    from clawteam.team.snapshot import SnapshotManager

    mgr = SnapshotManager(team)

    try:
        summary = mgr.restore(snapshot_id, dry_run=True)
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)

    if dry_run:
        _output(summary, lambda d: console.print(
            f"[yellow]Dry run[/yellow] Would restore: "
            f"{d['tasks']} tasks, {d['events']} events, "
            f"{d['sessions']} sessions, {d['costs']} costs, "
            f"{d['inboxes']} inbox messages"
        ))
        return

    if not force and not _json_output:
        console.print(
            f"Will restore: {summary['tasks']} tasks, {summary['events']} events, "
            f"{summary['sessions']} sessions, {summary['costs']} costs"
        )
        if not typer.confirm("Proceed?"):
            raise typer.Abort()

    result = mgr.restore(snapshot_id)
    _output(result, lambda d: console.print(
        f"[green]OK[/green] Restored from snapshot [cyan]{snapshot_id}[/cyan]"
    ))


@team_app.command("snapshot-delete")
def team_snapshot_delete(
    team: str = typer.Argument(..., help="Team name"),
    snapshot_id: str = typer.Argument(..., help="Snapshot ID to delete"),
):
    """Delete a snapshot."""
    from clawteam.team.snapshot import SnapshotManager

    if SnapshotManager(team).delete(snapshot_id):
        _output(
            {"status": "deleted", "id": snapshot_id},
            lambda d: console.print(f"[green]OK[/green] Snapshot '{snapshot_id}' deleted"),
        )
    else:
        console.print(f"[yellow]Snapshot '{snapshot_id}' not found[/yellow]")
        raise typer.Exit(1)


