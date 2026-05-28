"""Codex CLI session locator."""

from __future__ import annotations

from pathlib import Path

from clawteam.spawn.adapters import is_codex_command
from clawteam.spawn.command_validation import normalize_spawn_command

from .base import (
    CapturedSession,
    CurrentSessionHint,
    PreparedSession,
    SessionContext,
    env_session,
    first_json_line,
    recent_files,
    same_path,
    timestamp_to_epoch,
)


class CodexSessionLocator:
    client = "codex"

    def matches(self, command: list[str]) -> bool:
        return is_codex_command(normalize_spawn_command(command))

    def prepare(self, command: list[str], context: SessionContext) -> PreparedSession:
        session_id = _codex_resume_session_id(normalize_spawn_command(command))
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
        current = env_session("CODEX_THREAD_ID", "CODEX_SESSION_ID") if context.allow_environment else ""
        workspace = Path(context.cwd).resolve() if context.cwd else None
        candidates = _codex_session_candidates(since=0.0 if context.allow_environment else context.started_at)
        if current:
            for path in candidates:
                meta = _codex_meta(path)
                if meta.get("id") == current and _meta_matches_workspace(meta, workspace):
                    return CapturedSession(current, self.client, "environment", "exact", context.cwd)
            return CapturedSession(current, self.client, "environment", "exact", context.cwd)

        scored: list[tuple[int, float, str]] = []
        for path in candidates:
            meta = _codex_meta(path)
            session_id = str(meta.get("id") or "")
            if not session_id or not _meta_matches_workspace(meta, workspace):
                continue
            raw = _read_prefix(path)
            score = 10
            source = "transcript"
            confidence = "latest"
            if context.hint and all(token in raw for token in context.hint.tokens()):
                score = 20
                confidence = "hinted"
            sort_ts = timestamp_to_epoch(meta.get("timestamp")) or path.stat().st_mtime
            scored.append((score, sort_ts, f"{session_id}|{source}|{confidence}"))
        if not scored:
            return None
        _, _, packed = max(scored, key=lambda item: (item[0], item[1]))
        session_id, source, confidence = packed.split("|", 2)
        return CapturedSession(session_id, self.client, source, confidence, context.cwd)

    def resume_command(self, command: list[str], session_id: str) -> list[str]:
        normalized = normalize_spawn_command(command)
        if len(normalized) >= 2 and normalized[1] in {"resume", "fork"}:
            return list(command)
        return [*command, "resume", session_id]


def discover_codex_session(
    *,
    team_name: str,
    agent_name: str,
    cwd: str,
    since: float,
    timeout_seconds: float = 8.0,
) -> str:
    import time

    hint_context = SessionContext(
        team_name=team_name,
        agent_name=agent_name,
        cwd=cwd,
        hint=CurrentSessionHint.from_prompt(team_name=team_name, agent_name=agent_name),
        started_at=since,
        allow_environment=False,
    )
    deadline = time.monotonic() + max(timeout_seconds, 0.0)
    locator = CodexSessionLocator()
    while True:
        found = locator.current_session(hint_context)
        if found:
            return found.session_id
        if time.monotonic() >= deadline:
            return ""
        time.sleep(0.4)


def _codex_session_id(path: Path) -> str:
    return str(_codex_meta(path).get("id") or "")


def _codex_meta(path: Path) -> dict:
    first = first_json_line(path)
    if first.get("type") != "session_meta":
        return {}
    payload = first.get("payload")
    return payload if isinstance(payload, dict) else {}


def _codex_session_candidates(*, since: float = 0.0) -> list[Path]:
    return recent_files(Path.home() / ".codex" / "sessions", "*.jsonl", since=since, limit=100)


def _meta_matches_workspace(meta: dict, workspace: Path | None) -> bool:
    if workspace is None:
        return True
    cwd = meta.get("cwd")
    return isinstance(cwd, str) and same_path(cwd, workspace)


def _read_prefix(path: Path, max_lines: int = 120) -> str:
    parts: list[str] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for i, line in enumerate(fh):
                parts.append(line)
                if i >= max_lines:
                    break
    except OSError:
        return ""
    return "".join(parts)


def _codex_resume_session_id(command: list[str]) -> str:
    if len(command) < 2 or command[1] != "resume":
        return ""
    for item in command[2:]:
        if item.startswith("-"):
            continue
        return item
    return ""
