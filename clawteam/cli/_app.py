"""Main ClawTeam CLI application — mounts all sub-apps and top-level commands."""
from __future__ import annotations

from clawteam.cli._helpers import app
from clawteam.cli.board import board_app
from clawteam.cli.config import config_app, preset_app, profile_app
from clawteam.cli.harness import harness_app
from clawteam.cli.hook import hook_app
from clawteam.cli.identity import identity_app
from clawteam.cli.inbox import inbox_app

# Top-level commands (registered via @app.command decorator side-effects)
from clawteam.cli.launch import *  # noqa: F401, F403
from clawteam.cli.lifecycle import lifecycle_app
from clawteam.cli.plugin import plugin_app
from clawteam.cli.run import *  # noqa: F401, F403
from clawteam.cli.runtime import runtime_app
from clawteam.cli.session import plan_app, session_app
from clawteam.cli.spawn import *  # noqa: F401, F403
from clawteam.cli.task import cost_app, task_app
from clawteam.cli.team import team_app
from clawteam.cli.template import template_app
from clawteam.cli.workspace import context_app, workspace_app

# Mount sub-apps
app.add_typer(config_app, name="config")
app.add_typer(preset_app, name="preset")
app.add_typer(profile_app, name="profile")
app.add_typer(team_app, name="team")
app.add_typer(inbox_app, name="inbox")
app.add_typer(runtime_app, name="runtime")
app.add_typer(task_app, name="task")
app.add_typer(cost_app, name="cost")
app.add_typer(session_app, name="session")
app.add_typer(plan_app, name="plan")
app.add_typer(lifecycle_app, name="lifecycle")
app.add_typer(identity_app, name="identity")
app.add_typer(board_app, name="board")
app.add_typer(workspace_app, name="workspace")
app.add_typer(context_app, name="context")
app.add_typer(template_app, name="template")
app.add_typer(hook_app, name="hook")
app.add_typer(plugin_app, name="plugin")
app.add_typer(harness_app, name="harness")
