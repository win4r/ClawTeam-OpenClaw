"""Identity commands for clawteam."""

from __future__ import annotations

import json
import sys
from typing import Optional

import typer

from clawteam.cli._helpers import (
    _json_output,
    _output,
    console,
)

identity_app = typer.Typer(help="Agent identity commands")


@identity_app.command("show")
def identity_show():
    """Show current agent identity (from environment variables)."""
    from clawteam.identity import AgentIdentity

    identity = AgentIdentity.from_env()
    data = {
        "agentId": identity.agent_id,
        "agentName": identity.agent_name,
        "user": identity.user,
        "agentType": identity.agent_type,
        "teamName": identity.team_name,
        "isLeader": identity.is_leader,
        "planModeRequired": identity.plan_mode_required,
    }

    def _human(d):
        console.print(f"Agent ID:   {d['agentId']}")
        console.print(f"Agent Name: {d['agentName']}")
        console.print(f"User:       {d['user'] or '(none)'}")
        console.print(f"Agent Type: {d['agentType']}")
        console.print(f"Team:       {d['teamName'] or '(none)'}")
        console.print(f"Is Leader:  {d['isLeader']}")
        console.print(f"Plan Mode:  {d['planModeRequired']}")

    _output(data, _human)


@identity_app.command("set")
def identity_set(
    agent_id: Optional[str] = typer.Option(None, "--agent-id", help="Agent ID"),
    agent_name: Optional[str] = typer.Option(None, "--agent-name", help="Agent name"),
    agent_type: Optional[str] = typer.Option(None, "--agent-type", help="Agent type"),
    team: Optional[str] = typer.Option(None, "--team", help="Team name"),
):
    """Print shell export commands to set identity environment variables."""
    lines = []
    if agent_id:
        lines.append(f'export CLAWTEAM_AGENT_ID="{agent_id}"')
    if agent_name:
        lines.append(f'export CLAWTEAM_AGENT_NAME="{agent_name}"')
    if agent_type:
        lines.append(f'export CLAWTEAM_AGENT_TYPE="{agent_type}"')
    if team:
        lines.append(f'export CLAWTEAM_TEAM_NAME="{team}"')

    if not lines:
        console.print("[yellow]No options specified. Use --agent-id, --agent-name, --agent-type, --team[/yellow]")
        raise typer.Exit(1)

    output = "\n".join(lines)
    if _json_output:
        print(json.dumps({"exports": lines}))
    else:
        console.print("Run the following to set your identity:\n")
        console.print(output)
        console.print(f"\nOr use: eval $(clawteam identity set {' '.join(sys.argv[3:])})")


