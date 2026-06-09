"""Launch commands for clawteam."""

from __future__ import annotations

import uuid
from typing import Optional

import typer
from rich.table import Table

from clawteam.cli._helpers import (
    _output,
    app,
    console,
)
from clawteam.cli.team import _workspace_cwd_from_info


@app.command("launch")
def launch_team(
    template: str = typer.Argument(..., help="Template name (e.g., hedge-fund)"),
    goal: str = typer.Option("", "--goal", "-g", help="Project goal injected into agent prompts"),
    backend: Optional[str] = typer.Option(None, "--backend", "-b", help="Override backend"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Apply a named runtime profile to all agents"),
    team_name: Optional[str] = typer.Option(None, "--team-name", "--team", "-t", help="Override team name"),
    workspace: bool = typer.Option(False, "--workspace/--no-workspace", "-w"),
    repo: Optional[str] = typer.Option(None, "--repo", help="Git repo path"),
    command_override: Optional[list[str]] = typer.Option(None, "--command", help="Override agent command"),
    force: bool = typer.Option(False, "--force", "-f", help="Suppress max-agent warnings"),
    model_override: Optional[str] = typer.Option(None, "--model", help="Override model for ALL agents"),
    model_strategy_override: Optional[str] = typer.Option(None, "--model-strategy", help="Model strategy: auto | none"),
):
    """Launch a full agent team from a template with one command."""
    import os as _os

    from clawteam.config import get_effective
    from clawteam.model_resolution import resolve_model
    from clawteam.spawn import get_backend, normalize_backend_name
    from clawteam.spawn.profiles import apply_profile, load_profile
    from clawteam.spawn.prompt import build_agent_prompt
    from clawteam.team.manager import TeamManager
    from clawteam.team.tasks import TaskStore
    from clawteam.templates import TemplateDef, load_template, render_task

    # 1. Load template
    try:
        tmpl: TemplateDef = load_template(template)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    # Check agent count against template max_agents
    if not force:
        from clawteam.templates import check_agent_count

        total_agents = len(tmpl.agents) + 1  # agents + leader
        warning = check_agent_count(total_agents - 1, tmpl.max_agents)
        if warning:
            console.print(f"[yellow]{warning}[/yellow]")

    # 2. Determine team name
    t_name = team_name or f"{tmpl.name}-{uuid.uuid4().hex[:6]}"
    be_name = normalize_backend_name(backend or tmpl.backend)
    cmd = command_override or tmpl.command

    # 3. Create team
    leader_id = uuid.uuid4().hex[:12]
    try:
        TeamManager.create_team(
            name=t_name,
            leader_name=tmpl.leader.name,
            leader_id=leader_id,
            description=tmpl.description,
            user=_os.environ.get("CLAWTEAM_USER", ""),
        )
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)

    # 4. Add members
    agent_ids: dict[str, str] = {tmpl.leader.name: leader_id}
    for agent in tmpl.agents:
        aid = uuid.uuid4().hex[:12]
        agent_ids[agent.name] = aid
        TeamManager.add_member(
            team_name=t_name,
            member_name=agent.name,
            agent_id=aid,
            agent_type=agent.type,
            user=_os.environ.get("CLAWTEAM_USER", ""),
        )

    # 5. Create tasks
    ts = TaskStore(t_name)
    for task_def in tmpl.tasks:
        ts.create(
            subject=task_def.subject,
            description=task_def.description,
            owner=task_def.owner,
        )

    # 6. Get backend
    try:
        be = get_backend(be_name)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    # Match `spawn` behavior: honor configured permission skipping for
    # template-launched agents as well. Per-agent _skip is recomputed below
    # via get_effective; the top-level call here is kept for early validation
    # of the config key (any error surfaces before workspace setup).
    sp_val, _ = get_effective("skip_permissions")
    _ = str(sp_val).lower() not in ("false", "0", "no", "")

    # 7. Workspace setup (optional)
    ws_mgr = None
    if workspace:
        from clawteam.workspace import get_workspace_manager
        ws_mgr = get_workspace_manager(repo)
        if ws_mgr is None:
            console.print("[red]Not in a git repository. Use --repo or cd into a repo.[/red]")
            raise typer.Exit(1)

    # 8. Spawn all agents (leader first, then workers)
    # Load config once for model resolution (avoid re-reading per agent)
    from clawteam.config import load_config as _load_config
    _model_cfg = _load_config()

    all_agents = [tmpl.leader] + list(tmpl.agents)
    spawned: list[dict[str, str]] = []
    resolved_profile = None
    if profile:
        try:
            resolved_profile = load_profile(profile)
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1)

    for agent in all_agents:
        a_id = agent_ids[agent.name]
        a_cmd = agent.command or cmd
        a_env: dict[str, str] = {}
        if resolved_profile:
            command_seed = list(a_cmd) if (agent.command or command_override) else []
            a_cmd, a_env, _ = apply_profile(resolved_profile, command=command_seed)

        # Variable substitution
        rendered = render_task(
            agent.task,
            goal=goal,
            team_name=t_name,
            agent_name=agent.name,
        )

        # Workspace
        cwd = None
        ws_branch = ""
        if ws_mgr:
            ws_info = ws_mgr.create_workspace(
                team_name=t_name, agent_name=agent.name, agent_id=a_id,
            )
            cwd = _workspace_cwd_from_info(repo, ws_info)
            ws_branch = ws_info.branch_name

        # Build prompt
        prompt = build_agent_prompt(
            agent_name=agent.name,
            agent_id=a_id,
            agent_type=agent.type,
            team_name=t_name,
            leader_name=tmpl.leader.name,
            task=rendered,
            user=_os.environ.get("CLAWTEAM_USER", ""),
            workspace_dir=cwd or "",
            workspace_branch=ws_branch,
            memory_scope=f"custom:team-{t_name}",
            intent=agent.intent or "",
            end_state=agent.end_state or "",
            constraints=agent.constraints,
            team_size=len(all_agents),
            isolated_workspace=bool(cwd),
        )

        # Resolve skip_permissions from config
        from clawteam.config import get_effective
        sp_val, _ = get_effective("skip_permissions")
        _skip = str(sp_val).lower() not in ("false", "0", "no", "")

        # Resolve model for this agent (CLI override > agent > tier > strategy > template > config)
        resolved_model = resolve_model(
            cli_model=model_override,
            agent_model=agent.model,
            agent_model_tier=agent.model_tier,
            template_model_strategy=model_strategy_override or tmpl.model_strategy,
            template_model=tmpl.model,
            config_default_model=_model_cfg.default_model,
            agent_type=agent.type,
            tier_overrides=_model_cfg.model_tiers or None,
        )

        spawn_kwargs = dict(
            command=a_cmd,
            agent_name=agent.name,
            agent_id=a_id,
            agent_type=agent.type,
            team_name=t_name,
            prompt=prompt,
            env=a_env or None,
            cwd=cwd,
            skip_permissions=_skip,
            model=resolved_model,
            is_leader=(agent.name == tmpl.leader.name),
            keepalive=True,
        )
        if agent.retry:
            from clawteam.spawn import spawn_with_retry
            result = spawn_with_retry(
                be,
                max_retries=agent.retry.max_retries,
                backoff_base=agent.retry.backoff_base_seconds,
                backoff_max=agent.retry.backoff_max_seconds,
                **spawn_kwargs,
            )
        else:
            result = be.spawn(**spawn_kwargs)
        spawned.append({"name": agent.name, "id": a_id, "type": agent.type, "result": result})

    # 9. Output summary
    out = {
        "status": "launched",
        "team": t_name,
        "template": tmpl.name,
        "backend": be_name,
        "agents": [{"name": s["name"], "id": s["id"], "type": s["type"]} for s in spawned],
    }

    def _human(_data):
        console.print(f"\n[green bold]Team '{t_name}' launched from template '{tmpl.name}'[/green bold]\n")
        table = Table(title="Agents")
        table.add_column("Name", style="cyan")
        table.add_column("Type")
        table.add_column("ID", style="dim")
        for s in spawned:
            table.add_row(s["name"], s["type"], s["id"])
        console.print(table)
        console.print()
        if be_name == "tmux":
            console.print(f"[bold]Attach:[/bold] tmux attach -t clawteam-{t_name}")
        console.print(f"[bold]Board:[/bold]  clawteam board show {t_name}")
        console.print(f"[bold]Inbox:[/bold]  clawteam inbox peek {t_name} --agent <name>")

    _output(out, _human)


# ── Hook management ────────────────────────────────────────────────────
