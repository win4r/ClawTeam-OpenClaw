"""Cost tracking for multi-agent teams."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from clawteam.team.models import get_data_dir


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class CostEvent(BaseModel):
    """A single cost event reported by an agent."""

    model_config = {"populate_by_name": True}

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    agent_name: str = Field(alias="agentName")
    provider: str = ""
    model: str = ""
    input_tokens: int = Field(default=0, alias="inputTokens")
    output_tokens: int = Field(default=0, alias="outputTokens")
    cost_cents: float = Field(default=0.0, alias="costCents")
    reported_at: str = Field(default_factory=_now_iso, alias="reportedAt")


class CostSummary(BaseModel):
    """Aggregated cost summary for a team."""

    model_config = {"populate_by_name": True}

    team_name: str = Field(alias="teamName")
    total_cost_cents: float = Field(default=0.0, alias="totalCostCents")
    total_input_tokens: int = Field(default=0, alias="totalInputTokens")
    total_output_tokens: int = Field(default=0, alias="totalOutputTokens")
    by_agent: dict[str, float] = Field(default_factory=dict, alias="byAgent")
    event_count: int = Field(default=0, alias="eventCount")


def _costs_root(team_name: str) -> Path:
    d = get_data_dir() / "costs" / team_name
    d.mkdir(parents=True, exist_ok=True)
    return d


class CostStore:
    """File-based cost event store.

    Each event is stored as a separate JSON file:
    ``{data_dir}/costs/{team}/cost-{timestamp}-{id}.json``
    """

    def __init__(self, team_name: str):
        self.team_name = team_name

    def report(
        self,
        agent_name: str,
        provider: str = "",
        model: str = "",
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_cents: float = 0.0,
    ) -> CostEvent:
        event = CostEvent(
            agent_name=agent_name,
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_cents=cost_cents,
        )
        ts = event.reported_at.replace(":", "-").replace("+", "p")
        filename = f"cost-{ts}-{event.id}.json"
        path = _costs_root(self.team_name) / filename
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            event.model_dump_json(indent=2, by_alias=True), encoding="utf-8"
        )
        tmp.replace(path)
        return event

    def list_events(self, agent_name: str = "") -> list[CostEvent]:
        root = _costs_root(self.team_name)
        events = []
        for f in sorted(root.glob("cost-*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                event = CostEvent.model_validate(data)
                if agent_name and event.agent_name != agent_name:
                    continue
                events.append(event)
            except Exception:
                continue
        return events

    def summary(self) -> CostSummary:
        events = self.list_events()
        total_cents = 0.0
        total_in = 0
        total_out = 0
        by_agent: dict[str, float] = {}
        for e in events:
            total_cents += e.cost_cents
            total_in += e.input_tokens
            total_out += e.output_tokens
            by_agent[e.agent_name] = by_agent.get(e.agent_name, 0.0) + e.cost_cents
        return CostSummary(
            team_name=self.team_name,
            total_cost_cents=total_cents,
            total_input_tokens=total_in,
            total_output_tokens=total_out,
            by_agent=by_agent,
            event_count=len(events),
        )
