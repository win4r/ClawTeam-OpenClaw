"""Tests for tool call extraction."""

import json
import tempfile
from pathlib import Path

import pytest

from clawteam.spawn.tool_calls import (
    redact_sensitive,
    _write_tool_calls,
    _get_session_uuid,
    extract_and_log,
)


class TestRedactSensitive:
    def test_redacts_api_key(self):
        text = 'api_key="sk-abc123def456"'
        result = redact_sensitive(text)
        assert "sk-abc123" not in result
        assert "[REDACTED]" in result

    def test_redacts_token(self):
        text = 'token=ghp_abc123'
        result = redact_sensitive(text)
        assert "ghp_abc123" not in result

    def test_redacts_password(self):
        text = 'password: "mysecretpass"'
        result = redact_sensitive(text)
        assert "mysecretpass" not in result

    def test_redacts_secret(self):
        text = 'secret="mysecretvalue"'
        result = redact_sensitive(text)
        assert "mysecretvalue" not in result

    def test_preserves_normal_text(self):
        text = "This is a normal message about api design"
        result = redact_sensitive(text)
        assert result == text


class TestWriteToolCalls:
    def test_writes_jsonl_format(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        messages = [
            {"type": "tool_call", "tool": "read", "input": {"path": "test.py"}, "timestamp": "2026-03-25T00:00:00Z"},
            {"type": "tool_result", "tool": "read", "result": "file content", "timestamp": "2026-03-25T00:00:01Z"},
        ]
        count, path = _write_tool_calls(messages, "test-team", "test-agent")
        assert count == 2
        assert path is not None
        # Verify JSONL format
        with open(path) as f:
            lines = f.readlines()
        assert len(lines) == 2
        entry = json.loads(lines[0])
        assert entry["tool"] == "read"
        assert entry["type"] == "call"

    def test_empty_messages(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        count, path = _write_tool_calls([], "test-team", "test-agent")
        assert count == 0
        assert path is None

    def test_redacts_sensitive_params(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        messages = [
            {"type": "tool_call", "tool": "exec", "input": {"api_key": "sk-123abc"}, "timestamp": "2026-03-25T00:00:00Z"},
        ]
        count, path = _write_tool_calls(messages, "test-team", "test-agent")
        with open(path) as f:
            content = f.read()
        assert "sk-123abc" not in content
        assert "[REDACTED]" in content

    def test_log_file_permissions(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        messages = [
            {"type": "tool_call", "tool": "read", "input": {}, "timestamp": "2026-03-25T00:00:00Z"},
        ]
        count, path = _write_tool_calls(messages, "test-team", "test-agent")
        assert path is not None
        # Check permissions (chmod 600)
        stat = Path(path).stat()
        assert stat.st_mode & 0o777 == 0o600


class TestGetSessionUuid:
    def test_finds_with_prefix(self, tmp_path, monkeypatch):
        sessions_file = tmp_path / ".openclaw" / "agents" / "main" / "sessions.json"
        sessions_file.parent.mkdir(parents=True)
        sessions_file.write_text(json.dumps({
            "sessions": [{"key": "clawteam-ring2-impl-coder-a", "id": "abc-123"}]
        }))
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        result = _get_session_uuid("agent:main:clawteam-ring2-impl-coder-a")
        assert result == "abc-123"

    def test_finds_without_prefix(self, tmp_path, monkeypatch):
        sessions_file = tmp_path / ".openclaw" / "agents" / "main" / "sessions.json"
        sessions_file.parent.mkdir(parents=True)
        sessions_file.write_text(json.dumps({
            "sessions": [{"key": "clawteam-ring2-impl-coder-a", "id": "abc-123"}]
        }))
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        result = _get_session_uuid("clawteam-ring2-impl-coder-a")
        assert result == "abc-123"

    def test_returns_none_if_not_found(self, tmp_path, monkeypatch):
        sessions_file = tmp_path / ".openclaw" / "agents" / "main" / "sessions.json"
        sessions_file.parent.mkdir(parents=True)
        sessions_file.write_text(json.dumps({
            "sessions": [{"key": "other-session", "id": "xyz-789"}]
        }))
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        result = _get_session_uuid("agent:main:clawteam-ring2-impl-coder-a")
        assert result is None

    def test_returns_none_if_no_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        result = _get_session_uuid("agent:main:clawteam-ring2-impl-coder-a")
        assert result is None


class TestExtractAndLog:
    def test_returns_error_if_no_transcript(self):
        result = extract_and_log("nonexistent-team", "nonexistent-agent")
        assert result["status"] == "ok"
        assert result["tool_calls"] == 0

    def test_builds_session_key_if_not_provided(self):
        result = extract_and_log("my-team", "my-agent")
        assert result["status"] == "ok"


class TestFindTranscript:
    def test_returns_none_if_no_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        from clawteam.spawn.tool_calls import _find_transcript
        result = _find_transcript("nonexistent-session")
        assert result is None

    def test_finds_via_sessions_json(self, tmp_path, monkeypatch):
        # Create sessions.json with UUID mapping
        sessions_file = tmp_path / ".openclaw" / "agents" / "main" / "sessions.json"
        sessions_file.parent.mkdir(parents=True)
        sessions_file.write_text(json.dumps({
            "sessions": [{"key": "clawteam-test-team-test-agent", "id": "abc-123"}]
        }))
        # Create transcript file
        transcript = tmp_path / ".openclaw" / "agents" / "main" / "sessions" / "abc-123.jsonl"
        transcript.parent.mkdir(parents=True)
        transcript.write_text('{"type": "tool_call", "tool": "read"}\n')
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        from clawteam.spawn.tool_calls import _find_transcript
        result = _find_transcript("agent:main:clawteam-test-team-test-agent")
        assert result is not None
        assert result.exists()


class TestAbnormalTranscript:
    def test_skips_invalid_json_lines(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        messages = [
            {"type": "tool_call", "tool": "read", "input": {}, "timestamp": "2026-03-25T00:00:00Z"},
        ]
        count, path = _write_tool_calls(messages, "test-team", "test-agent")
        assert count == 1


class TestLogRotation:
    def test_rotation_on_large_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        # Create a large log file (>10MB)
        log_dir = tmp_path / ".clawteam" / "logs" / "test-team"
        log_dir.mkdir(parents=True)
        log_file = log_dir / "test-agent-tools.log"
        # Write 11MB of data
        log_file.write_text("x" * (11 * 1024 * 1024))
        # Now write tool calls - should trigger rotation
        messages = [
            {"type": "tool_call", "tool": "read", "input": {}, "timestamp": "2026-03-25T00:00:00Z"},
        ]
        count, path = _write_tool_calls(messages, "test-team", "test-agent")
        assert count == 1
        # Check rotated file exists
        rotated_files = list(log_dir.glob("*.log"))
        assert len(rotated_files) >= 2  # original + rotated
