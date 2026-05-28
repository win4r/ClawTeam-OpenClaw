"""Helpers for making the current clawteam executable available to spawned agents."""

from __future__ import annotations

import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from clawteam.team.models import get_data_dir


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


@dataclass(frozen=True)
class DockerClawteamRuntime:
    """Best-effort runtime bundle for invoking clawteam inside docker."""

    mounts: tuple[tuple[str, str], ...]
    env: dict[str, str]


def _docker_bootstrap_script_path() -> Path:
    runtime_dir = get_data_dir() / "runtime" / "docker"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    return runtime_dir / "clawteam-bootstrap.sh"


def _ensure_docker_bootstrap_script() -> str:
    """Write a container-safe clawteam bootstrap wrapper and return its path."""
    script_path = _docker_bootstrap_script_path()
    script_body = """#!/bin/sh
if [ -n "${CLAWTEAM_DOCKER_HOST_WRAPPER:-}" ] && [ -x "${CLAWTEAM_DOCKER_HOST_WRAPPER:-}" ]; then
  "${CLAWTEAM_DOCKER_HOST_WRAPPER}" "$@" && exit 0
fi

if [ -n "${CLAWTEAM_DOCKER_SOURCE_ROOT:-}" ]; then
  if command -v python3 >/dev/null 2>&1; then
    PYTHONPATH="${CLAWTEAM_DOCKER_SOURCE_ROOT}${PYTHONPATH:+:${PYTHONPATH}}" exec python3 -m clawteam.cli.commands "$@"
  fi
  if command -v python >/dev/null 2>&1; then
    PYTHONPATH="${CLAWTEAM_DOCKER_SOURCE_ROOT}${PYTHONPATH:+:${PYTHONPATH}}" exec python -m clawteam.cli.commands "$@"
  fi
fi

echo "clawteam bootstrap unavailable inside container" >&2
exit 127
"""
    if not script_path.exists() or script_path.read_text(encoding="utf-8") != script_body:
        script_path.write_text(script_body, encoding="utf-8")
    script_path.chmod(0o755)
    return str(script_path)


def resolve_clawteam_source_root() -> str | None:
    """Return the source root that provides the current clawteam package."""
    try:
        import clawteam

        init_py = Path(clawteam.__file__).resolve()
    except Exception:
        return None

    package_dir = init_py.parent
    source_root = package_dir.parent
    if not source_root.exists():
        return None
    return str(source_root)


def _extract_wrapper_python_path(executable: str) -> str | None:
    """Best-effort parser for wrapper scripts that exec a Python interpreter."""
    candidate = Path(executable)
    if not candidate.is_file():
        return None

    try:
        lines = candidate.read_text(encoding="utf-8").splitlines()
    except Exception:
        return None

    for line in lines[:10]:
        line = line.strip()
        if not line.startswith("exec "):
            continue
        remainder = line[5:].strip()
        if " -m clawteam.cli.commands" not in remainder:
            continue
        python_path = remainder.split(" -m clawteam.cli.commands", 1)[0].strip().strip('"').strip("'")
        if os.path.isabs(python_path):
            return python_path
    return None


def build_docker_clawteam_runtime() -> DockerClawteamRuntime | None:
    """Return mounts/env needed to make `clawteam` available inside docker.

    Strategy:
    - mount the resolved `clawteam` wrapper into `/usr/local/bin/clawteam`
    - if the wrapper points at an absolute venv Python, mount that venv root at
      the same absolute path
    - mount the currently imported clawteam source tree at the same absolute
      path so editable installs continue to resolve
    """

    executable = resolve_clawteam_executable()
    if not os.path.isabs(executable):
        return None

    executable_path = Path(executable).resolve()
    if not executable_path.is_file():
        return None

    bootstrap_path = _ensure_docker_bootstrap_script()
    mounts: list[tuple[str, str]] = [
        (bootstrap_path, "/usr/local/bin/clawteam"),
        (str(executable_path), "/usr/local/bin/clawteam-host"),
    ]
    seen = set(mounts)

    python_path = _extract_wrapper_python_path(str(executable_path))
    if python_path:
        venv_root = Path(python_path).resolve().parent.parent
        if venv_root.exists():
            mount = (str(venv_root), str(venv_root))
            if mount not in seen:
                mounts.append(mount)
                seen.add(mount)

    source_root = resolve_clawteam_source_root()
    if source_root:
        mount = (source_root, source_root)
        if mount not in seen:
            mounts.append(mount)
            seen.add(mount)

    return DockerClawteamRuntime(
        mounts=tuple(mounts),
        env={
            "CLAWTEAM_BIN": "/usr/local/bin/clawteam",
            "CLAWTEAM_DOCKER_HOST_WRAPPER": "/usr/local/bin/clawteam-host",
            "CLAWTEAM_DOCKER_SOURCE_ROOT": source_root or "",
        },
    )


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
