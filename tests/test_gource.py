from __future__ import annotations

from clawteam.board.gource import (
    append_log_lines,
    collect_live_log_lines,
    generate_event_log,
    generate_git_log,
    launch_gource,
)


def test_collect_live_log_lines_returns_only_unseen(monkeypatch):
    monkeypatch.setattr(
        "clawteam.board.gource.generate_combined_log",
        lambda team, repo=None: [
            "1|alice|A|/tasks/1",
            "2|bob|M|/tasks/2",
        ],
    )

    seen = {"1|alice|A|/tasks/1"}
    assert collect_live_log_lines(seen, "demo") == ["2|bob|M|/tasks/2"]


def test_append_log_lines_writes_and_flushes():
    class DummyStream:
        def __init__(self):
            self.data = ""
            self.flushed = False

        def write(self, text):
            self.data += text

        def flush(self):
            self.flushed = True

    stream = DummyStream()
    append_log_lines(stream, ["1|alice|A|/a", "2|bob|M|/b"])

    assert stream.data == "1|alice|A|/a\n2|bob|M|/b\n"
    assert stream.flushed is True


def test_launch_gource_live_stream_uses_stdin(monkeypatch):
    captured: dict[str, object] = {}

    class DummyProcess:
        def __init__(self):
            self.stdin = object()

    monkeypatch.setattr("clawteam.board.gource.find_gource", lambda: "/usr/bin/gource")

    def fake_popen(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return DummyProcess()

    monkeypatch.setattr("clawteam.board.gource.subprocess.Popen", fake_popen)

    proc = launch_gource(
        log_file=None,
        title="Demo",
        live_stream=True,
    )

    assert proc is not None
    assert captured["cmd"][1] == "-"
    assert "--realtime" in captured["cmd"]
    assert captured["kwargs"]["stdin"] is not None
    assert captured["kwargs"]["text"] is True


def test_generate_event_log_uses_message_sender_and_member_aliases(monkeypatch):
    monkeypatch.setattr(
        "clawteam.board.gource.BoardCollector.collect_team",
        lambda self, team: {
            "members": [
                {"name": "leader", "user": "alice", "joinedAt": "2026-03-20T08:40:03+00:00"},
                {"name": "backend", "joinedAt": "2026-03-20T08:40:40+00:00"},
            ],
            "tasks": {"pending": [], "in_progress": [], "completed": [], "blocked": []},
            "messages": [
                {
                    "from": "alice_leader",
                    "to": "backend",
                    "type": "message",
                    "timestamp": "2026-03-20T08:41:23+00:00",
                }
            ],
        },
    )

    lines = generate_event_log("demo")

    assert any("|leader|M|/messages/leader/backend/message" in line for line in lines)
    assert all("/messages/unknown/" not in line for line in lines)


def test_generate_git_log_normalizes_duplicate_path_segments(monkeypatch):
    monkeypatch.setattr(
        "clawteam.workspace.context.cross_branch_log",
        lambda team, limit=500, repo=None: [
            {
                "agent": "backend",
                "timestamp": "2026-03-20T08:41:22+00:00",
                "files": ["backend/app.py", "shared/api-contract.md"],
            }
        ],
    )
    monkeypatch.setattr(
        "clawteam.workspace.context.file_owners",
        lambda team, repo=None: {"shared/api-contract.md": ["frontend", "backend"]},
    )

    lines = generate_git_log("demo")

    assert any("|backend|M|/backend/app.py" in line for line in lines)
    assert any("|backend|M|/shared/api-contract.md" in line for line in lines)
    assert all("/backend/backend/" not in line for line in lines)
    assert all("/shared/shared/" not in line for line in lines)
