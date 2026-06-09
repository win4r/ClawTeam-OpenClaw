"""Spawn commands for clawteam."""

from __future__ import annotations

import os
import uuid
from typing import Optional

import typer

from clawteam.cli._helpers import (
    _load_skill_content,
    _output,
    _spawn_backend_hint,
    app,
    console,
)
from clawteam.cli.lifecycle import _resolve_spawn_backend_and_command
from clawteam.cli.team import _workspace_cwd_from_info


@app.command("spawn")
def spawn_agent(
    backend: Optional[str] = typer.Argument(
        None,
        help="Backend: platform default (tmux on Linux/macOS, subprocess on Windows) or explicit backend",
    ),
    command: list[str] = typer.Argument(None, help="Command and arguments to run (default: openclaw)"),
    team: Optional[str] = typer.Option(None, "--team", "-t", help="Team name"),
    agent_name: Optional[str] = typer.Option(None, "--agent-name", "-n", help="Agent name"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Apply a named runtime profile"),
    agent_type: str = typer.Option("general-purpose", "--agent-type", help="Agent type"),
    task: Optional[str] = typer.Option(None, "--task", help="Task to assign (becomes the agent's initial prompt)"),
    workspace: Optional[bool] = typer.Option(None, "--workspace/--no-workspace", "-w", help="Create isolated git worktree (default: auto)"),
    repo: Optional[str] = typer.Option(None, "--repo", help="Git repo path (default: cwd)"),
    skip_permissions: Optional[bool] = typer.Option(None, "--skip-permissions/--no-skip-permissions", help="Skip tool approval for claude (default: from config, true)"),
    resume: bool = typer.Option(False, "--resume", "-r", help="Resume previous session if available"),
    replace: bool = typer.Option(False, "--replace", help="Replace a running agent with the same name"),
    keepalive: bool = typer.Option(True, "--keepalive/--no-keepalive", help="Keep resumable interactive agents attached and auto-resume after clean exit"),
    skill: Optional[list[str]] = typer.Option(None, "--skill", help="Skill name(s) to inject into the agent's system prompt (repeatable, claude only)"),
    openclaw_agent: Optional[str] = typer.Option(None, "--openclaw-agent", help="OpenClaw agent id to use (routes to a specific agent config/model)"),
    force: bool = typer.Option(False, "--force", "-f", help="Suppress max-agent warnings"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Model alias or ID (passed to backend via --model)"),
):
    """Spawn a new agent process with identity + task as its initial prompt.

    Defaults: platform backend, openclaw command, git worktree isolation, skip-permissions on.

    Backends:
      tmux        - Launch in tmux windows (visual monitoring)
      subprocess  - Launch as background processes
    """
    from clawteam.config import get_effective
    from clawteam.spawn import get_backend, normalize_backend_name
    from clawteam.spawn.profiles import apply_profile, load_profile, resolve_profile_name

    backend, command = _resolve_spawn_backend_and_command(backend, command)
    # Resolve defaults from config
    backend = normalize_backend_name(backend or None)
    # Do NOT default `command = ["openclaw"]` here — that would prevent
    # `resolve_profile_name` / `apply_profile` from substituting the profile's
    # agent later.  The fallback to OpenClaw happens after the profile branch.
    try:
        profile = resolve_profile_name(profile, command=list(command or []))
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    _team = team or "default"
    _name = agent_name or f"agent-{uuid.uuid4().hex[:6]}"
    _id = uuid.uuid4().hex[:12]
    user_name = os.environ.get("CLAWTEAM_USER", "")

    from clawteam.spawn.registry import is_agent_alive, stop_agent

    existing_alive = is_agent_alive(_team, _name)
    if existing_alive is True:
        if not replace:
            _output(
                {
                    "error": (
                        f"Agent '{_name}' is already running in team '{_team}'. "
                        "Use --replace to stop it and spawn a new instance."
                    )
                },
                lambda d: console.print(f"[red]{d['error']}[/red]"),
            )
            raise typer.Exit(1)

        if stop_agent(_team, _name) is not True:
            _output(
                {
                    "error": (
                        f"Failed to stop running agent '{_name}' in team '{_team}'. "
                        "Retry after the existing process exits."
                    )
                },
                lambda d: console.print(f"[red]{d['error']}[/red]"),
            )
            raise typer.Exit(1)

    # Check agent count against recommended max (arXiv:2512.08296)
    if not force:
        from clawteam.spawn.registry import get_registry
        from clawteam.templates import DEFAULT_MAX_AGENTS, check_agent_count

        current_count = len(get_registry(_team))
        warning = check_agent_count(current_count, max_agents=DEFAULT_MAX_AGENTS)
        if warning:
            console.print(f"[yellow]{warning}[/yellow]")

    # Resolve skip_permissions from config
    if skip_permissions is None:
        sp_val, _ = get_effective("skip_permissions")
        skip_permissions = str(sp_val).lower() not in ("false", "0", "no", "")

    try:
        be = get_backend(backend)
    except ValueError as e:
        message = str(e) + _spawn_backend_hint(backend, team)
        _output({"error": message}, lambda d: console.print(f"[red]{d['error']}[/red]"))
        raise typer.Exit(1)

    # Workspace: resolve from flag or config (default: auto)
    cwd = None
    ws_branch = ""
    ws_mode = ""
    ws_mgr = None
    if workspace is None:
        ws_mode, _ = get_effective("workspace")
        ws_mode = ws_mode or "auto"
        workspace = ws_mode in ("auto", "always")
    elif workspace is False:
        ws_mode = "never"

    if workspace:
        from clawteam.workspace import get_workspace_manager
        ws_mgr = get_workspace_manager(repo)
        if ws_mgr is None:
            if ws_mode not in ("auto", ""):
                console.print("[red]Not in a git repository. Use --repo or cd into a repo.[/red]")
                raise typer.Exit(1)
        else:
            ws_info = ws_mgr.create_workspace(team_name=_team, agent_name=_name, agent_id=_id)
            cwd = _workspace_cwd_from_info(repo, ws_info)
            ws_branch = ws_info.branch_name
            console.print(f"[dim]Workspace: {cwd} (branch: {ws_branch})[/dim]")
    elif repo:
        import os as _os_repo
        cwd = _os_repo.path.abspath(repo)

    profile_env: dict[str, str] = {}
    if profile:
        try:
            resolved_profile = load_profile(profile)
            command, profile_env, _ = apply_profile(
                resolved_profile,
                command=list(command or []),
            )
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1)
    elif not command:
        # Fork default: OpenClaw, not Claude.  CLAUDE.md "OpenClaw is the default".
        command = ["openclaw"]

    # Auto-register agent as team member
    from clawteam.team.manager import TeamManager
    team_created = False
    member_added = False
    if TeamManager.get_team(_team) is None:
        TeamManager.create_team(
            name=_team,
            leader_name=_name,
            leader_id=_id,
            description="Auto-created by clawteam spawn",
            user=user_name,
            leader_agent_type=agent_type,
        )
        team_created = True
        member_added = True
    try:
        if not team_created:
            TeamManager.add_member(
                team_name=_team,
                member_name=_name,
                agent_id=_id,
                agent_type=agent_type,
                user=user_name,
            )
            member_added = True
    except ValueError:
        pass  # already a member, ignore

    leader_name = TeamManager.get_leader_name(_team) or "leader"
    is_leader = _name == leader_name

    # Build prompt: identity + task + clawteam coordination guide
    prompt = None
    if task:
        from clawteam.spawn.prompt import build_agent_prompt

        prompt = build_agent_prompt(
            agent_name=_name,
            agent_id=_id,
            agent_type=agent_type,
            team_name=_team,
            leader_name=leader_name,
            task=task,
            user=user_name,
            workspace_dir=cwd or "",
            workspace_branch=ws_branch,
            memory_scope=f"custom:team-{_team}",
            isolated_workspace=bool(workspace and cwd),
            repo_path=repo,
        )

    # Session resume: inject the native client resume flag.
    if resume:
        from clawteam.spawn.session_capture import build_resume_command as build_cli_resume_command
        from clawteam.spawn.sessions import SessionStore
        session_store = SessionStore(_team)
        session = session_store.load(_name)
        if session and session.session_id:
            client = str((getattr(session, "state", None) or {}).get("client") or "")
            resumed_command = build_cli_resume_command(command, session.session_id, client=client)
            if resumed_command != list(command):
                command = resumed_command
                console.print(f"[dim]Resuming session: {session.session_id}[/dim]")
            if prompt:
                prompt += "\nYou are resuming a previous session."

    system_prompt = None
    if skill:
        skill_parts: list[str] = []
        for skill_name in skill:
            content = _load_skill_content(skill_name)
            if content is None:
                console.print(
                    f"[yellow]Warning: skill '{skill_name}' not found in ~/.claude/skills/[/yellow]"
                )
                continue
            skill_parts.append(content)
        if skill_parts:
            system_prompt = "\n\n".join(skill_parts)

    result = be.spawn(
        command=command,
        agent_name=_name,
        agent_id=_id,
        agent_type=agent_type,
        team_name=_team,
        prompt=prompt,
        env=profile_env or None,
        cwd=cwd,
        skip_permissions=skip_permissions,
        openclaw_agent=openclaw_agent,
        model=model,
        system_prompt=system_prompt,
        is_leader=is_leader,
        keepalive=keepalive,
    )

    if result.startswith("Error"):
        if member_added:
            if team_created:
                TeamManager.cleanup(_team)
            else:
                TeamManager.remove_member(_team, _name)
        if ws_mgr is not None and cwd:
            try:
                ws_mgr.cleanup_workspace(_team, _name, auto_checkpoint=False)
            except Exception:
                pass
        _output({"error": result}, lambda d: console.print(f"[red]{d['error']}[/red]"))
        raise typer.Exit(1)

    _output(
        {"status": "spawned", "backend": backend, "agentName": _name, "agentId": _id, "message": result},
        lambda d: console.print(f"[green]OK[/green] {d['message']}"),
    )


