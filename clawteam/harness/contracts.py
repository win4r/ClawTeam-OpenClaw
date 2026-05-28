"""Sprint contracts for harness execution."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SuccessCriterion(BaseModel):
    """A single testable success criterion."""

    description: str = ""
    test_command: str = ""  # optional automated verification command
    verified: bool = False
    verified_by: str = ""
    verified_at: str = ""


class SprintContract(BaseModel):
    """A sprint contract defining a unit of work with testable criteria."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    title: str = ""
    description: str = ""
    tasks: list[str] = Field(default_factory=list)  # TaskStore task IDs
    success_criteria: list[SuccessCriterion] = Field(default_factory=list)
    assigned_to: list[str] = Field(default_factory=list)  # agent names
    wave: int = 1  # for wave-based parallel execution
    depends_on: list[str] = Field(default_factory=list)  # other contract IDs
    status: str = "pending"  # pending | in_progress | completed | failed
    created_at: str = Field(default_factory=_now_iso)
    completed_at: str = ""
