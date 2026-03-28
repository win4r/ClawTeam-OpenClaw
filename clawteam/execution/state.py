"""Lightweight helpers for task execution lifecycle metadata."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Literal, TypedDict, cast


ExecutionLifecycleState = Literal[
    "awaiting_release",
    "awaiting_claim",
    "claim_failed",
    "claimed",
    "awaiting_writeback",
    "writeback_failed",
    "writeback_applied",
]

AWAITING_RELEASE: ExecutionLifecycleState = "awaiting_release"
AWAITING_CLAIM: ExecutionLifecycleState = "awaiting_claim"
CLAIM_FAILED: ExecutionLifecycleState = "claim_failed"
CLAIMED: ExecutionLifecycleState = "claimed"
AWAITING_WRITEBACK: ExecutionLifecycleState = "awaiting_writeback"
WRITEBACK_FAILED: ExecutionLifecycleState = "writeback_failed"
WRITEBACK_APPLIED: ExecutionLifecycleState = "writeback_applied"
VALID_EXECUTION_STATES = frozenset({
    AWAITING_RELEASE,
    AWAITING_CLAIM,
    CLAIM_FAILED,
    CLAIMED,
    AWAITING_WRITEBACK,
    WRITEBACK_FAILED,
    WRITEBACK_APPLIED,
})

_BOOL_FIELDS = frozenset({"claim_observed", "respawn_attempted", "respawn_succeeded", "message_sent", "replacement_required"})
_STR_FIELDS = frozenset({"updated_at", "released_at", "claimed_at", "runtime_state_before", "message_id", "replacement_reason", "last_error"})


class ExecutionMetadata(TypedDict, total=False):
    state: ExecutionLifecycleState
    updated_at: str
    released_at: str
    claimed_at: str
    claim_observed: bool
    runtime_state_before: str
    respawn_attempted: bool
    respawn_succeeded: bool
    message_sent: bool
    message_id: str
    replacement_required: bool
    replacement_reason: str
    last_error: str



def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()



def _normalize_execution_dict(raw: Any) -> ExecutionMetadata:
    if not isinstance(raw, dict):
        return ExecutionMetadata()
    normalized = cast(ExecutionMetadata, deepcopy(raw))
    state = normalized.get("state")
    if state not in VALID_EXECUTION_STATES:
        normalized.pop("state", None)
    for key in list(normalized.keys()):
        value = normalized[key]
        if value is None:
            normalized.pop(key, None)
            continue
        if key in _BOOL_FIELDS:
            normalized[key] = bool(value)
        elif key in _STR_FIELDS:
            normalized[key] = str(value)
    return normalized



def get_execution_metadata(task_or_metadata: Any) -> ExecutionMetadata:
    metadata = getattr(task_or_metadata, "metadata", task_or_metadata)
    if not isinstance(metadata, dict):
        return ExecutionMetadata()
    return _normalize_execution_dict(metadata.get("execution"))



def build_execution_metadata(*, state: ExecutionLifecycleState, now: str | None = None, **fields: Any) -> ExecutionMetadata:
    payload: ExecutionMetadata = ExecutionMetadata(state=state, updated_at=now or _now_iso(), **fields)
    return _normalize_execution_dict(payload)



def merge_execution_metadata(task_or_metadata: Any, *, state: ExecutionLifecycleState, now: str | None = None, clear_error: bool = True, **fields: Any) -> dict[str, Any]:
    execution = get_execution_metadata(task_or_metadata)
    execution.update(build_execution_metadata(state=state, now=now, **fields))
    if clear_error and state != CLAIM_FAILED:
        execution.pop("last_error", None)
    return {"execution": execution}
