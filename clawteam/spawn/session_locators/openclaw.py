"""OpenClaw session locator."""

from __future__ import annotations

from pathlib import Path

from clawteam.spawn.adapters import is_openclaw_command
from clawteam.spawn.command_validation import normalize_spawn_command

from .base import (
    CapturedSession,
    PreparedSession,
    SessionContext,
    first_json_line,
    option_value,
    safe_json_load,
    same_path,
)


class OpenClawSessionLocator:
    client = "openclaw"

    def matches(self, command: list[str]) -> bool:
        return is_openclaw_command(normalize_spawn_command(command))

    def prepare(self, command: list[str], context: SessionContext) -> PreparedSession:
        normalized = normalize_spawn_command(command)
        session_id = option_value(normalized, "--session-id") or option_value(normalized, "--session")
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
        home = Path.home() / ".openclaw"
        agents_dir = home / "agents"
        if not agents_dir.exists():
            return None
        matches: list[tuple[float, str]] = []
        for session_path in agents_dir.glob("*/sessions/*.jsonl"):
            if context.cwd:
                header = first_json_line(session_path)
                cwd = header.get("cwd")
                if isinstance(cwd, str) and not same_path(cwd, context.cwd):
                    continue
            session_id = session_path.stem
            store = safe_json_load(session_path.parent / "sessions.json")
            if isinstance(store, dict):
                for item in store.values():
                    if isinstance(item, dict) and item.get("sessionId") == session_path.stem:
                        session_id = str(item.get("sessionId"))
                        break
            matches.append((session_path.stat().st_mtime, session_id))
        if not matches:
            return None
        _, session_id = max(matches)
        return CapturedSession(session_id, self.client, "transcript", "latest", context.cwd)

    def resume_command(self, command: list[str], session_id: str) -> list[str]:
        normalized = normalize_spawn_command(command)
        if option_value(normalized, "--session-id") or option_value(normalized, "--session"):
            return list(command)
        if "tui" in normalized:
            return [*command, "--session", f"agent:main:resume:{session_id}"]
        return [*command, "--session-id", session_id]
