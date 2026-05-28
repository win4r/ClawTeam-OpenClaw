"""Artifact storage for structured handoff between harness phases."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ArtifactStore:
    """File-based artifact storage for harness phases."""

    def __init__(self, base_dir: Path, team_name: str, harness_id: str) -> None:
        self._dir = base_dir / team_name / harness_id / "artifacts"
        self._dir.mkdir(parents=True, exist_ok=True)

    def write(self, name: str, content: str, metadata: dict[str, Any] | None = None) -> Path:
        """Write an artifact file. Returns the file path."""
        path = self._dir / name
        path.write_text(content, encoding="utf-8")
        if metadata:
            meta_path = self._dir / f"{name}.meta.json"
            meta_path.write_text(
                json.dumps({**metadata, "written_at": _now_iso()}, indent=2),
                encoding="utf-8",
            )
        return path

    def read(self, name: str) -> str | None:
        """Read an artifact file. Returns None if not found."""
        path = self._dir / name
        if path.is_file():
            return path.read_text(encoding="utf-8")
        return None

    def exists(self, name: str) -> bool:
        return (self._dir / name).is_file()

    def list_artifacts(self) -> list[dict[str, Any]]:
        """List all artifacts with metadata."""
        result = []
        for path in sorted(self._dir.iterdir()):
            if path.name.endswith(".meta.json"):
                continue
            entry: dict[str, Any] = {
                "name": path.name,
                "size": path.stat().st_size,
            }
            meta_path = self._dir / f"{path.name}.meta.json"
            if meta_path.is_file():
                try:
                    entry["metadata"] = json.loads(meta_path.read_text(encoding="utf-8"))
                except Exception:
                    pass
            result.append(entry)
        return result

    # ── Convenience methods for common artifact types ──

    def write_spec(self, content: str) -> Path:
        """Write the plan specification."""
        return self.write("spec.md", content, {"type": "specification", "phase": "plan"})

    def write_sprint_contract(self, contract_id: str, content: str) -> Path:
        """Write a sprint contract."""
        return self.write(
            f"sprint-contract-{contract_id}.json",
            content,
            {"type": "sprint_contract", "phase": "plan"},
        )

    def write_evaluation(self, content: str) -> Path:
        """Write evaluation results."""
        return self.write("eval-report.json", content, {"type": "evaluation", "phase": "verify"})

    def write_ship_manifest(self, content: str) -> Path:
        """Write the ship manifest."""
        return self.write("ship-manifest.json", content, {"type": "manifest", "phase": "ship"})
