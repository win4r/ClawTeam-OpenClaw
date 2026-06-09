"""Inbox commands for clawteam."""

from __future__ import annotations

from typing import Optional

import typer

from clawteam.cli._helpers import (
    _dump,
    _json_output,
    _output,
    console,
)
from clawteam.timefmt import format_timestamp

inbox_app = typer.Typer(help="Inbox / messaging commands")


@inbox_app.command("send")
def inbox_send(
    team: str = typer.Argument(..., help="Team name"),
    to: str = typer.Argument(..., help="Recipient agent name"),
    content: Optional[str] = typer.Argument(None, help="Message content", metavar="[CONTENT]"),
    key: Optional[str] = typer.Option(None, "--key", "-k", help="Optional routing key"),
    msg_type: str = typer.Option("message", "--type", help="Message type"),
    from_agent: Optional[str] = typer.Option(None, "--from", "-f", help="Override sender name (default: from env identity)"),
):
    """Send a point-to-point message (write)."""
    import sys

    from clawteam.identity import AgentIdentity
    from clawteam.team.mailbox import MailboxManager
    from clawteam.team.models import MessageType

    if content is None:
        content = sys.stdin.read()
        if content.endswith("\n"):
            content = content[:-1]

    sender = from_agent or AgentIdentity.from_env().agent_name
    mailbox = MailboxManager(team)
    mt = MessageType(msg_type)
    msg = mailbox.send(
        from_agent=sender,
        to=to,
        content=content,
        msg_type=mt,
        key=key,
    )
    data = _dump(msg)
    _output(data, lambda d: console.print(f"[green]OK[/green] Message sent to '{to}'"))


@inbox_app.command("broadcast")
def inbox_broadcast(
    team: str = typer.Argument(..., help="Team name"),
    content: str = typer.Argument(..., help="Message content"),
    key: Optional[str] = typer.Option(None, "--key", "-k", help="Optional routing key"),
    msg_type: str = typer.Option("broadcast", "--type", help="Message type"),
    from_agent: Optional[str] = typer.Option(None, "--from", "-f", help="Override sender name (default: from env identity)"),
):
    """Broadcast a message to all team members (broadcast)."""
    from clawteam.identity import AgentIdentity
    from clawteam.team.mailbox import MailboxManager
    from clawteam.team.models import MessageType

    sender = from_agent or AgentIdentity.from_env().agent_name
    mailbox = MailboxManager(team)
    mt = MessageType(msg_type)
    messages = mailbox.broadcast(
        from_agent=sender,
        content=content,
        msg_type=mt,
        key=key,
    )
    data = {"count": len(messages), "recipients": [m.to for m in messages]}
    _output(data, lambda d: console.print(f"[green]OK[/green] Broadcast to {d['count']} agents"))


@inbox_app.command("receive")
def inbox_receive(
    team: str = typer.Argument(..., help="Team name"),
    agent: Optional[str] = typer.Option(None, "--agent", "-a", help="Agent name (default: from env)"),
    limit: int = typer.Option(10, "--limit", "-l", help="Max messages to receive"),
):
    """Receive and consume messages from inbox."""
    from clawteam.identity import AgentIdentity
    from clawteam.team.mailbox import MailboxManager
    from clawteam.team.manager import TeamManager

    identity = AgentIdentity.from_env()
    agent_name = TeamManager.resolve_inbox(team, agent or identity.agent_name, identity.user)
    mailbox = MailboxManager(team)
    messages = mailbox.receive(agent_name, limit=limit)

    data = [_dump(m) for m in messages]

    def _human(msgs):
        if not msgs:
            console.print("[dim]No messages[/dim]")
            return
        for m in msgs:
            console.print(
                f"[{format_timestamp(m.get('timestamp', ''))}] "
                f"[cyan]{m.get('type', '')}[/cyan] "
                f"from={m.get('from', '')} : {m.get('content', '')}"
            )

    _output(data, _human)


@inbox_app.command("peek")
def inbox_peek(
    team: str = typer.Argument(..., help="Team name"),
    agent: Optional[str] = typer.Option(None, "--agent", "-a", help="Agent name (default: from env)"),
):
    """Peek at messages without consuming them."""
    from clawteam.identity import AgentIdentity
    from clawteam.team.mailbox import MailboxManager
    from clawteam.team.manager import TeamManager

    identity = AgentIdentity.from_env()
    agent_name = TeamManager.resolve_inbox(team, agent or identity.agent_name, identity.user)
    mailbox = MailboxManager(team)
    messages = mailbox.peek(agent_name)

    data = {"count": len(messages), "messages": [_dump(m) for m in messages]}

    def _human(d):
        console.print(f"Pending messages: {d['count']}")
        for m in d["messages"]:
            console.print(
                f"  [{format_timestamp(m.get('timestamp', ''))}] "
                f"[cyan]{m.get('type', '')}[/cyan] "
                f"from={m.get('from', '')} : {(m.get('content') or '')[:80]}"
            )

    _output(data, _human)


@inbox_app.command("log")
def inbox_log(
    team: str = typer.Argument(..., help="Team name"),
    limit: int = typer.Option(50, "--limit", "-l", help="Max messages to show"),
    agent: Optional[str] = typer.Option(None, "--agent", "-a", help="Filter by sender agent name"),
):
    """View message history (event log). Non-destructive, shows all sent messages."""
    from clawteam.team.mailbox import MailboxManager

    mailbox = MailboxManager(team)
    messages = mailbox.get_event_log(limit=limit)

    if agent:
        messages = [m for m in messages if m.from_agent == agent]

    # Reverse to show oldest first (event log returns newest first)
    messages.reverse()

    data = {"count": len(messages), "messages": [_dump(m) for m in messages]}

    def _human(d):
        console.print(f"Message history: {d['count']} message(s)")
        for m in d["messages"]:
            fr = m.get("from", "?")
            to = m.get("to", "all")
            ts = format_timestamp(m.get("timestamp") or "")
            mtype = m.get("type", "message")
            content = (m.get("content") or "")[:120]
            console.print(f"  [{ts}] [cyan]{fr}[/cyan] → {to} ({mtype}): {content}")

    _output(data, _human)


@inbox_app.command("watch")
def inbox_watch(
    team: str = typer.Argument(..., help="Team name"),
    agent: Optional[str] = typer.Option(None, "--agent", "-a", help="Agent name (default: from env)"),
    poll_interval: float = typer.Option(1.0, "--poll-interval", "-p", help="Poll interval in seconds"),
    exec_cmd: Optional[str] = typer.Option(None, "--exec", "-e", help="Shell command to run for each new message (msg data in env vars)"),
):
    """Watch inbox for new messages (blocking, Ctrl+C to stop).

    With --exec, runs a shell command for each message. Message data is passed
    via env vars: CLAWTEAM_MSG_FROM, CLAWTEAM_MSG_TO, CLAWTEAM_MSG_CONTENT,
    CLAWTEAM_MSG_TYPE, CLAWTEAM_MSG_TIMESTAMP, CLAWTEAM_MSG_JSON.
    Legacy OH_MSG_* aliases are still exported for compatibility.
    """
    from clawteam.identity import AgentIdentity
    from clawteam.team.mailbox import MailboxManager
    from clawteam.team.manager import TeamManager
    from clawteam.team.watcher import InboxWatcher

    identity = AgentIdentity.from_env()
    agent_name = TeamManager.resolve_inbox(team, agent or identity.agent_name, identity.user)
    mailbox = MailboxManager(team)

    if not _json_output:
        console.print(f"Watching inbox for '{agent_name}' in team '{team}'... (Ctrl+C to stop)")
        if exec_cmd:
            console.print(f"  exec: {exec_cmd}")

    watcher = InboxWatcher(
        team_name=team,
        agent_name=agent_name,
        mailbox=mailbox,
        poll_interval=poll_interval,
        json_output=_json_output,
        exec_cmd=exec_cmd,
    )
    watcher.watch()


