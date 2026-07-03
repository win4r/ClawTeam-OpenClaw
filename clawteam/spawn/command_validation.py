"""Validation and classification helpers for spawned agent commands."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

_DOCKER_ENGINES = {"docker", "podman"}
_DOCKER_FLAGS_WITH_VALUE = {
    "-a",
    "--add-host",
    "--annotation",
    "--cgroup-parent",
    "--cidfile",
    "--cpu-period",
    "--cpu-quota",
    "--cpuset-cpus",
    "--cpuset-mems",
    "-e",
    "--entrypoint",
    "--env",
    "--env-file",
    "-h",
    "--hostname",
    "-l",
    "--label",
    "--label-file",
    "--log-driver",
    "--log-opt",
    "--memory",
    "--mount",
    "--name",
    "--network",
    "--platform",
    "-p",
    "--publish",
    "--pull",
    "--restart",
    "--runtime",
    "--security-opt",
    "--shm-size",
    "-u",
    "--user",
    "-v",
    "--volume",
    "--volumes-from",
    "-w",
    "--workdir",
}


def _docker_run_spec(command: list[str]) -> tuple[int, str, list[str]] | None:
    """Return (image_index, image, remainder) for docker/podman run commands."""
    if len(command) < 3:
        return None
    if Path(command[0]).name.lower() not in _DOCKER_ENGINES or command[1] != "run":
        return None

    i = 2
    while i < len(command):
        token = command[i]
        if token == "--":
            i += 1
            continue
        if token in _DOCKER_FLAGS_WITH_VALUE:
            i += 2
            continue
        if any(
            token.startswith(prefix)
            for prefix in (
                "--add-host=",
                "--annotation=",
                "--cgroup-parent=",
                "--cidfile=",
                "--cpu-period=",
                "--cpu-quota=",
                "--cpuset-cpus=",
                "--cpuset-mems=",
                "--entrypoint=",
                "--env=",
                "--env-file=",
                "--hostname=",
                "--label=",
                "--label-file=",
                "--log-driver=",
                "--log-opt=",
                "--memory=",
                "--mount=",
                "--name=",
                "--network=",
                "--platform=",
                "--publish=",
                "--pull=",
                "--restart=",
                "--runtime=",
                "--security-opt=",
                "--shm-size=",
                "--user=",
                "--volume=",
                "--volumes-from=",
                "--workdir=",
            )
        ):
            i += 1
            continue
        if token.startswith("-") and token not in {"-", "--"}:
            i += 1
            continue
        return i, token, command[i + 1 :]
    return None


def docker_wrapped_cli_name(command: list[str]) -> str | None:
    """Return the inner CLI name for supported docker/podman wrappers."""
    spec = _docker_run_spec(command)
    if spec is None:
        return None
    _, image, remainder = spec
    if remainder:
        return Path(remainder[0]).name.lower()
    if "nanobot" in image.lower():
        return "nanobot"
    return None


def ensure_docker_workspace(command: list[str], cwd: str) -> list[str]:
    """Ensure docker/podman run mounts and enters the requested workspace."""
    spec = _docker_run_spec(command)
    if spec is None:
        return list(command)

    image_index, image, remainder = spec
    prefix = list(command[:image_index])
    volume_spec = f"{cwd}:{cwd}"

    if not _docker_has_workdir(prefix, cwd):
        prefix.extend(["-w", cwd])
    if not _docker_has_workspace_mount(prefix, cwd):
        prefix.extend(["-v", volume_spec])

    return prefix + [image] + remainder


def ensure_docker_mount(command: list[str], host_path: str, container_path: str | None = None) -> list[str]:
    """Ensure docker/podman run mounts a host path into the container."""
    spec = _docker_run_spec(command)
    if spec is None:
        return list(command)

    image_index, image, remainder = spec
    prefix = list(command[:image_index])
    target_path = container_path or host_path
    volume_spec = f"{host_path}:{target_path}"

    if not _docker_has_mount(prefix, host_path, target_path):
        prefix.extend(["-v", volume_spec])

    return prefix + [image] + remainder


def ensure_docker_env(command: list[str], env_vars: dict[str, str]) -> list[str]:
    """Ensure docker/podman run passes selected environment variables through."""
    spec = _docker_run_spec(command)
    if spec is None:
        return list(command)

    image_index, image, remainder = spec
    prefix = list(command[:image_index])

    for key, value in env_vars.items():
        if key and not _docker_has_env(prefix, key):
            prefix.extend(["-e", f"{key}={value}"])

    return prefix + [image] + remainder


def _docker_has_workdir(prefix: list[str], cwd: str) -> bool:
    i = 0
    while i < len(prefix):
        token = prefix[i]
        if token in {"-w", "--workdir"} and i + 1 < len(prefix):
            if prefix[i + 1] == cwd:
                return True
            i += 2
            continue
        if token.startswith("--workdir=") and token.split("=", 1)[1] == cwd:
            return True
        i += 1
    return False


def _docker_has_workspace_mount(prefix: list[str], cwd: str) -> bool:
    return _docker_has_mount(prefix, cwd, cwd)


def _docker_has_mount(prefix: list[str], host_path: str, container_path: str) -> bool:
    i = 0
    while i < len(prefix):
        token = prefix[i]
        if token in {"-v", "--volume"} and i + 1 < len(prefix):
            if _volume_targets(prefix[i + 1], host_path, container_path):
                return True
            i += 2
            continue
        if token.startswith("--volume=") and _volume_targets(token.split("=", 1)[1], host_path, container_path):
            return True
        if token.startswith("--mount="):
            value = token.split("=", 1)[1]
            if _mount_targets(value, host_path, container_path):
                return True
        if token == "--mount" and i + 1 < len(prefix):
            value = prefix[i + 1]
            if _mount_targets(value, host_path, container_path):
                return True
            i += 2
            continue
        i += 1
    return False


def _volume_targets(spec: str, host_path: str, container_path: str) -> bool:
    parts = spec.split(":")
    if len(parts) < 2:
        return False
    return parts[0] == host_path and parts[1] == container_path


def _mount_targets(spec: str, host_path: str, container_path: str) -> bool:
    source_match = f"source={host_path}" in spec or f"src={host_path}" in spec
    target_match = f"target={container_path}" in spec or f"dst={container_path}" in spec
    return source_match and target_match


def _docker_has_env(prefix: list[str], key: str) -> bool:
    i = 0
    while i < len(prefix):
        token = prefix[i]
        if token in {"-e", "--env"} and i + 1 < len(prefix):
            if _env_key_matches(prefix[i + 1], key):
                return True
            i += 2
            continue
        if token.startswith("--env=") and _env_key_matches(token.split("=", 1)[1], key):
            return True
        i += 1
    return False


def _env_key_matches(spec: str, key: str) -> bool:
    return spec == key or spec.startswith(f"{key}=")


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
    spec = _docker_run_spec(command)
    if spec is not None and docker_wrapped_cli_name(command) == "nanobot":
        image_index, _, remainder = spec
        prefix = list(command[: image_index + 1])
        if not remainder:
            return prefix + ["nanobot", "agent"]
        if Path(remainder[0]).name.lower() == "nanobot" and len(remainder) == 1:
            return prefix + ["nanobot", "agent"]
    if executable == "openclaw" and len(command) == 1:
        # OpenClaw >= 2026.6 made `openclaw agent` a single-turn command that
        # requires an explicit session target, so a resident worker must run
        # the interactive TUI instead. The tmux backend appends
        # --session/--message/--model to bare `openclaw tui` commands.
        return [command[0], "tui"]

    return list(command)


# ---------------------------------------------------------------------------
# Command type detection helpers (shared by tmux and subprocess backends)
# ---------------------------------------------------------------------------

def _cmd_basename(command: list[str]) -> str:
    """Extract the basename of the first element of a command list."""
    if not command:
        return ""
    return command[0].rsplit("/", 1)[-1]


def is_claude_command(command: list[str]) -> bool:
    """Check if the command is a claude CLI invocation."""
    return _cmd_basename(command) in ("claude", "claude-code")


def is_codex_command(command: list[str]) -> bool:
    """Check if the command is a codex CLI invocation."""
    return _cmd_basename(command) in ("codex", "codex-cli")


def is_nanobot_command(command: list[str]) -> bool:
    """Check if the command is a nanobot CLI invocation."""
    return _cmd_basename(command) == "nanobot" or docker_wrapped_cli_name(command) == "nanobot"


def is_gemini_command(command: list[str]) -> bool:
    """Check if the command is a Gemini CLI invocation."""
    return _cmd_basename(command) == "gemini"


def is_kimi_command(command: list[str]) -> bool:
    """Check if the command is a Kimi CLI invocation."""
    return _cmd_basename(command) == "kimi"


def is_qwen_command(command: list[str]) -> bool:
    """Check if the command is a Qwen Code CLI invocation."""
    return _cmd_basename(command) in ("qwen", "qwen-code")


def is_opencode_command(command: list[str]) -> bool:
    """Check if the command is an OpenCode CLI invocation."""
    return _cmd_basename(command) == "opencode"


def is_pi_command(command: list[str]) -> bool:
    """Check if the command is a pi-coding-agent CLI invocation."""
    return _cmd_basename(command) == "pi"


def is_openclaw_command(command: list[str]) -> bool:
    """Check if the command is an OpenClaw CLI invocation."""
    return _cmd_basename(command) in ("openclaw",)


def is_hermes_command(command: list[str]) -> bool:
    """Check if the command is a Hermes Agent CLI invocation."""
    return _cmd_basename(command) == "hermes"


def is_interactive_cli(command: list[str]) -> bool:
    """Check if the command is an interactive AI CLI."""
    return (
        is_claude_command(command)
        or is_codex_command(command)
        or is_nanobot_command(command)
        or is_gemini_command(command)
        or is_kimi_command(command)
        or is_qwen_command(command)
        or is_opencode_command(command)
        or is_pi_command(command)
        or is_openclaw_command(command)
        or is_hermes_command(command)
    )


def command_has_workspace_arg(command: list[str]) -> bool:
    """Return True when a command already specifies a nanobot workspace."""
    spec = _docker_run_spec(command)
    if spec is not None and docker_wrapped_cli_name(command) == "nanobot":
        _, _, remainder = spec
        return "-w" in remainder or "--workspace" in remainder
    return "-w" in command or "--workspace" in command
