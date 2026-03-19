"""Validation helpers for spawned agent commands."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def validate_spawn_command(
    command: list[str],
    *,
    path: str | None = None,
    cwd: str | None = None,
) -> str | None:
    """Return an error string when the agent command is not executable."""

    if not command:
        return "Error: no agent command specified"

    executable = command[0]
    separators = tuple(sep for sep in (os.sep, os.altsep) if sep)

    if any(sep in executable for sep in separators):
        candidate = Path(executable).expanduser()
        if not candidate.is_absolute() and cwd:
            candidate = Path(cwd) / candidate
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return None
        return f"Error: executable '{executable}' not found or not executable"

    if shutil.which(executable, path=path):
        return None

    return (
        f"Error: command '{executable}' not found in PATH. "
        "Install the agent CLI first or pass an executable path."
    )


def normalize_spawn_command(command: list[str]) -> list[str]:
    """Normalize shorthand agent commands to their interactive entrypoints."""

    if not command:
        return []

    executable = Path(command[0]).name
    if executable == "nanobot" and len(command) == 1:
        return [command[0], "agent"]

    return list(command)
