"""Model resolution for per-agent model assignment.

Implements a 7-level priority chain:
1. CLI --model flag
2. Agent-level model (from template TOML)
3. Agent-level model_tier mapped via tier table
4. Template model_strategy auto-assignment by role
5. Template-level default model
6. Config default_model
7. None (let backend use its own default)
"""

from __future__ import annotations

DEFAULT_TIERS: dict[str, str] = {
    "strong": "opus",
    "balanced": "sonnet-4.6",
    "cheap": "haiku-4.5",
}

AUTO_ROLE_MAP: dict[str, str] = {
    "leader": "strong",
    "reviewer": "strong",
    "architect": "strong",
    "manager": "strong",
}


def resolve_model(
    cli_model: str | None,
    agent_model: str | None,
    agent_model_tier: str | None,
    template_model_strategy: str | None,
    template_model: str | None,
    config_default_model: str,
    agent_type: str,
    tier_overrides: dict[str, str] | None = None,
) -> str | None:
    """Resolve the effective model for an agent. Returns None if no model specified."""
    tiers = {**DEFAULT_TIERS, **(tier_overrides or {})}

    # 1. CLI override
    if cli_model:
        return cli_model

    # 2. Explicit agent model
    if agent_model:
        return agent_model

    # 3. Agent model tier (validated at parse time, guard kept for safety)
    if agent_model_tier and agent_model_tier in tiers:
        return tiers[agent_model_tier]

    # 4. Auto strategy
    if template_model_strategy == "auto":
        for keyword, tier in AUTO_ROLE_MAP.items():
            if keyword in agent_type.lower():
                return tiers[tier]
        return tiers["balanced"]

    # 5. Template default
    if template_model:
        return template_model

    # 6. Config default
    if config_default_model:
        return config_default_model

    # 7. No model — let backend use its own default
    return None
