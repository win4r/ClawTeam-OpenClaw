"""Agent roles for harness orchestration."""

from __future__ import annotations

from pydantic import BaseModel, Field

# AgentRole is an open str — not an Enum. Plugins can define custom roles.
AgentRole = str

PLANNER: AgentRole = "planner"
EXECUTOR: AgentRole = "executor"
EVALUATOR: AgentRole = "evaluator"
LEADER: AgentRole = "leader"


class RoleConfig(BaseModel):
    """Role-specific configuration for harness agents."""

    role: str = EXECUTOR
    system_prompt_addon: str = ""
    phase_affinity: list[str] = Field(default_factory=list)


DEFAULT_ROLES: dict[str, RoleConfig] = {
    PLANNER: RoleConfig(
        role=PLANNER,
        phase_affinity=["discuss", "plan"],
        system_prompt_addon=(
            "You are the planner. Your job is to analyze the user's goal, "
            "ask clarifying questions, and produce a structured specification "
            "with sprint contracts containing testable success criteria."
        ),
    ),
    EXECUTOR: RoleConfig(
        role=EXECUTOR,
        phase_affinity=["execute"],
        system_prompt_addon=(
            "You are an executor. Focus on implementing your assigned sprint contract "
            "in your isolated workspace. Commit frequently and update task status."
        ),
    ),
    EVALUATOR: RoleConfig(
        role=EVALUATOR,
        phase_affinity=["verify"],
        system_prompt_addon=(
            "You are the evaluator. Test the implementation against the sprint contract's "
            "success criteria. Be thorough and specific in your findings. Report each "
            "criterion as passed or failed with evidence."
        ),
    ),
}
