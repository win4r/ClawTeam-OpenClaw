"""Gource visualization integration for ClawTeam.

Generates Gource custom log format from ClawTeam events and git history,
and launches Gource visualizations of team activity.

Gource custom log format: timestamp|username|type|path
  - timestamp: unix timestamp
  - username: agent name
  - type: A (add), M (modify), D (delete)
  - path: virtual file path representing the event
"""

from __future__ import annotations

import shutil
import subprocess
import time
from datetime import datetime, timezone
from io import TextIOBase
from pathlib import Path

from clawteam.board.collector import BoardCollector

# ---------------------------------------------------------------------------
# Color mapping for agents
# ---------------------------------------------------------------------------

# Gource user colors (hex without #)
AGENT_COLORS = [
    "00FF00",  # green
    "FF6600",  # orange
    "00CCFF",  # cyan
    "FF00FF",  # magenta
    "FFFF00",  # yellow
    "FF3333",  # red
    "66FF66",  # light green
    "9966FF",  # purple
    "FF9999",  # pink
    "33FFCC",  # teal
]


def _agent_color(index: int) -> str:
    return AGENT_COLORS[index % len(AGENT_COLORS)]


def _virtual_path(*parts: str) -> str:
    components: list[str] = []
    for part in parts:
        if not part:
            continue
        for component in str(part).replace("\\", "/").split("/"):
            if not component or component == ".":
                continue
            if components and components[-1] == component:
                continue
            components.append(component)
    return "/" + "/".join(components)


# ---------------------------------------------------------------------------
# ClawTeam event log → Gource custom log
# ---------------------------------------------------------------------------


def _parse_iso(ts: str) -> int:
    """Parse ISO timestamp string to unix timestamp."""
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return int(dt.timestamp())
    except Exception:
        return int(datetime.now(timezone.utc).timestamp())


def generate_event_log(team_name: str) -> list[str]:
    """Generate Gource custom log lines from ClawTeam events.

    Maps ClawTeam events to virtual paths:
      - Task status changes → /tasks/{status}/{task_subject}
      - Messages → /messages/{from_agent}/{to}
      - Member joins → /team/{agent_name}

    Returns sorted list of 'timestamp|username|type|path' strings.
    """
    collector = BoardCollector()
    try:
        data = collector.collect_team(team_name)
    except ValueError:
        return []

    lines: list[str] = []
    inbox_aliases: dict[str, str] = {}

    # Member joins as additions
    for member in data.get("members", []):
        name = member["name"]
        inbox_aliases[name] = name
        user = member.get("user", "")
        if user:
            inbox_aliases[f"{user}_{name}"] = name
        joined = member.get("joinedAt", "")
        if joined:
            ts = _parse_iso(joined)
            lines.append(f"{ts}|{name}|A|{_virtual_path('team', name)}")

    # Tasks as file operations
    for status, tasks in data.get("tasks", {}).items():
        for task in tasks:
            owner = task.get("owner", "system")
            subject = task.get("subject", "untitled").replace("/", "_")
            task_id = task.get("id", "unknown")
            updated = task.get("updatedAt", task.get("createdAt", ""))
            created = task.get("createdAt", "")

            if created:
                ts = _parse_iso(created)
                creator = owner or "system"
                lines.append(f"{ts}|{creator}|A|{_virtual_path('tasks', 'pending', f'{task_id}_{subject}')}")

            if updated and status != "pending":
                ts = _parse_iso(updated)
                gource_type = "M" if status in ("in_progress", "blocked") else "A"
                agent = owner or "system"
                lines.append(
                    f"{ts}|{agent}|{gource_type}|{_virtual_path('tasks', status, f'{task_id}_{subject}')}"
                )

    # Messages as modifications
    for msg in data.get("messages", []):
        raw_from = msg.get("from") or msg.get("fromAgent") or "unknown"
        from_agent = inbox_aliases.get(raw_from, raw_from)
        raw_to = msg.get("to") or "broadcast"
        to = inbox_aliases.get(raw_to, raw_to)
        ts_str = msg.get("timestamp", "")
        msg_type = msg.get("type", "message")
        if ts_str:
            ts = _parse_iso(ts_str)
            lines.append(f"{ts}|{from_agent}|M|{_virtual_path('messages', from_agent, to, msg_type)}")

    # Sort by timestamp
    lines.sort(key=lambda line: int(line.split("|")[0]))
    return lines


# ---------------------------------------------------------------------------
# Git log → Gource log (via context layer)
# ---------------------------------------------------------------------------


def generate_git_log(team_name: str, repo_path: str | None = None) -> list[str]:
    """Combine git logs from all agent branches into unified Gource log.

    Uses the context layer's cross_branch_log() and file_owners() instead
    of reading git logs directly, making Gource a view on top of context.

    Each agent's file paths are prefixed with their agent name to show
    parallel work in different areas of the visualization tree.
    """
    try:
        from clawteam.workspace.context import cross_branch_log, file_owners
    except ImportError:
        return []

    try:
        entries = cross_branch_log(team_name, limit=500, repo=repo_path)
    except Exception:
        return []

    lines: list[str] = []
    for entry in entries:
        agent = entry.get("agent", "unknown")
        ts_str = entry.get("timestamp", "")
        ts = _parse_iso(ts_str)
        for fpath in entry.get("files", []):
            # Classify as M (modify) by default; context layer doesn't
            # distinguish A/M/D per-file, so use "M" for all.
            lines.append(f"{ts}|{agent}|M|{_virtual_path(agent, fpath)}")

    # Enrich with file-owner coloring: mark multi-owner files
    try:
        owners = file_owners(team_name, repo=repo_path)
        now_ts = int(datetime.now(timezone.utc).timestamp())
        for fname, agents in owners.items():
            if len(agents) > 1:
                # Add a synthetic entry so Gource shows shared files
                for agent in agents:
                    lines.append(f"{now_ts}|{agent}|M|{_virtual_path('shared', fname)}")
    except Exception:
        pass

    # Sort by timestamp
    lines.sort(key=lambda line: int(line.split("|")[0]))
    return lines


def generate_combined_log(team_name: str, repo_path: str | None = None) -> list[str]:
    """Combine both ClawTeam event log and git history into one Gource log."""
    events = generate_event_log(team_name)
    git_lines = generate_git_log(team_name, repo_path)
    combined = events + git_lines
    combined.sort(key=lambda line: int(line.split("|")[0]))
    return combined


def collect_live_log_lines(
    seen_lines: set[str],
    team_name: str,
    *,
    combine_worktrees: bool = True,
    repo_path: str | None = None,
) -> list[str]:
    """Return newly observed log lines for live streaming.

    This is intentionally side-effect free with respect to ClawTeam state.
    It only polls current event/git views and de-duplicates against a local
    in-memory cursor owned by the `board gource --live` command.
    """
    all_lines = (
        generate_combined_log(team_name, repo_path)
        if combine_worktrees
        else generate_event_log(team_name)
    )
    new_lines = [line for line in all_lines if line not in seen_lines]
    new_lines.sort(key=lambda line: int(line.split("|")[0]))
    return new_lines


def append_log_lines(stream: TextIOBase, lines: list[str]) -> None:
    """Append custom-log lines to a live Gource input stream."""
    if not lines:
        return
    stream.write("\n".join(lines) + "\n")
    stream.flush()


def stream_gource_live(
    proc: subprocess.Popen,
    team_name: str,
    *,
    combine_worktrees: bool = True,
    repo_path: str | None = None,
    poll_interval: float = 2.0,
) -> None:
    """Feed Gource custom log lines to a running process via STDIN."""
    if proc.stdin is None:
        raise RuntimeError("Live gource process missing stdin pipe")

    seen_lines: set[str] = set()
    while proc.poll() is None:
        new_lines = collect_live_log_lines(
            seen_lines,
            team_name,
            combine_worktrees=combine_worktrees,
            repo_path=repo_path,
        )
        if new_lines:
            append_log_lines(proc.stdin, new_lines)
            seen_lines.update(new_lines)
        time.sleep(poll_interval)


# ---------------------------------------------------------------------------
# Gource user color config generation
# ---------------------------------------------------------------------------


def generate_user_colors(team_name: str) -> str:
    """Generate Gource --user-image-dir compatible color config.

    Returns content for a user colors file mapping agent names to colors.
    Format: username=color (one per line).
    """
    collector = BoardCollector()
    try:
        data = collector.collect_team(team_name)
    except ValueError:
        return ""

    lines: list[str] = []
    for i, member in enumerate(data.get("members", [])):
        name = member["name"]
        color = _agent_color(i)
        lines.append(f"{name}={color}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Launch Gource
# ---------------------------------------------------------------------------


def find_gource() -> str | None:
    """Find gource binary. Returns path or None."""
    from clawteam.config import load_config

    cfg = load_config()
    custom_path = getattr(cfg, "gource_path", "")
    if custom_path and Path(custom_path).is_file():
        return custom_path
    return shutil.which("gource")


def launch_gource(
    log_file: Path | None = None,
    title: str = "",
    resolution: str = "",
    seconds_per_day: float = 0,
    extra_args: list[str] | None = None,
    export_path: str | None = None,
    live_stream: bool = False,
) -> subprocess.Popen | None:
    """Launch Gource with the given custom log file.

    If export_path is provided, pipes through FFmpeg to produce an MP4.
    Returns the Popen object, or None if gource is not found.
    """
    gource_bin = find_gource()
    if not gource_bin:
        return None

    # Load config defaults
    from clawteam.config import load_config

    cfg = load_config()
    if not resolution:
        resolution = getattr(cfg, "gource_resolution", "1280x720")
    if not seconds_per_day:
        seconds_per_day = getattr(cfg, "gource_seconds_per_day", 0.5)

    cmd = [
        gource_bin,
        "-" if live_stream else str(log_file),
        "--log-format",
        "custom",
        "--seconds-per-day",
        str(seconds_per_day),
        "--auto-skip-seconds",
        "0.5",
        "--file-idle-time",
        "0",
        "--max-files",
        "0",
        "--highlight-users",
        "--multi-sampling",
    ]
    if live_stream:
        cmd.append("--realtime")

    if resolution:
        parts = resolution.split("x")
        if len(parts) == 2:
            cmd.extend(["--viewport", f"{parts[0]}x{parts[1]}"])

    if title:
        cmd.extend(["--title", title])

    if extra_args:
        cmd.extend(extra_args)

    if export_path:
        # Pipe PPM stream to FFmpeg for video export
        ffmpeg_bin = shutil.which("ffmpeg")
        if not ffmpeg_bin:
            return None

        cmd.extend(["--output-ppm-stream", "-"])

        gource_proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
        )

        ffmpeg_cmd = [
            ffmpeg_bin,
            "-y",  # overwrite
            "-r",
            "60",
            "-f",
            "image2pipe",
            "-vcodec",
            "ppm",
            "-i",
            "-",
            "-vcodec",
            "libx264",
            "-preset",
            "medium",
            "-pix_fmt",
            "yuv420p",
            "-crf",
            "18",
            export_path,
        ]

        ffmpeg_proc = subprocess.Popen(
            ffmpeg_cmd,
            stdin=gource_proc.stdout,
        )
        # Allow gource_proc to receive SIGPIPE if ffmpeg exits
        if gource_proc.stdout:
            gource_proc.stdout.close()
        return ffmpeg_proc
    else:
        popen_kwargs: dict[str, object] = {}
        if live_stream:
            popen_kwargs.update({"stdin": subprocess.PIPE, "text": True})
        return subprocess.Popen(cmd, **popen_kwargs)
