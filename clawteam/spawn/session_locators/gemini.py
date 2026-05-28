"""Gemini CLI session locator."""

from __future__ import annotations

import json
import os
from pathlib import Path

from clawteam.spawn.adapters import is_gemini_command
from clawteam.spawn.command_validation import normalize_spawn_command

from .base import (
    CapturedSession,
    PreparedSession,
    SessionContext,
    option_value,
    safe_json_load,
    same_path,
    timestamp_to_epoch,
)


class GeminiSessionLocator:
    client = "gemini"

    def matches(self, command: list[str]) -> bool:
        return is_gemini_command(normalize_spawn_command(command))

    def prepare(self, command: list[str], context: SessionContext) -> PreparedSession:
        session_id = option_value(normalize_spawn_command(command), "--resume")
        return PreparedSession(
            command=list(command),
            client=self.client,
            session_id="" if session_id == "latest" else session_id,
            source="provided" if session_id and session_id != "latest" else "",
            confidence="exact" if session_id and session_id != "latest" else "",
            cwd=context.cwd,
            started_at=context.started_at,
            async_capture=not bool(session_id),
            hint=context.hint,
        )

    def capture(self, prepared: PreparedSession, context: SessionContext) -> CapturedSession | None:
        if prepared.session_id:
            return CapturedSession(prepared.session_id, self.client, "provided", "exact", context.cwd)
        return self.current_session(context)

    def current_session(self, context: SessionContext) -> CapturedSession | None:
        cwd = Path(context.cwd).resolve() if context.cwd else None
        sessions: list[Path] = []
        tmp_root = _gemini_home() / "tmp"
        if not tmp_root.exists() or cwd is None:
            return None
        for project_dir in tmp_root.iterdir():
            marker = project_dir / ".project_root"
            if not marker.is_file():
                continue
            try:
                if not same_path(marker.read_text(encoding="utf-8").strip(), cwd):
                    continue
            except OSError:
                continue
            sessions.extend((project_dir / "chats").glob("*.json"))
        sessions = sorted(sessions, key=_gemini_session_sort_key, reverse=True)
        for path in sessions:
            payload = safe_json_load(path)
            if not isinstance(payload, dict):
                continue
            session_id = payload.get("sessionId")
            if isinstance(session_id, str) and session_id:
                return CapturedSession(session_id, self.client, "transcript", "latest", context.cwd)
        return None

    def resume_command(self, command: list[str], session_id: str) -> list[str]:
        normalized = normalize_spawn_command(command)
        if option_value(normalized, "--resume"):
            return list(command)
        return [*command, "--resume", session_id]


def _gemini_home() -> Path:
    cli_home = os.environ.get("GEMINI_CLI_HOME")
    if cli_home:
        return Path(cli_home).expanduser() / ".gemini"
    legacy = os.environ.get("GEMINI_HOME")
    if legacy:
        return Path(legacy).expanduser()
    return Path.home() / ".gemini"


def _gemini_session_sort_key(path: Path) -> tuple[float, float]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        try:
            return (0.0, path.stat().st_mtime)
        except OSError:
            return (0.0, 0.0)
    for field in ("lastUpdated", "startTime"):
        ts = timestamp_to_epoch(payload.get(field))
        if ts:
            return (ts, path.stat().st_mtime)
    try:
        return (0.0, path.stat().st_mtime)
    except OSError:
        return (0.0, 0.0)
