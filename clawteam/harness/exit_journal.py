"""Cross-process exit notification via JSONL journal."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from clawteam.harness.strategies import ExitNotifier
from clawteam.team.models import get_data_dir


class FileExitJournal(ExitNotifier):
    """JSONL append-only journal for cross-process exit notification.

    Written by: `clawteam lifecycle on-exit` (in the exiting agent's process)
    Read by: HarnessConductor (in the conductor's process)
    """

    def __init__(self, team_name: str, harness_id: str = ""):
        if harness_id:
            self._path = get_data_dir() / "harness" / team_name / harness_id / "exit-journal.jsonl"
        else:
            self._path = get_data_dir() / "harness" / team_name / "exit-journal.jsonl"
        self._read_offset = 0

    def record_exit(
        self,
        agent_name: str,
        exit_code: int | None = None,
        abandoned_tasks: list[str] | None = None,
    ) -> None:
        """Append an exit record. Called from the exiting process."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "agent_name": agent_name,
            "exit_code": exit_code,
            "abandoned_tasks": abandoned_tasks or [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        # Append atomically (one write call, newline-terminated)
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def read_new(self) -> list[dict]:
        """Read entries added since the last call. Called from conductor."""
        if not self._path.is_file():
            return []
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                f.seek(self._read_offset)
                new_lines = f.readlines()
                self._read_offset = f.tell()
        except Exception:
            return []

        entries = []
        for line in new_lines:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return entries

    def clear(self) -> None:
        """Clear the journal (for testing or cleanup)."""
        if self._path.is_file():
            os.unlink(self._path)
        self._read_offset = 0
