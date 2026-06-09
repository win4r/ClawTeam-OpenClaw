"""Backward-compatibility shim -- imports from split modules."""
# Main app
from clawteam.cli._app import *  # noqa: F401, F403
from clawteam.cli._app import app  # noqa: F401

# Helpers that tests import directly
from clawteam.cli._helpers import (  # noqa: F401
    _data_dir,
    _dump,
    _json_output,
    _load_questionary,
    _load_skill_content,
    _output,
    _parse_key_value_items,
    _spawn_backend_hint,
    console,
)

# Cross-module helpers that tests access via monkeypatch or direct call
from clawteam.cli.lifecycle import _resolve_spawn_backend_and_command  # noqa: F401
from clawteam.cli.runtime import _resolve_runtime_backend  # noqa: F401
from clawteam.cli.team import _workspace_cwd_from_info  # noqa: F401

if __name__ == "__main__":
    app()
