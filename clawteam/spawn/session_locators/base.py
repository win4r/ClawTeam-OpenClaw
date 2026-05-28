"""Common types and helpers for client-specific session capture."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

CONFIDENCE_RANK = {
    "latest": 10,
    "hinted": 20,
    "exact": 30,
}


@dataclass(frozen=True)
class CurrentSessionHint:
    """Metadata that helps match a spawned prompt to a native client session."""

    team_name: str
    agent_name: str
    task_id: str = ""
    prompt_text: str = ""
    prompt_fingerprint: str = ""

    @classmethod
    def from_prompt(
        cls,
        *,
        team_name: str,
        agent_name: str,
        prompt: str | None = None,
        task_id: str = "",
    ) -> "CurrentSessionHint":
        text = normalize_message_text(prompt)
        fingerprint = hashlib.sha256(text.encode("utf-8")).hexdigest() if text else ""
        return cls(
            team_name=team_name,
            agent_name=agent_name,
            task_id=task_id,
            prompt_text=text,
            prompt_fingerprint=fingerprint,
        )

    def tokens(self) -> list[str]:
        return [value for value in (self.team_name, self.agent_name, self.task_id) if value]


@dataclass
class SessionContext:
    team_name: str
    agent_name: str
    cwd: str = ""
    hint: CurrentSessionHint | None = None
    started_at: float = field(default_factory=time.time)
    allow_environment: bool = True


@dataclass
class PreparedSession:
    command: list[str]
    team_name: str = ""
    agent_name: str = ""
    client: str = ""
    session_id: str = ""
    source: str = ""
    confidence: str = ""
    cwd: str = ""
    started_at: float = field(default_factory=time.time)
    async_capture: bool = False
    hint: CurrentSessionHint | None = None


@dataclass(frozen=True)
class CapturedSession:
    session_id: str
    client: str
    source: str
    confidence: str
    cwd: str = ""


class SessionLocator(Protocol):
    client: str

    def matches(self, command: list[str]) -> bool:
        ...

    def prepare(self, command: list[str], context: SessionContext) -> PreparedSession:
        ...

    def capture(self, prepared: PreparedSession, context: SessionContext) -> CapturedSession | None:
        ...

    def current_session(self, context: SessionContext) -> CapturedSession | None:
        ...

    def resume_command(self, command: list[str], session_id: str) -> list[str]:
        ...


def option_value(command: list[str], option: str) -> str:
    for i, item in enumerate(command):
        if item == option and i + 1 < len(command):
            return command[i + 1]
        if item.startswith(option + "="):
            return item.split("=", 1)[1]
    return ""


def has_any(command: list[str], options: set[str]) -> bool:
    return any(item in options for item in command)


def normalize_message_text(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip().lower()[:4000]


def same_path(left: str | Path, right: str | Path) -> bool:
    try:
        return Path(left).expanduser().resolve() == Path(right).expanduser().resolve()
    except Exception:
        return str(left) == str(right)


def timestamp_to_epoch(value: Any) -> float:
    if not value:
        return 0.0
    try:
        text = str(value)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        return datetime.fromisoformat(text).timestamp()
    except Exception:
        return 0.0


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_json_load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def first_json_line(path: Path) -> dict[str, Any]:
    try:
        first = path.read_text(encoding="utf-8").split("\n", 1)[0]
        payload = json.loads(first)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def recent_files(root: Path, pattern: str, *, since: float = 0.0, limit: int = 80) -> list[Path]:
    if not root.exists():
        return []
    threshold = since - 10 if since else 0
    paths: list[Path] = []
    for path in root.rglob(pattern):
        try:
            if path.is_file() and path.stat().st_mtime >= threshold:
                paths.append(path)
        except OSError:
            continue
    return sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True)[:limit]


def command_basename(command: list[str]) -> str:
    if not command:
        return ""
    return Path(command[0]).name.lower()


def env_session(*names: str) -> str:
    for name in names:
        value = os.environ.get(name)
        if value and value.strip():
            return value.strip()
    return ""
