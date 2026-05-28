"""Facade for client-specific resumable session capture."""

from __future__ import annotations

import os
import threading
import time

from clawteam.spawn.command_validation import normalize_spawn_command
from clawteam.spawn.session_locators import (
    CapturedSession,
    CurrentSessionHint,
    PreparedSession,
    SessionContext,
    discover_codex_session,
    locator_for_client,
    locator_for_command,
    locators,
)
from clawteam.spawn.session_locators.base import CONFIDENCE_RANK, now_iso
from clawteam.spawn.sessions import SessionStore

SessionCapture = PreparedSession
__all__ = [
    "SessionCapture",
    "build_resume_command",
    "discover_codex_session",
    "persist_spawned_session",
    "prepare_session_capture",
    "save_current_agent_session",
]


def prepare_session_capture(
    command: list[str],
    *,
    team_name: str,
    agent_name: str,
    cwd: str | None = None,
    prompt: str | None = None,
    task_id: str = "",
) -> PreparedSession:
    """Prepare a command so its native client session can be captured."""
    context = _context(
        team_name=team_name,
        agent_name=agent_name,
        cwd=cwd,
        prompt=prompt,
        task_id=task_id,
    )
    locator = locator_for_command(command)
    if locator is None:
        return PreparedSession(
            command=list(command),
            team_name=team_name,
            agent_name=agent_name,
            cwd=cwd or "",
            hint=context.hint,
        )
    prepared = locator.prepare(command, context)
    prepared.team_name = team_name
    prepared.agent_name = agent_name
    return prepared


def persist_spawned_session(
    capture: PreparedSession,
    *,
    team_name: str | None = None,
    agent_name: str | None = None,
    command: list[str] | None = None,
    timeout_seconds: float = 8.0,
) -> str:
    """Persist a spawned session id under ~/.clawteam/sessions when possible."""
    if not capture.client:
        return ""

    context = SessionContext(
        team_name=team_name or capture.team_name,
        agent_name=agent_name or capture.agent_name,
        cwd=capture.cwd,
        hint=capture.hint,
        started_at=capture.started_at,
        allow_environment=False,
    )
    if not context.team_name or not context.agent_name:
        return ""

    locator = locator_for_client(capture.client)
    if locator is None:
        return ""

    if capture.async_capture and not capture.session_id:
        thread = threading.Thread(
            target=_capture_async,
            kwargs={
                "locator_client": capture.client,
                "capture": capture,
                "context": context,
                "command": command or capture.command,
                "timeout_seconds": timeout_seconds,
            },
            daemon=True,
        )
        thread.start()
        return ""

    captured = locator.capture(capture, context)
    if captured is None:
        return ""
    _save_captured(context, captured, command or capture.command)
    return captured.session_id


def save_current_agent_session(
    team_name: str,
    agent_name: str,
    *,
    cwd: str | None = None,
) -> str:
    """Persist the current leader agent session id."""
    context = SessionContext(team_name=team_name, agent_name=agent_name, cwd=cwd or os.getcwd())
    preferred_clients = []
    if os.environ.get("CODEX_THREAD_ID") or os.environ.get("CODEX_SESSION_ID"):
        preferred_clients.append("codex")
    if os.environ.get("CLAUDE_CODE_SESSION") or os.environ.get("CLAUDE_SESSION_ID"):
        preferred_clients.append("claude")
    for locator in [*(locator_for_client(c) for c in preferred_clients), *locators()]:
        if locator is None:
            continue
        captured = locator.current_session(context)
        if captured is None:
            continue
        _save_captured(context, captured, [])
        return captured.session_id
    return ""


def build_resume_command(
    command: list[str],
    session_id: str,
    client: str | None = None,
) -> list[str]:
    """Return a CLI-specific command that resumes a stored session id."""
    if not session_id:
        return list(command)
    locator = locator_for_client(client or "") if client else locator_for_command(command)
    if locator is None:
        return list(command)
    if client and not locator.matches(command):
        command = [_default_command_for_client(locator.client)]
    return locator.resume_command(command, session_id)


def _capture_async(
    *,
    locator_client: str,
    capture: PreparedSession,
    context: SessionContext,
    command: list[str],
    timeout_seconds: float,
) -> None:
    locator = locator_for_client(locator_client)
    if locator is None:
        return
    deadline = time.monotonic() + max(timeout_seconds, 0.0)
    while True:
        captured = locator.capture(capture, context)
        if captured is not None:
            _save_captured(context, captured, command)
            return
        if time.monotonic() >= deadline:
            return
        time.sleep(0.4)


def _save_captured(
    context: SessionContext,
    captured: CapturedSession,
    command: list[str],
) -> None:
    if not captured.session_id:
        return
    store = SessionStore(context.team_name)
    existing = store.load(context.agent_name)
    if existing and existing.session_id and not _should_overwrite(existing.state, captured.confidence):
        return
    store.save(
        agent_name=context.agent_name,
        session_id=captured.session_id,
        state={
            "client": captured.client,
            "source": captured.source,
            "cwd": captured.cwd or context.cwd,
            "command": command,
            "confidence": captured.confidence,
            "capturedAt": now_iso(),
        },
    )


def _should_overwrite(existing_state: dict, new_confidence: str) -> bool:
    old = str(existing_state.get("confidence") or "")
    return CONFIDENCE_RANK.get(new_confidence, 0) >= CONFIDENCE_RANK.get(old, 0)


def _context(
    *,
    team_name: str,
    agent_name: str,
    cwd: str | None,
    prompt: str | None,
    task_id: str,
) -> SessionContext:
    return SessionContext(
        team_name=team_name,
        agent_name=agent_name,
        cwd=cwd or "",
        hint=CurrentSessionHint.from_prompt(
            team_name=team_name,
            agent_name=agent_name,
            prompt=prompt,
            task_id=task_id,
        ),
        allow_environment=False,
    )


def client_for_command(command: list[str]) -> str:
    locator = locator_for_command(normalize_spawn_command(command))
    return locator.client if locator else ""


def _default_command_for_client(client: str) -> str:
    return {
        "claude": "claude",
        "codex": "codex",
        "gemini": "gemini",
        "opencode": "opencode",
        "openclaw": "openclaw",
        "nanobot": "nanobot",
    }.get(client, client)
