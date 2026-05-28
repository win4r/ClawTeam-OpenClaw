"""Registry for client-specific session locators."""

from __future__ import annotations

from clawteam.spawn.command_validation import normalize_spawn_command

from .base import (
    CapturedSession,
    CurrentSessionHint,
    PreparedSession,
    SessionContext,
    SessionLocator,
)
from .claude import ClaudeSessionLocator
from .codex import CodexSessionLocator, discover_codex_session
from .gemini import GeminiSessionLocator
from .nanobot import NanobotSessionLocator
from .openclaw import OpenClawSessionLocator
from .opencode import OpenCodeSessionLocator

_LOCATORS: list[SessionLocator] = [
    ClaudeSessionLocator(),
    CodexSessionLocator(),
    GeminiSessionLocator(),
    OpenCodeSessionLocator(),
    OpenClawSessionLocator(),
    NanobotSessionLocator(),
]


def locators() -> list[SessionLocator]:
    return list(_LOCATORS)


def locator_for_command(command: list[str]) -> SessionLocator | None:
    normalized = normalize_spawn_command(command)
    for locator in _LOCATORS:
        if locator.matches(normalized):
            return locator
    return None


def locator_for_client(client: str) -> SessionLocator | None:
    normalized = client.strip().lower()
    aliases = {
        "claude-code": "claude",
        "codex-cli": "codex",
        "gemini-cli": "gemini",
    }
    normalized = aliases.get(normalized, normalized)
    for locator in _LOCATORS:
        if locator.client == normalized:
            return locator
    return None


__all__ = [
    "CapturedSession",
    "CurrentSessionHint",
    "PreparedSession",
    "SessionContext",
    "SessionLocator",
    "discover_codex_session",
    "locator_for_client",
    "locator_for_command",
    "locators",
]
