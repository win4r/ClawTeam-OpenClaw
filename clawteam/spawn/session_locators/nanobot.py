"""Nanobot session locator."""

from __future__ import annotations

import os
from pathlib import Path

from clawteam.spawn.adapters import is_nanobot_command
from clawteam.spawn.command_validation import normalize_spawn_command

from .base import CapturedSession, PreparedSession, SessionContext, option_value


class NanobotSessionLocator:
    client = "nanobot"

    def matches(self, command: list[str]) -> bool:
        return is_nanobot_command(normalize_spawn_command(command))

    def prepare(self, command: list[str], context: SessionContext) -> PreparedSession:
        session_id = option_value(normalize_spawn_command(command), "--session")
        return PreparedSession(
            command=list(command),
            client=self.client,
            session_id=session_id,
            source="provided" if session_id else "",
            confidence="exact" if session_id else "",
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
        home = Path(os.environ.get("NANOBOT_HOME", Path.home() / ".nanobot")).expanduser()
        sessions_dir = home / "workspace" / "sessions"
        if not sessions_dir.exists():
            return None
        sessions = sorted(sessions_dir.glob("*.jsonl"), key=lambda path: path.stat().st_mtime, reverse=True)
        if not sessions:
            return None
        return CapturedSession(sessions[0].stem, self.client, "transcript", "latest", context.cwd)

    def resume_command(self, command: list[str], session_id: str) -> list[str]:
        normalized = normalize_spawn_command(command)
        if option_value(normalized, "--session"):
            return list(command)
        return [*command, "--session", session_id]
