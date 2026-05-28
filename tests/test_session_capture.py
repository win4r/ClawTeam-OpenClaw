from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from clawteam.spawn.session_capture import (
    build_resume_command,
    discover_codex_session,
    persist_spawned_session,
    prepare_session_capture,
    save_current_agent_session,
)
from clawteam.spawn.session_locators import SessionContext, locator_for_client
from clawteam.spawn.sessions import SessionStore


def test_prepare_session_capture_generates_claude_session_id(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / ".clawteam"))

    capture = prepare_session_capture(
        ["claude"],
        team_name="demo",
        agent_name="leader",
        cwd=str(tmp_path),
    )

    assert capture.client == "claude"
    assert capture.session_id
    assert capture.command == ["claude", "--session-id", capture.session_id]

    saved = persist_spawned_session(capture, command=capture.command)
    session = SessionStore("demo").load("leader")

    assert saved == capture.session_id
    assert session is not None
    assert session.session_id == capture.session_id
    assert session.state["client"] == "claude"
    assert session.state["confidence"] == "exact"


def test_prepare_session_capture_keeps_existing_claude_session_id():
    capture = prepare_session_capture(
        ["claude", "--session-id", "11111111-1111-4111-8111-111111111111"],
        team_name="demo",
        agent_name="worker",
    )

    assert capture.session_id == "11111111-1111-4111-8111-111111111111"
    assert capture.source == "provided"
    assert capture.command == ["claude", "--session-id", "11111111-1111-4111-8111-111111111111"]


def test_build_resume_command_supports_codex_and_claude():
    assert build_resume_command(["claude"], "sess-1") == ["claude", "--resume", "sess-1"]
    assert build_resume_command(["codex"], "sess-2") == ["codex", "resume", "sess-2"]
    assert build_resume_command(["run"], "sess-3", client="codex") == ["codex", "resume", "sess-3"]


def test_save_current_agent_session_uses_codex_thread_id(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / ".clawteam"))
    monkeypatch.setenv("CODEX_THREAD_ID", "019dd264-7ba2-7be2-8493-329b1c5ef1f3")

    saved = save_current_agent_session("demo", "leader", cwd=str(tmp_path))
    session = SessionStore("demo").load("leader")

    assert saved == "019dd264-7ba2-7be2-8493-329b1c5ef1f3"
    assert session is not None
    assert session.session_id == saved
    assert session.state["client"] == "codex"


def test_discover_codex_session_matches_recent_agent_prompt(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    cwd = tmp_path / "repo"
    cwd.mkdir()
    session_id = "019dd264-7ba2-7be2-8493-329b1c5ef1f3"
    session_dir = tmp_path / ".codex" / "sessions" / "2026" / "04" / "28"
    session_dir.mkdir(parents=True)
    session_file = session_dir / f"rollout-2026-04-28T12-41-33-{session_id}.jsonl"
    now = time.time()
    session_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "session_meta",
                        "payload": {
                            "id": session_id,
                            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                            "cwd": str(cwd),
                        },
                    }
                ),
                json.dumps({"type": "user_message", "text": "team demo agent worker1"}),
            ]
        ),
        encoding="utf-8",
    )
    Path(session_file).touch()

    found = discover_codex_session(
        team_name="demo",
        agent_name="worker1",
        cwd=str(cwd),
        since=now - 30,
        timeout_seconds=0,
    )

    assert found == session_id


def test_spawned_codex_capture_ignores_parent_thread_id(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CLAWTEAM_DATA_DIR", str(tmp_path / ".clawteam"))
    monkeypatch.setenv("CODEX_THREAD_ID", "parent-session")
    cwd = tmp_path / "repo"
    cwd.mkdir()
    child_session_id = "019dd264-7ba2-7be2-8493-329b1c5ef1f3"
    session_dir = tmp_path / ".codex" / "sessions" / "2026" / "04" / "28"
    session_dir.mkdir(parents=True)
    session_file = session_dir / f"rollout-2026-04-28T12-41-33-{child_session_id}.jsonl"
    now = time.time()
    session_file.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "session_meta",
                        "payload": {
                            "id": child_session_id,
                            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                            "cwd": str(cwd),
                        },
                    }
                ),
                json.dumps({"type": "user_message", "text": "demo worker1"}),
            ]
        ),
        encoding="utf-8",
    )

    capture = prepare_session_capture(
        ["codex"],
        team_name="demo",
        agent_name="worker1",
        cwd=str(cwd),
        prompt="work for demo worker1",
    )
    capture.async_capture = False
    capture.started_at = now - 30
    saved = persist_spawned_session(capture, team_name="demo", agent_name="worker1")
    session = SessionStore("demo").load("worker1")

    assert saved == child_session_id
    assert session is not None
    assert session.session_id == child_session_id


def test_gemini_locator_reads_workspace_chat_session(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    cwd = tmp_path / "repo"
    cwd.mkdir()
    project_dir = tmp_path / ".gemini" / "tmp" / "project-a"
    chats_dir = project_dir / "chats"
    chats_dir.mkdir(parents=True)
    (project_dir / ".project_root").write_text(str(cwd), encoding="utf-8")
    (chats_dir / "session.json").write_text(
        json.dumps(
            {
                "sessionId": "gemini-session-1",
                "lastUpdated": datetime.now(timezone.utc).isoformat(),
                "messages": [],
            }
        ),
        encoding="utf-8",
    )

    captured = locator_for_client("gemini").current_session(  # type: ignore[union-attr]
        SessionContext(
            team_name="demo",
            agent_name="gem",
            cwd=str(cwd),
            allow_environment=False,
        )
    )

    assert captured is not None
    assert captured.session_id == "gemini-session-1"


def test_opencode_locator_uses_session_list(monkeypatch, tmp_path):
    cwd = tmp_path / "repo"
    cwd.mkdir()

    monkeypatch.setattr("clawteam.spawn.session_locators.opencode.shutil.which", lambda name: "/usr/bin/opencode")

    class Result:
        returncode = 0
        stdout = json.dumps(
            [
                {"id": "other", "directory": str(tmp_path / "other"), "updated": 3},
                {"id": "opencode-session-1", "directory": str(cwd), "updated": 5},
            ]
        )

    monkeypatch.setattr(
        "clawteam.spawn.session_locators.opencode.subprocess.run",
        lambda *_, **__: Result(),
    )

    captured = locator_for_client("opencode").current_session(  # type: ignore[union-attr]
        SessionContext(
            team_name="demo",
            agent_name="open",
            cwd=str(cwd),
            allow_environment=False,
        )
    )

    assert captured is not None
    assert captured.session_id == "opencode-session-1"
