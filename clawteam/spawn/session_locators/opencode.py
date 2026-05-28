"""OpenCode session locator."""

from __future__ import annotations

import json
import os
import shutil
import subprocess

from clawteam.spawn.adapters import is_opencode_command
from clawteam.spawn.command_validation import normalize_spawn_command

from .base import CapturedSession, PreparedSession, SessionContext, option_value, same_path


class OpenCodeSessionLocator:
    client = "opencode"

    def matches(self, command: list[str]) -> bool:
        return is_opencode_command(normalize_spawn_command(command))

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
        binary = shutil.which("opencode")
        if not binary or not context.cwd or not os.path.isdir(context.cwd):
            return None
        result = subprocess.run(
            [binary, "session", "list", "--format", "json"],
            cwd=context.cwd,
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
        if result.returncode != 0:
            return None
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            return None
        matches = []
        for item in payload if isinstance(payload, list) else []:
            session_id = item.get("id")
            directory = item.get("directory")
            if isinstance(session_id, str) and isinstance(directory, str) and same_path(directory, context.cwd):
                matches.append(item)
        matches.sort(key=lambda item: item.get("updated", 0), reverse=True)
        if not matches:
            return None
        return CapturedSession(matches[0]["id"], self.client, "client-list", "latest", context.cwd)

    def resume_command(self, command: list[str], session_id: str) -> list[str]:
        normalized = normalize_spawn_command(command)
        if option_value(normalized, "--session"):
            return list(command)
        return [*command, "--session", session_id]
