"""Per-worker turn heartbeat: data-driven stall detection signal."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from clawteam.fileutil import atomic_write_text


@dataclass(frozen=True)
class Heartbeat:
    agent: str
    alive: bool
    turn_count: int
    last_turn_at: datetime
    task_id: Optional[str] = None


def _path(team_dir: Path, agent: str) -> Path:
    return team_dir / "heartbeats" / f"{agent}.json"


def write_heartbeat(
    team_dir: Path,
    *,
    agent: str,
    alive: bool,
    turn_count: int,
    task_id: Optional[str] = None,
) -> None:
    """Write a heartbeat file atomically."""
    path = _path(team_dir, agent)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "agent": agent,
        "alive": alive,
        "turn_count": turn_count,
        "last_turn_at": datetime.now(timezone.utc).isoformat(),
        "task_id": task_id,
    }
    atomic_write_text(path, json.dumps(payload))


def read_heartbeat(team_dir: Path, agent: str) -> Optional[Heartbeat]:
    """Return the latest heartbeat for *agent*, or None if it doesn't exist."""
    path = _path(team_dir, agent)
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    return Heartbeat(
        agent=data["agent"],
        alive=data["alive"],
        turn_count=data["turn_count"],
        last_turn_at=datetime.fromisoformat(data["last_turn_at"]),
        task_id=data.get("task_id"),
    )


def list_heartbeats(team_dir: Path) -> list:
    """Return all heartbeats found in *team_dir*."""
    hb_dir = team_dir / "heartbeats"
    if not hb_dir.exists():
        return []
    out = []
    for p in sorted(hb_dir.glob("*.json")):
        hb = read_heartbeat(team_dir, p.stem)
        if hb is not None:
            out.append(hb)
    return out
