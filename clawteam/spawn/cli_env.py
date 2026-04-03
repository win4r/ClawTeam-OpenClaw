"""Helpers for making the current clawteam executable available to spawned agents."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path


def _looks_like_clawteam_entrypoint(value: str) -> bool:
    """Return True when argv0 plausibly points at the clawteam CLI."""

    name = Path(value).name.lower()
    return name == "clawteam" or name.startswith("clawteam.")


def resolve_clawteam_executable() -> str:
    """Resolve the current clawteam executable.

    Prefer the current process entrypoint when running from a venv or editable
    install via an absolute path. Fall back to `shutil.which("clawteam")`, then
    the bare command name.
    """

    argv0 = (sys.argv[0] or "").strip()
    if argv0 and _looks_like_clawteam_entrypoint(argv0):
        candidate = Path(argv0).expanduser()
        has_explicit_dir = candidate.parent != Path(".")
        if (candidate.is_absolute() or has_explicit_dir) and candidate.is_file():
            return str(candidate.resolve())

    resolved = shutil.which("clawteam")
    return resolved or "clawteam"


def build_spawn_path(base_path: str | None = None) -> str:
    """Ensure the current clawteam executable directory is on PATH."""

    path_value = base_path if base_path is not None else os.environ.get("PATH", "")
    executable = resolve_clawteam_executable()
    if not os.path.isabs(executable):
        return path_value

    bin_dir = str(Path(executable).resolve().parent)
    path_parts = [part for part in path_value.split(os.pathsep) if part] if path_value else []
    if bin_dir in path_parts:
        return path_value
    if not path_parts:
        return bin_dir
    return os.pathsep.join([bin_dir, *path_parts])


def propagate_openclaw_gateway_token(env_vars: dict[str, str]) -> None:
    """Best-effort: pre-load gateway token from OpenClaw config into env vars.

    Works around a timing issue where ``openclaw tui --session`` may attempt
    API calls before the config-file reader has loaded the gateway token,
    resulting in 401 errors.  By setting the token in the environment before
    the child process starts, OpenClaw can pick it up immediately.

    See: https://github.com/win4r/ClawTeam-OpenClaw/issues/51
    """
    if env_vars.get("OPENCLAW_GATEWAY_TOKEN"):
        return  # already set by user

    config_path = Path.home() / ".openclaw" / "openclaw.json"
    if not config_path.exists():
        return
    try:
        config = json.loads(config_path.read_text())
        token = config.get("gateway", {}).get("auth", {}).get("token")
        if token:
            env_vars["OPENCLAW_GATEWAY_TOKEN"] = token
    except Exception:
        pass  # best-effort, never crash the spawn flow
