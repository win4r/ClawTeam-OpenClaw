"""Harness system: plan-then-execute agent orchestration."""

from clawteam.harness.contracts import SprintContract, SuccessCriterion
from clawteam.harness.phases import (
    DISCUSS,
    EXECUTE,
    PLAN,
    SHIP,
    VERIFY,
    AllTasksCompleteGate,
    ArtifactRequiredGate,
    HumanApprovalGate,
    PhaseGate,
    PhaseRunner,
    PhaseState,
)
from clawteam.harness.roles import EVALUATOR, EXECUTOR, LEADER, PLANNER, RoleConfig
from clawteam.harness.strategies import (
    AssignmentStrategy,
    ExitNotifier,
    HealthStrategy,
    RespawnStrategy,
    SpawnStrategy,
)

__all__ = [
    "DISCUSS", "PLAN", "EXECUTE", "VERIFY", "SHIP",
    "PhaseState", "PhaseRunner", "PhaseGate",
    "ArtifactRequiredGate", "AllTasksCompleteGate", "HumanApprovalGate",
    "SprintContract", "SuccessCriterion",
    "PLANNER", "EXECUTOR", "EVALUATOR", "LEADER", "RoleConfig",
    "SpawnStrategy", "RespawnStrategy", "HealthStrategy",
    "ExitNotifier", "AssignmentStrategy",
]
