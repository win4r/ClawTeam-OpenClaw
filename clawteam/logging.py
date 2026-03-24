"""Logging configuration for ClawTeam operational logs."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional


_loggers: dict[str, logging.Logger] = {}


def get_logger(component: str, team_name: Optional[str] = None) -> logging.Logger:
    """Get or create a logger for the specified component and team.

    Args:
        component: The component name (e.g., 'spawn', 'tasks', 'manager')
        team_name: Optional team name for team-specific logging

    Returns:
        A configured logger instance
    """
    logger_key = f"{component}:{team_name or 'global'}"

    if logger_key in _loggers:
        return _loggers[logger_key]

    logger = logging.getLogger(f"clawteam.{component}")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(component)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(_ComponentFilter(component))
    logger.addHandler(console_handler)

    if team_name:
        log_dir = Path.home() / ".clawteam" / "logs" / team_name
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / "clawteam.log"
            file_handler = logging.FileHandler(log_file)
            file_handler.setFormatter(formatter)
            file_handler.addFilter(_ComponentFilter(component))
            logger.addHandler(file_handler)
        except Exception:
            pass

    _loggers[logger_key] = logger
    return logger


class _ComponentFilter(logging.Filter):
    """Filter that adds component name to log records."""

    def __init__(self, component: str):
        super().__init__()
        self.component = component

    def filter(self, record: logging.LogRecord) -> bool:
        record.component = self.component
        return True


def log_spawn(
    team_name: str,
    agent_name: str,
    status: str,
    message: str,
    error: Optional[str] = None,
) -> None:
    """Log a spawn event."""
    logger = get_logger("spawn", team_name)
    if status == "success":
        logger.info(f"Agent '{agent_name}' spawned: {message}")
    elif status == "error":
        logger.error(f"Agent '{agent_name}' spawn failed: {message} | Error: {error}")
    else:
        logger.debug(f"Agent '{agent_name}' spawn: {message}")


def log_task(
    team_name: str,
    action: str,
    task_id: str,
    subject: str,
    agent: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    """Log a task event."""
    logger = get_logger("tasks", team_name)
    msg = f"Task {action}: {task_id} ({subject})"
    if agent:
        msg += f" | owner: {agent}"

    if action in ("created", "completed"):
        logger.info(msg)
    elif action in ("failed", "error"):
        logger.error(f"{msg} | Error: {error}")
    elif action in ("updated", "started", "blocked"):
        logger.debug(msg)


def log_member(
    team_name: str,
    action: str,
    member_name: str,
    error: Optional[str] = None,
) -> None:
    """Log a team member event."""
    logger = get_logger("manager", team_name)
    if action == "added":
        logger.info(f"Member added: {member_name}")
    elif action == "removed":
        logger.info(f"Member removed: {member_name}")
    elif action == "error":
        logger.error(f"Member operation failed: {member_name} | Error: {error}")


def log_workspace(
    team_name: str,
    action: str,
    agent_name: str,
    path: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    """Log a workspace event."""
    logger = get_logger("workspace", team_name)
    msg = f"Workspace {action}: {agent_name}"
    if path:
        msg += f" | path: {path}"

    if action in ("created", "cleaned", "merged"):
        logger.info(msg)
    elif action == "error":
        logger.error(f"{msg} | Error: {error}")
    else:
        logger.debug(msg)


def log_cli(
    command: str,
    status: str,
    message: str,
    error: Optional[str] = None,
) -> None:
    """Log a CLI command execution."""
    logger = get_logger("cli")
    if status == "success":
        logger.info(f"CLI command '{command}': {message}")
    elif status == "error":
        logger.error(f"CLI command '{command}' failed: {message} | Error: {error}")
    else:
        logger.debug(f"CLI command '{command}': {message}")
