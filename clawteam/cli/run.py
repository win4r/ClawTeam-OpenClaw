"""Run commands for clawteam."""

from __future__ import annotations

import typer

from clawteam.cli._helpers import (
    _load_skill_content,
    app,
    console,
)


@app.command("run")
def run_command(
    cli: str = typer.Argument(..., help="CLI agent to wrap (claude, codex, gemini, ...)"),
    goal: str = typer.Argument("", help="Task description"),
    team: str = typer.Option("default", "--team", "-t"),
    profile: str = typer.Option("", "--profile", "-P", help="Agent profile name"),
    workspace: bool = typer.Option(False, "--workspace", "-w", help="Create isolated workspace"),
    skill: list[str] = typer.Option([], "--skill", "-s", help="Skills to inject"),
    resume: bool = typer.Option(False, "--resume", help="Resume previous session"),
    keepalive: bool = typer.Option(False, "--keepalive/--no-keepalive", help="Keep resumable interactive agents attached and auto-resume after clean exit"),
) -> None:
    """Wrap a CLI agent with ClawTeam lifecycle management.

    Example: clawteam run claude "Fix the login bug"
    """
    import uuid as _uuid

    from clawteam.harness.prompts import build_harness_system_prompt, build_wrapped_prompt
    from clawteam.spawn import get_backend
    from clawteam.spawn.session_capture import build_resume_command as build_cli_resume_command
    from clawteam.team.manager import TeamManager

    mgr = TeamManager
    existing_team = mgr.get_team(team)
    existing_leader = None
    if existing_team and resume:
        existing_leader = next(
            (member for member in existing_team.members if member.agent_id == existing_team.lead_agent_id),
            existing_team.members[0] if existing_team.members else None,
        )

    if existing_leader is not None:
        agent_name = existing_leader.name
        agent_id = existing_leader.agent_id
    else:
        agent_name = f"{cli}-{_uuid.uuid4().hex[:6]}"
        agent_id = _uuid.uuid4().hex[:12]

    if existing_team is None:
        mgr.create_team(
            name=team,
            leader_name=agent_name,
            leader_id=agent_id,
            leader_agent_type=cli,
        )
    elif existing_leader is None:
        mgr.add_member(team, agent_name, agent_id=agent_id, agent_type=cli)

    # Optional workspace
    cwd = None
    if workspace:
        try:
            from clawteam.workspace import get_workspace_manager
            ws_mgr = get_workspace_manager()
            if ws_mgr:
                info = ws_mgr.create_workspace(team, agent_name)
                cwd = info.worktree_path
        except Exception:
            pass

    # Build prompts
    prompt = build_wrapped_prompt(agent_name=agent_name, goal=goal, team=team)
    system_prompt = build_harness_system_prompt(team=team, agent_name=agent_name)

    # Load skills
    if skill:
        skill_parts: list[str] = []
        for skill_name in skill:
            content = _load_skill_content(skill_name)
            if content:
                skill_parts.append(content)
        if skill_parts:
            system_prompt = system_prompt + "\n\n" + "\n\n".join(skill_parts)

    # Resolve profile env
    profile_env = None
    if profile:
        from clawteam.spawn.profiles import resolve_profile_env
        profile_env = resolve_profile_env(profile, cli)

    # Spawn
    from clawteam.config import load_config
    cfg = load_config()
    backend = get_backend(cfg.default_backend or "tmux")

    command_list = [cli]
    if resume:
        from clawteam.spawn.sessions import SessionStore

        session = SessionStore(team).load(agent_name)
        if session and session.session_id:
            client = str((getattr(session, "state", None) or {}).get("client") or "")
            resumed_command = build_cli_resume_command(command_list, session.session_id, client=client)
            if resumed_command != command_list:
                command_list = resumed_command
            console.print(f"[dim]Resuming session: {session.session_id}[/dim]")
            if prompt:
                prompt += "\nYou are resuming a previous session."

    result = backend.spawn(
        command=command_list,
        agent_name=agent_name,
        agent_id=agent_id,
        agent_type=cli,
        team_name=team,
        prompt=prompt or None,
        env=profile_env,
        cwd=cwd,
        skip_permissions=cfg.skip_permissions,
        system_prompt=system_prompt,
        keepalive=keepalive,
    )

    if result.startswith("Error"):
        console.print(f"[red]{result}[/red]")
        raise typer.Exit(1)

    console.print(f"[green]{result}[/green]")
    console.print(f"[bold]Attach:[/bold] tmux attach -t clawteam-{team}")
