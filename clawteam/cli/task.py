"""Task commands for clawteam."""

from __future__ import annotations

import json
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

task_app = typer.Typer(help="Task management commands")


@task_app.command("create")
def task_create(
    team: str = typer.Argument(..., help="Team name"),
    subject: str = typer.Argument(..., help="Task subject"),
    description: str = typer.Option("", "--description", "-d", help="Task description"),
    owner: Optional[str] = typer.Option(None, "--owner", "--agent", "-o", "-a", help="Owner agent name"),
    priority: str = typer.Option("medium", "--priority", "-p", help="Task priority: low, medium, high, urgent"),
    blocks: Optional[str] = typer.Option(None, "--blocks", help="Comma-separated task IDs this blocks"),
    blocked_by: Optional[str] = typer.Option(None, "--blocked-by", help="Comma-separated task IDs this is blocked by"),
):
    """Create a new task (TaskCreate)."""
    from clawteam.team.models import TaskPriority
    from clawteam.team.tasks import TaskStore

    store = TaskStore(team)
    blocks_list = [b.strip() for b in blocks.split(",") if b.strip()] if blocks else []
    blocked_by_list = [b.strip() for b in blocked_by.split(",") if b.strip()] if blocked_by else []

    try:
        task = store.create(
            subject=subject,
            description=description,
            owner=owner or "",
            priority=TaskPriority(priority),
            blocks=blocks_list,
            blocked_by=blocked_by_list,
        )
    except ValueError as e:
        _output({"error": str(e)}, lambda d: console.print(f"[red]{d['error']}[/red]"))
        raise typer.Exit(1)

    data = _dump(task)
    _output(data, lambda d: (
        console.print(f"[green]OK[/green] Task created: {d['id']}"),
        console.print(f"  Subject: {d['subject']}"),
        console.print(f"  Status: {d['status']}"),
        console.print(f"  Priority: {d.get('priority', 'medium')}"),
        console.print(f"  Owner: {d.get('owner', '')}") if d.get('owner') else None,
    ))


@task_app.command("get")
def task_get(
    team: str = typer.Argument(..., help="Team name"),
    task_id: str = typer.Argument(..., help="Task ID"),
):
    """Get a single task (TaskGet)."""
    from clawteam.team.tasks import TaskStore

    store = TaskStore(team)
    task = store.get(task_id)
    if not task:
        _output({"error": f"Task '{task_id}' not found"}, lambda d: console.print(f"[red]{d['error']}[/red]"))
        raise typer.Exit(1)

    data = _dump(task)

    def _human(d):
        console.print(f"Task: [cyan]{d['id']}[/cyan]")
        console.print(f"  Subject: {d['subject']}")
        console.print(f"  Status: {d['status']}")
        console.print(f"  Priority: {d.get('priority', 'medium')}")
        if d.get('owner'):
            console.print(f"  Owner: {d['owner']}")
        if d.get('lockedBy'):
            console.print(f"  Locked by: [yellow]{d['lockedBy']}[/yellow] (since {format_timestamp(d.get('lockedAt', ''))})")
        if d.get('description'):
            console.print(f"  Description: {d['description']}")
        if d.get('blocks'):
            console.print(f"  Blocks: {', '.join(d['blocks'])}")
        if d.get('blockedBy'):
            console.print(f"  Blocked by: {', '.join(d['blockedBy'])}")

    _output(data, _human)


@task_app.command("update")
def task_update(
    team: str = typer.Argument(..., help="Team name"),
    task_id: str = typer.Argument(..., help="Task ID"),
    status: Optional[str] = typer.Option(None, "--status", "-s", help="New status: pending, in_progress, completed, blocked"),
    owner: Optional[str] = typer.Option(None, "--owner", "--agent", "-o", "-a", help="New owner"),
    subject: Optional[str] = typer.Option(None, "--subject", help="New subject"),
    description: Optional[str] = typer.Option(None, "--description", "-d", help="New description"),
    priority: Optional[str] = typer.Option(None, "--priority", "-p", help="New priority: low, medium, high, urgent"),
    add_blocks: Optional[str] = typer.Option(None, "--add-blocks", help="Comma-separated task IDs this blocks"),
    add_blocked_by: Optional[str] = typer.Option(None, "--add-blocked-by", help="Comma-separated task IDs blocking this"),
    force: bool = typer.Option(False, "--force", "-f", help="Force override task lock"),
):
    """Update a task (TaskUpdate)."""
    from clawteam.identity import AgentIdentity
    from clawteam.team.models import TaskPriority, TaskStatus
    from clawteam.team.tasks import TaskLockError, TaskStore

    store = TaskStore(team)
    ts = TaskStatus(status) if status else None
    tp = TaskPriority(priority) if priority else None
    blocks_list = [b.strip() for b in add_blocks.split(",") if b.strip()] if add_blocks else None
    blocked_by_list = [b.strip() for b in add_blocked_by.split(",") if b.strip()] if add_blocked_by else None

    caller = AgentIdentity.from_env().agent_name

    try:
        task = store.update(
            task_id,
            status=ts,
            owner=owner,
            subject=subject,
            description=description,
            priority=tp,
            add_blocks=blocks_list,
            add_blocked_by=blocked_by_list,
            caller=caller,
            force=force,
        )
    except TaskLockError as e:
        _output({"error": str(e)}, lambda d: console.print(f"[red]Lock conflict: {d['error']}[/red]"))
        raise typer.Exit(1)
    except ValueError as e:
        _output({"error": str(e)}, lambda d: console.print(f"[red]{d['error']}[/red]"))
        raise typer.Exit(1)

    if not task:
        _output({"error": f"Task '{task_id}' not found"}, lambda d: console.print(f"[red]{d['error']}[/red]"))
        raise typer.Exit(1)

    data = _dump(task)
    _output(data, lambda d: console.print(f"[green]OK[/green] Task {d['id']} updated"))


@task_app.command("list")
def task_list(
    team: str = typer.Argument(..., help="Team name"),
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by status"),
    owner: Optional[str] = typer.Option(None, "--owner", "--agent", "-o", "-a", help="Filter by owner"),
    priority: Optional[str] = typer.Option(None, "--priority", "-p", help="Filter by priority: low, medium, high, urgent"),
    sort_priority: bool = typer.Option(False, "--sort-priority", help="Sort by priority (urgent first)"),
):
    """List tasks for a team (TaskList)."""
    from clawteam.team.models import TaskPriority, TaskStatus
    from clawteam.team.tasks import TaskStore

    store = TaskStore(team)
    ts = TaskStatus(status) if status else None
    tp = TaskPriority(priority) if priority else None
    tasks = store.list_tasks(status=ts, owner=owner, priority=tp, sort_by_priority=sort_priority)

    data = [_dump(t) for t in tasks]

    def _human(items):
        if not items:
            console.print("[dim]No tasks found[/dim]")
            return
        table = Table(title=f"Tasks - {team}")
        table.add_column("ID", style="dim")
        table.add_column("Subject", style="cyan")
        table.add_column("Status")
        table.add_column("Priority")
        table.add_column("Owner")
        table.add_column("Lock", style="yellow")
        table.add_column("Blocked By", style="dim")
        for t in items:
            st = t.get("status", "")
            style = {"pending": "white", "in_progress": "yellow", "completed": "green", "blocked": "red"}.get(st, "")
            priority_value = t.get("priority", "medium")
            priority_style = {
                "urgent": "red bold",
                "high": "yellow",
                "medium": "white",
                "low": "dim",
            }.get(priority_value, "")
            table.add_row(
                t["id"],
                t["subject"],
                f"[{style}]{st}[/{style}]" if style else st,
                f"[{priority_style}]{priority_value}[/{priority_style}]" if priority_style else priority_value,
                t.get("owner") or "",
                t.get("lockedBy") or "",
                ", ".join(t.get("blockedBy", [])),
            )
        console.print(table)

    _output(data, _human)


@task_app.command("stats")
def task_stats(
    team: str = typer.Argument(..., help="Team name"),
):
    """Show task timing statistics for a team."""
    from clawteam.team.tasks import TaskStore

    store = TaskStore(team)
    stats = store.get_stats()

    def _human(d):
        table = Table(title=f"Task Stats - {team}")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", justify="right")
        table.add_row("Total tasks", str(d["total"]))
        table.add_row("Completed", str(d["completed"]))
        table.add_row("In progress", str(d["in_progress"]))
        table.add_row("Pending", str(d["pending"]))
        table.add_row("Blocked", str(d["blocked"]))
        table.add_row("With timing data", str(d["timed_completed"]))
        avg = d["avg_duration_seconds"]
        if avg > 0:
            # Show in a readable format
            if avg < 60:
                table.add_row("Avg completion time", f"{avg:.1f}s")
            elif avg < 3600:
                table.add_row("Avg completion time", f"{avg / 60:.1f}m")
            else:
                table.add_row("Avg completion time", f"{avg / 3600:.1f}h")
        else:
            table.add_row("Avg completion time", "-")
        console.print(table)

    _output(stats, _human)


cost_app = typer.Typer(help="Cost tracking and budget management")


@cost_app.command("report")
def cost_report(
    team: str = typer.Argument(..., help="Team name"),
    input_tokens: int = typer.Option(0, "--input-tokens", help="Input tokens consumed"),
    output_tokens: int = typer.Option(0, "--output-tokens", help="Output tokens consumed"),
    cost_cents: float = typer.Option(0.0, "--cost-cents", help="Cost in cents"),
    provider: str = typer.Option("", "--provider", help="Provider name (e.g. anthropic)"),
    model: str = typer.Option("", "--model", help="Model name"),
    agent: Optional[str] = typer.Option(None, "--agent", "-a", help="Agent name (default: from env)"),
    task_id: str = typer.Option("", "--task-id", help="Associated task ID"),
):
    """Report token usage and cost for an agent."""
    from clawteam.identity import AgentIdentity
    from clawteam.team.costs import CostStore
    from clawteam.team.manager import TeamManager

    agent_name = agent or AgentIdentity.from_env().agent_name
    store = CostStore(team)
    event = store.report(
        agent_name=agent_name,
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_cents=cost_cents,
        task_id=task_id,
    )
    data = _dump(event)

    def _human(d):
        console.print(f"[green]OK[/green] Cost reported: ${d.get('costCents', 0) / 100:.4f}")

    _output(data, _human)

    # Check budget
    config = TeamManager.get_team(team)
    if config and config.budget_cents > 0:
        summary = store.summary()
        if summary.total_cost_cents > config.budget_cents:
            budget_dollars = config.budget_cents / 100
            spent_dollars = summary.total_cost_cents / 100
            if not _json_output:
                console.print(
                    f"[yellow]WARNING: Budget exceeded! "
                    f"Spent ${spent_dollars:.2f} / ${budget_dollars:.2f}[/yellow]"
                )


@cost_app.command("show")
def cost_show(
    team: str = typer.Argument(..., help="Team name"),
    agent: Optional[str] = typer.Option(None, "--agent", "-a", help="Filter by agent"),
    by: Optional[str] = typer.Option(None, "--by", "-b", help="Breakdown dimension: agent, task, or model"),
):
    """Show cost summary and event history."""
    from clawteam.team.costs import CostStore
    from clawteam.team.manager import TeamManager

    store = CostStore(team)
    summary = store.summary()
    events = store.list_events(agent_name=agent or "")
    config = TeamManager.get_team(team)
    budget = config.budget_cents if config else 0.0
    rate = store.cost_rate()

    data = {
        "summary": _dump(summary),
        "budget_cents": budget,
        "cost_rate_per_min": rate,
        "events": [_dump(e) for e in events],
    }

    def _human(d):
        s = d["summary"]
        total = s.get("totalCostCents", 0)
        console.print(f"\nCost Summary — [cyan]{team}[/cyan]")
        if budget > 0:
            console.print(f"  Total: ${total / 100:.4f} / ${budget / 100:.2f}")
        else:
            console.print(f"  Total: ${total / 100:.4f}")
        console.print(f"  Input tokens:  {s.get('totalInputTokens', 0):,}")
        console.print(f"  Output tokens: {s.get('totalOutputTokens', 0):,}")
        console.print(f"  Events: {s.get('eventCount', 0)}")
        if rate > 0:
            console.print(f"  Rate: ${rate / 100:.4f}/min")

        # Dimension breakdown
        dimension = by or "agent"
        dimension_key = {
            "agent": "byAgent",
            "model": "byModel",
            "task": "byTask",
        }.get(dimension, "byAgent")
        breakdown = s.get(dimension_key, {})
        if breakdown:
            console.print(f"  By {dimension}:")
            for k, c in sorted(breakdown.items()):
                console.print(f"    {k}: ${c / 100:.4f}")

        evts = d["events"]
        if evts:
            table = Table(title="Recent Events")
            table.add_column("Time", style="dim")
            table.add_column("Agent", style="cyan")
            table.add_column("In Tokens", justify="right")
            table.add_column("Out Tokens", justify="right")
            table.add_column("Cost", justify="right")
            table.add_column("Model", style="dim")
            table.add_column("Task", style="dim")
            for e in evts[-20:]:  # show last 20
                table.add_row(
                    format_timestamp(e.get("reportedAt")),
                    e.get("agentName", ""),
                    f"{e.get('inputTokens', 0):,}",
                    f"{e.get('outputTokens', 0):,}",
                    f"${e.get('costCents', 0) / 100:.4f}",
                    e.get("model", ""),
                    e.get("taskId", ""),
                )
            console.print(table)

    _output(data, _human)


@cost_app.command("budget")
def cost_budget(
    team: str = typer.Argument(..., help="Team name"),
    dollars: float = typer.Argument(..., help="Budget in dollars (0 = unlimited)"),
):
    """Set team budget in dollars."""
    from clawteam.team.manager import TeamManager

    config = TeamManager.get_team(team)
    if not config:
        _output({"error": f"Team '{team}' not found"}, lambda d: console.print(f"[red]{d['error']}[/red]"))
        raise typer.Exit(1)

    config.budget_cents = dollars * 100
    # Save config back
    from clawteam.team.manager import _save_config
    _save_config(config)

    _output(
        {"status": "set", "team": team, "budgetDollars": dollars},
        lambda d: console.print(
            f"[green]OK[/green] Budget set to ${dollars:.2f}" if dollars > 0
            else "[green]OK[/green] Budget removed (unlimited)"
        ),
    )


@task_app.command("wait")
def task_wait(
    team: str = typer.Argument(..., help="Team name"),
    agent: Optional[str] = typer.Option(None, "--agent", "-a", help="Agent inbox to monitor (default: leader from team config)"),
    poll_interval: float = typer.Option(5.0, "--poll-interval", "-p", help="Seconds between polls"),
    timeout: Optional[float] = typer.Option(None, "--timeout", "-t", help="Max seconds to wait (default: no limit)"),
):
    """Block until all tasks in a team are completed."""
    from clawteam.team.mailbox import MailboxManager
    from clawteam.team.manager import TeamManager
    from clawteam.team.tasks import TaskStore
    from clawteam.team.waiter import TaskWaiter

    # Resolve agent name for inbox monitoring
    agent_name = agent
    if not agent_name:
        agent_name = TeamManager.get_leader_inbox(team)
    if not agent_name:
        from clawteam.identity import AgentIdentity
        identity = AgentIdentity.from_env()
        agent_name = TeamManager.resolve_inbox(team, identity.agent_name, identity.user)
    elif agent:
        from clawteam.identity import AgentIdentity
        identity = AgentIdentity.from_env()
        agent_name = TeamManager.resolve_inbox(team, agent_name, identity.user)

    mailbox = MailboxManager(team)
    store = TaskStore(team)

    def _on_message(msg):
        ts = msg.timestamp
        if ts and "T" in ts:
            ts = ts.split("T")[1][:8]
        from_agent = msg.from_agent or "?"
        content = msg.content or ""
        if _json_output:
            print(json.dumps({
                "event": "message",
                "from": from_agent,
                "content": content,
                "timestamp": msg.timestamp,
            }), flush=True)
        else:
            console.print(f"  {ts}  message from={from_agent}: {content}")

    last_progress = ""

    def _on_progress(completed, total, in_progress, pending, blocked):
        nonlocal last_progress
        summary = f"{completed}/{total}"
        if summary == last_progress:
            return
        last_progress = summary
        if _json_output:
            print(json.dumps({
                "event": "progress",
                "completed": completed,
                "total": total,
                "in_progress": in_progress,
                "pending": pending,
                "blocked": blocked,
            }), flush=True)
        else:
            console.print(
                f"  {completed}/{total} tasks completed"
                f"  ({in_progress} in progress, {pending} pending, {blocked} blocked)"
            )

    if not _json_output:
        timeout_str = f"{timeout:.0f}s" if timeout else "none"
        console.print(f"Waiting for all tasks in team '[cyan]{team}[/cyan]' to complete...")
        console.print(
            f"  Agent inbox: {agent_name}  |  Poll interval: {poll_interval}s  |  Timeout: {timeout_str}"
        )
        console.print()

    def _on_agent_dead(dead_agent, abandoned_tasks):
        task_subjects = ", ".join(t.subject for t in abandoned_tasks)
        if _json_output:
            print(json.dumps({
                "event": "agent_dead",
                "agent": dead_agent,
                "abandoned_tasks": [{"id": t.id, "subject": t.subject} for t in abandoned_tasks],
            }), flush=True)
        else:
            console.print(
                f"  [yellow]Agent '{dead_agent}' is dead.[/yellow]"
                f" Reset {len(abandoned_tasks)} task(s) to pending: {task_subjects}"
            )

    waiter = TaskWaiter(
        team_name=team,
        agent_name=agent_name,
        mailbox=mailbox,
        task_store=store,
        poll_interval=poll_interval,
        timeout=timeout,
        on_message=_on_message,
        on_progress=_on_progress,
        on_agent_dead=_on_agent_dead,
    )
    result = waiter.wait()

    if _json_output:
        print(json.dumps({
            "event": "result",
            "status": result.status,
            "elapsed": round(result.elapsed, 1),
            "total": result.total,
            "completed": result.completed,
            "in_progress": result.in_progress,
            "pending": result.pending,
            "blocked": result.blocked,
            "messages_received": result.messages_received,
            "task_details": result.task_details,
        }), flush=True)
    else:
        console.print()
        if result.status == "completed":
            console.print(
                f"[green]All {result.total} tasks completed![/green]"
                f" ({result.elapsed:.1f}s, {result.messages_received} messages)"
            )
        elif result.status == "timeout":
            console.print(
                f"[yellow]Timeout[/yellow] after {result.elapsed:.1f}s."
                f" {result.completed}/{result.total} completed."
            )
            _print_incomplete_tasks(result.task_details)
        else:
            console.print(
                f"[yellow]Interrupted[/yellow] after {result.elapsed:.1f}s."
                f" {result.completed}/{result.total} completed."
            )
            _print_incomplete_tasks(result.task_details)

    if result.status != "completed":
        raise typer.Exit(1)


def _print_incomplete_tasks(task_details: list[dict]):
    """Print tasks that are not completed."""
    incomplete = [t for t in task_details if t["status"] != "completed"]
    if incomplete:
        console.print("  Incomplete tasks:")
        for t in incomplete:
            console.print(f"    [{t['status']}] {t['id']}  {t['subject']}  (owner: {t['owner'] or '-'})")


