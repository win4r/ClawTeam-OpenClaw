"""Spawn registry - persists agent process info for liveness checking."""

from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
from pathlib import Path

from clawteam.team.models import get_data_dir


def _normalize_data_dir(data_dir: str | Path | None) -> Path:
    if data_dir is None or data_dir == "":
        return get_data_dir().expanduser().resolve()
    return Path(data_dir).expanduser().resolve()


def _registry_path(team_name: str, data_dir: str | Path | None = None) -> Path:
    return _normalize_data_dir(data_dir) / "teams" / team_name / "spawn_registry.json"


def _session_index_path() -> Path:
    path = Path.home() / ".clawteam" / "session_registry.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def current_runtime_generation() -> str:
    """Fingerprint the currently installed runtime semantics.

    Uses repo-local source metadata so local code changes invalidate long-lived
    workers even before a version bump.
    """
    root = Path(__file__).resolve().parents[1]
    candidates = sorted(root.rglob("*.py"))
    pyproject = root.parent / "pyproject.toml"
    if pyproject.exists():
        candidates.append(pyproject)

    digest = hashlib.sha256()
    for candidate in candidates:
        try:
            stat = candidate.stat()
        except OSError:
            continue
        digest.update(str(candidate.relative_to(root.parent)).encode("utf-8", "ignore"))
        digest.update(str(stat.st_size).encode("ascii"))
        digest.update(str(stat.st_mtime_ns).encode("ascii"))
    return digest.hexdigest()[:16]


def register_agent(
    team_name: str,
    agent_name: str,
    backend: str,
    tmux_target: str = "",
    pid: int = 0,
    command: list[str] | None = None,
    session_key: str = "",
    agent_id: str = "",
    agent_type: str = "",
    data_dir: str = "",
    runtime_generation: str | None = None,
) -> None:
    """Record spawn info for an agent (atomic write)."""
    resolved_data_dir = str(_normalize_data_dir(data_dir))
    path = _registry_path(team_name, resolved_data_dir)
    registry = _load(path)
    registry[agent_name] = {
        "backend": backend,
        "tmux_target": tmux_target,
        "pid": pid,
        "command": command or [],
        "session_key": session_key,
        "agent_id": agent_id,
        "agent_type": agent_type,
        "team_name": team_name,
        "agent_name": agent_name,
        "data_dir": resolved_data_dir,
        "runtime_generation": current_runtime_generation() if runtime_generation is None else runtime_generation,
    }
    _save(path, registry)

    if session_key:
        session_index = _load(_session_index_path())
        session_index[session_key] = dict(registry[agent_name])
        _save(_session_index_path(), session_index)


def get_registry(team_name: str) -> dict[str, dict]:
    """Return the full spawn registry for a team."""
    return _load(_registry_path(team_name))


def get_agent_record(team_name: str, agent_name: str, data_dir: str | Path | None = None) -> dict | None:
    registry = _load(_registry_path(team_name, data_dir))
    info = registry.get(agent_name)
    return info if isinstance(info, dict) else None


def find_agent_by_session_key(session_key: str) -> dict | None:
    """Resolve agent identity from a stored OpenClaw session key across all teams."""
    if not session_key:
        return None

    session_index = _load(_session_index_path())
    indexed = session_index.get(session_key)
    if isinstance(indexed, dict):
        data_dir = indexed.get("data_dir", "")
        team_name = indexed.get("team_name", "")
        agent_name = indexed.get("agent_name", "")
        if data_dir and team_name and agent_name:
            registry_info = get_agent_record(team_name, agent_name, data_dir)
            if (
                registry_info
                and registry_info.get("session_key") == session_key
                and str(_normalize_data_dir(registry_info.get("data_dir"))) == str(_normalize_data_dir(data_dir))
            ):
                return registry_info
        return None

    teams_root = get_data_dir() / "teams"
    if not teams_root.exists():
        return None
    matches: list[dict] = []
    for team_dir in teams_root.iterdir():
        if not team_dir.is_dir():
            continue
        registry = _load(team_dir / "spawn_registry.json")
        for _agent_name, info in registry.items():
            if info.get("session_key") == session_key:
                info = dict(info)
                info.setdefault("data_dir", str(_normalize_data_dir()))
                matches.append(info)
    if len(matches) == 1:
        return matches[0]
    return None




def get_agent_runtime_state(team_name: str, agent_name: str, data_dir: str | Path | None = None) -> str:
    """Return runtime state: alive, dead, stale, or missing."""
    info = get_agent_record(team_name, agent_name, data_dir)
    if not info:
        return "missing"

    recorded_generation = str(info.get("runtime_generation") or "").strip()
    if not recorded_generation or recorded_generation != current_runtime_generation():
        return "stale"

    backend = info.get("backend", "")
    if backend == "tmux":
        alive = _tmux_pane_alive(info.get("tmux_target", ""))
        if alive is False:
            pid = info.get("pid", 0)
            if pid:
                return "alive" if _pid_alive(pid) else "dead"
        return "alive" if alive else "dead"
    if backend == "subprocess":
        return "alive" if _pid_alive(info.get("pid", 0)) else "dead"
    return "missing"


def is_agent_alive(team_name: str, agent_name: str) -> bool | None:
    """Check if a spawned agent process is still alive.

    Returns True if alive, False if dead, None if no spawn info found.
    """
    state = get_agent_runtime_state(team_name, agent_name)
    if state == "missing":
        return None
    return state == "alive"




def terminate_agent(team_name: str, agent_name: str, data_dir: str | Path | None = None) -> bool:
    """Best-effort terminate a registered agent process/window."""
    info = get_agent_record(team_name, agent_name, data_dir)
    if not info:
        return False

    backend = info.get("backend", "")
    if backend == "tmux":
        target = str(info.get("tmux_target") or "").strip()
        if target:
            subprocess.run(["tmux", "kill-window", "-t", target], capture_output=True, text=True)
            return True
    pid = int(info.get("pid", 0) or 0)
    if pid > 0:
        try:
            os.kill(pid, signal.SIGTERM)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return False
    return False


def list_dead_agents(team_name: str) -> list[str]:
    """Return names of agents whose processes are no longer alive."""
    registry = get_registry(team_name)
    dead = []
    for name, info in registry.items():
        state = get_agent_runtime_state(team_name, name)
        if state in {"dead", "stale"}:
            dead.append(name)
    return dead


def _tmux_pane_alive(target: str) -> bool:
    """Check if a tmux target (session:window) still has a running process."""
    if not target:
        return False
    # Check if the window exists at all
    result = subprocess.run(
        ["tmux", "list-panes", "-t", target, "-F", "#{pane_dead} #{pane_current_command}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        # Window doesn't exist anymore
        return False
    # Check pane_dead flag — "1" means the command has exited
    for line in result.stdout.strip().splitlines():
        parts = line.split(None, 1)
        if parts and parts[0] == "1":
            return False
        # Also check if the pane is just running a shell (agent exited, shell remains)
        if len(parts) >= 2 and parts[1] in ("bash", "zsh", "sh", "fish"):
            return False
    return True


def _pid_alive(pid: int) -> bool:
    """Check if a process with the given PID is still running."""
    if pid <= 0:
        return False
    try:
        import os
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we can't signal it
        return True


def _load(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save(path: Path, data: dict) -> None:
    import tempfile
    path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic write
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        import os
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        Path(tmp).replace(path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
