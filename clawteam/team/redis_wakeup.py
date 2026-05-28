"""Optional Redis wakeup layer for team coordination."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from clawteam.fileutil import atomic_write_text
from clawteam.paths import ensure_within_root, validate_identifier
from clawteam.team.models import get_data_dir


@dataclass
class RedisWakeup:
    """Resolved Redis wakeup state."""

    enabled: bool
    url: str = ""
    reason: str = ""
    started: bool = False
    pid: int = 0


def team_channel(team_name: str, suffix: str) -> str:
    validate_identifier(team_name, "team name")
    return f"clawteam:{team_name}:{suffix}"


def agent_channel(team_name: str, agent_name: str) -> str:
    validate_identifier(agent_name, "agent name")
    return team_channel(team_name, f"agent:{agent_name}")


def resolve_wakeup(team_name: str, mode: str = "auto") -> RedisWakeup:
    """Resolve and optionally start Redis for a watcher.

    Modes:
    - off: disabled
    - redis://...: use the explicit URL
    - auto: use env/state URL, or start local redis-server if available
    """
    mode = (mode or "auto").strip()
    if mode == "off":
        return RedisWakeup(False, reason="disabled")
    if _redis_module() is None:
        return RedisWakeup(False, reason="python redis package not installed")

    if mode.startswith("redis://") or mode.startswith("rediss://"):
        return _ping(mode)

    url = os.environ.get("CLAWTEAM_REDIS_URL") or _read_state_url(team_name)
    if url:
        resolved = _ping(url)
        if resolved.enabled:
            return resolved

    if mode != "auto":
        return RedisWakeup(False, reason=f"unsupported redis mode: {mode}")

    redis_server = shutil.which("redis-server")
    if not redis_server:
        return RedisWakeup(False, reason="redis-server not found")

    return _start_local_redis(team_name, redis_server)


def publish_wakeup(
    team_name: str,
    channel: str,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> bool:
    """Best-effort Redis publish. Never raises to callers."""
    redis_mod = _redis_module()
    if redis_mod is None:
        return False
    url = os.environ.get("CLAWTEAM_REDIS_URL") or _read_state_url(team_name)
    if not url:
        return False
    try:
        client = redis_mod.from_url(url)
        message = {
            "team": team_name,
            "type": event_type,
            "payload": payload or {},
            "timestamp": time.time(),
        }
        client.publish(channel, json.dumps(message, ensure_ascii=False))
        return True
    except Exception:
        return False


def subscribe_client(url: str):
    redis_mod = _redis_module()
    if redis_mod is None:
        return None
    try:
        return redis_mod.from_url(url)
    except Exception:
        return None


def _redis_module():
    try:
        import redis
    except ImportError:
        return None
    return redis


def _team_dir(team_name: str) -> Path:
    return ensure_within_root(get_data_dir() / "teams", validate_identifier(team_name, "team name"))


def _state_path(team_name: str) -> Path:
    return _team_dir(team_name) / "redis.json"


def _read_state_url(team_name: str) -> str:
    path = _state_path(team_name)
    if not path.exists():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return str(data.get("url") or "")
    except Exception:
        return ""


def _write_state(team_name: str, data: dict[str, Any]) -> None:
    atomic_write_text(_state_path(team_name), json.dumps(data, indent=2, ensure_ascii=False))


def _ping(url: str) -> RedisWakeup:
    redis_mod = _redis_module()
    if redis_mod is None:
        return RedisWakeup(False, url=url, reason="python redis package not installed")
    try:
        client = redis_mod.from_url(url)
        client.ping()
        return RedisWakeup(True, url=url)
    except Exception as exc:
        return RedisWakeup(False, url=url, reason=str(exc))


def _start_local_redis(team_name: str, redis_server: str) -> RedisWakeup:
    port = _find_open_port()
    url = f"redis://127.0.0.1:{port}/0"
    redis_dir = _team_dir(team_name) / "redis"
    redis_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        redis_server,
        "--bind",
        "127.0.0.1",
        "--port",
        str(port),
        "--save",
        "",
        "--appendonly",
        "no",
        "--dir",
        str(redis_dir),
    ]
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as exc:
        return RedisWakeup(False, url=url, reason=str(exc))

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        resolved = _ping(url)
        if resolved.enabled:
            _write_state(
                team_name,
                {
                    "url": url,
                    "pid": proc.pid,
                    "startedBy": "clawteam team watch",
                    "startedAt": time.time(),
                },
            )
            return RedisWakeup(True, url=url, started=True, pid=proc.pid)
        if proc.poll() is not None:
            return RedisWakeup(False, url=url, reason="redis-server exited during startup")
        time.sleep(0.1)
    return RedisWakeup(False, url=url, reason="redis-server startup timed out")


def _find_open_port(start: int = 6380, attempts: int = 100) -> int:
    for port in range(start, start + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("no open Redis port found")
