"""Tool call extraction from OpenClaw session transcripts.

Reads session transcript after agent completion, extracts structured
tool calls, and writes them to JSONL log files.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


# Sensitive patterns to redact
_REDACT_PATTERNS = [
    (re.compile(r'(api[_-]?key|token|password|secret|auth)["\s:=]+\S+', re.I), "[REDACTED]"),
]

# Maximum characters for result summary
MAX_RESULT_SUMMARY = 200


def redact_sensitive(text: str) -> str:
    """Redact sensitive data from text."""
    for pattern, replacement in _REDACT_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def _get_session_uuid(session_key: str) -> Optional[str]:
    """Map session key to UUID using sessions.json.

    session_key format: "agent:main:clawteam-{team}-{agent}"
    But sessions.json keys may be: "clawteam-{team}-{agent}" (without agent:main: prefix)
    So we try both formats.
    """
    sessions_file = Path.home() / ".openclaw" / "agents" / "main" / "sessions.json"
    if not sessions_file.exists():
        return None
    try:
        with open(sessions_file, "r", encoding="utf-8") as f:
            sessions = json.load(f)

        # Build list of keys to try
        keys_to_try = [session_key]
        # Also try without "agent:main:" prefix
        if session_key.startswith("agent:main:"):
            keys_to_try.append(session_key[len("agent:main:"):])

        # sessions.json format: {"sessions": [{"key": "...", "id": "..."}, ...]}
        for key in keys_to_try:
            for s in sessions.get("sessions", []):
                if s.get("key") == key:
                    return s.get("id")
            # Try alternative formats
            if key in sessions:
                return sessions[key]
    except (json.JSONDecodeError, OSError):
        pass
    return None


def extract_tool_calls_from_transcript(
    session_key: str,
    team_name: str,
    agent_name: str,
) -> tuple[int, Optional[str]]:
    """Extract tool calls from OpenClaw session transcript.

    Reads session transcript JSONL file, parses tool calls, and writes to JSONL log.

    Returns:
        (tool_call_count, log_file_path) or (0, None) on failure
    """
    # Try to find transcript file
    transcript_path = _find_transcript(session_key)
    if transcript_path is None:
        return 0, None

    messages = []
    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        messages.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except OSError:
        return 0, None

    return _write_tool_calls(messages, team_name, agent_name)


def _find_transcript(session_key: str) -> Optional[Path]:
    """Find transcript file for given session key.

    Priority:
    1. ~/.openclaw/agents/main/sessions/<UUID>.jsonl (real path)
    2. ~/.openclaw/sessions/<key>/transcript.jsonl (fallback)
    3. ~/.openclaw/sessions/<key>.jsonl (fallback)
    """
    # Priority 1: Real path with UUID
    uuid = _get_session_uuid(session_key)
    if uuid:
        real_path = Path.home() / ".openclaw" / "agents" / "main" / "sessions" / f"{uuid}.jsonl"
        if real_path.exists():
            return real_path

    # Priority 2: Fallback paths
    for alt in [
        Path.home() / ".openclaw" / "sessions" / session_key / "transcript.jsonl",
        Path.home() / ".openclaw" / "sessions" / f"{session_key}.jsonl",
    ]:
        if alt.exists():
            return alt

    return None


def _write_tool_calls(
    messages: list[dict],
    team_name: str,
    agent_name: str,
) -> tuple[int, Optional[str]]:
    """Parse messages for tool calls and write JSONL log."""
    log_dir = Path.home() / ".clawteam" / "logs" / team_name
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{agent_name}-tools.log"

    tool_calls = []
    now = datetime.now(timezone.utc).isoformat()

    for msg in messages:
        msg_type = msg.get("type", "")

        # OpenClaw transcript format: tool_call messages
        if msg_type == "tool_call" or msg.get("tool"):
            tool_name = msg.get("tool", msg.get("name", "unknown"))
            params = msg.get("input", msg.get("params", msg.get("arguments", {})))

            # Redact sensitive params
            params_str = redact_sensitive(json.dumps(params, ensure_ascii=False))

            entry = {
                "timestamp": msg.get("timestamp", now),
                "tool": tool_name,
                "params_summary": params_str[:500],  # Truncate long params
                "type": "call",
            }
            tool_calls.append(entry)

        elif msg_type == "tool_result" or msg.get("tool_result"):
            result = msg.get("result", msg.get("content", ""))
            result_str = str(result)[:MAX_RESULT_SUMMARY]
            status = "error" if msg.get("is_error") else "success"

            entry = {
                "timestamp": msg.get("timestamp", now),
                "tool": msg.get("tool", "unknown"),
                "status": status,
                "result_summary": redact_sensitive(result_str),
                "type": "result",
            }
            tool_calls.append(entry)

    # Write JSONL
    if tool_calls:
        # Log rotation: if file > 10MB, rename and create new
        if log_file.exists() and log_file.stat().st_size > 10 * 1024 * 1024:
            rotated = log_file.with_suffix(f".{now[:10]}.log")
            log_file.rename(rotated)

        with open(log_file, "a", encoding="utf-8") as f:
            for call in tool_calls:
                f.write(json.dumps(call, ensure_ascii=False) + "\n")
        # Set permissions to owner-only
        log_file.chmod(0o600)

    return len(tool_calls), str(log_file) if tool_calls else None


def extract_and_log(
    team_name: str,
    agent_name: str,
    session_key: Optional[str] = None,
) -> dict[str, Any]:
    """Extract tool calls and write to log. Called from lifecycle_on_exit.

    Returns dict with: status, tool_calls, log_file
    """
    if not session_key:
        session_key = f"agent:main:clawteam-{team_name}-{agent_name}"

    try:
        count, log_file = extract_tool_calls_from_transcript(
            session_key=session_key,
            team_name=team_name,
            agent_name=agent_name,
        )
        return {
            "status": "ok",
            "tool_calls": count,
            "log_file": log_file or "",
        }
    except Exception as e:
        return {
            "status": "error",
            "tool_calls": 0,
            "log_file": "",
            "error": str(e),
        }


# TODO: extract_summary_from_transcript is currently unused.
# Reserved for future use when we need agent activity summaries.
def extract_summary_from_transcript(
    session_key: str,
) -> dict[str, Any]:
    """Extract a summary of what the agent did from transcript.

    Returns dict with: task_summary, tool_count, error_count
    """
    transcript_path = _find_transcript(session_key)
    if transcript_path is None:
        return {"task_summary": "", "tool_count": 0, "error_count": 0}

    tool_count = 0
    error_count = 0
    last_assistant_msg = ""

    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue

                msg_type = msg.get("type", "")
                if msg_type in ("tool_call", "tool"):
                    tool_count += 1
                elif msg_type == "tool_result" and msg.get("is_error"):
                    error_count += 1
                elif msg_type == "assistant":
                    content = msg.get("content", "")
                    if isinstance(content, str):
                        last_assistant_msg = content[:200]
                    elif isinstance(content, list):
                        for part in content:
                            if isinstance(part, dict) and part.get("type") == "text":
                                last_assistant_msg = part.get("text", "")[:200]
                                break
    except OSError:
        pass

    return {
        "task_summary": last_assistant_msg,
        "tool_count": tool_count,
        "error_count": error_count,
    }
