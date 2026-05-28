"""Claude Code session locator."""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

from clawteam.spawn.adapters import is_claude_command
from clawteam.spawn.command_validation import normalize_spawn_command

from .base import (
    CapturedSession,
    PreparedSession,
    SessionContext,
    env_session,
    has_any,
    option_value,
    timestamp_to_epoch,
)


class ClaudeSessionLocator:
    client = "claude"

    def matches(self, command: list[str]) -> bool:
        return is_claude_command(normalize_spawn_command(command))

    def prepare(self, command: list[str], context: SessionContext) -> PreparedSession:
        normalized = normalize_spawn_command(command)
        existing = option_value(normalized, "--session-id")
        if existing:
            return PreparedSession(
                command=list(command),
                client=self.client,
                session_id=existing,
                source="provided",
                confidence="exact",
                cwd=context.cwd,
                started_at=context.started_at,
                hint=context.hint,
            )
        resumed = option_value(normalized, "--resume") or option_value(normalized, "-r")
        if resumed:
            return PreparedSession(
                command=list(command),
                client=self.client,
                session_id=resumed,
                source="provided",
                confidence="exact",
                cwd=context.cwd,
                started_at=context.started_at,
                hint=context.hint,
            )
        if has_any(normalized, {"--continue", "-c", "--no-session-persistence"}):
            return PreparedSession(
                command=list(command),
                client=self.client,
                cwd=context.cwd,
                started_at=context.started_at,
                hint=context.hint,
            )

        session_id = str(uuid.uuid4())
        return PreparedSession(
            command=[*command, "--session-id", session_id],
            client=self.client,
            session_id=session_id,
            source="generated",
            confidence="exact",
            cwd=context.cwd,
            started_at=context.started_at,
            hint=context.hint,
        )

    def capture(self, prepared: PreparedSession, context: SessionContext) -> CapturedSession | None:
        if prepared.session_id:
            return CapturedSession(
                session_id=prepared.session_id,
                client=self.client,
                source=prepared.source or "prepared",
                confidence=prepared.confidence or "exact",
                cwd=context.cwd,
            )
        return self.current_session(context)

    def current_session(self, context: SessionContext) -> CapturedSession | None:
        if context.allow_environment:
            session_id = env_session("CLAUDE_CODE_SESSION", "CLAUDE_SESSION_ID")
            if session_id:
                return CapturedSession(session_id, self.client, "environment", "exact", context.cwd)

        project_dir = _claude_project_dir(context.cwd)
        if not project_dir:
            return None
        sessions = sorted(project_dir.glob("*.jsonl"), key=_claude_session_sort_key, reverse=True)
        if not sessions:
            return None
        session_path = sessions[0]
        return CapturedSession(session_path.stem, self.client, "transcript", "latest", context.cwd)

    def resume_command(self, command: list[str], session_id: str) -> list[str]:
        normalized = normalize_spawn_command(command)
        if option_value(normalized, "--resume") or option_value(normalized, "-r"):
            return list(command)
        return [*command, "--resume", session_id]


def _encode_claude_project_dir(workspace: Path) -> str:
    return re.sub(r"[^A-Za-z0-9-]", "-", str(workspace))


def _claude_project_dir(cwd: str) -> Path | None:
    if not cwd:
        return None
    projects = Path.home() / ".claude" / "projects"
    if not projects.exists():
        return None
    encoded = _encode_claude_project_dir(Path(cwd).resolve())
    direct = projects / encoded
    if direct.exists():
        return direct
    for candidate in projects.iterdir():
        if candidate.is_dir() and encoded in candidate.name:
            return candidate
    return None


def _claude_session_sort_key(path: Path) -> tuple[float, float]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return (0.0, 0.0)
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts = timestamp_to_epoch(payload.get("timestamp") or payload.get("createdAt"))
        if ts:
            return (ts, path.stat().st_mtime)
    try:
        return (0.0, path.stat().st_mtime)
    except OSError:
        return (0.0, 0.0)
