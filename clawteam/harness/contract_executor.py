"""Contract execution: converts sprint contracts to tasks and manages waves."""

from __future__ import annotations

import json
from typing import Any

from clawteam.harness.contracts import SprintContract
from clawteam.harness.strategies import AssignmentStrategy


class RoundRobinAssigner(AssignmentStrategy):
    """Default: round-robin assignment of contracts to agents."""

    def assign(
        self,
        contracts: list,
        agent_names: list[str],
    ) -> dict[str, list]:
        if not agent_names:
            return {}
        mapping: dict[str, list] = {name: [] for name in agent_names}
        for i, contract in enumerate(contracts):
            agent = agent_names[i % len(agent_names)]
            mapping[agent].append(contract)
        return mapping


class ContractExecutor:
    """Parses sprint contracts from artifacts and creates executable tasks."""

    def __init__(
        self,
        orchestrator: Any,
        assignment: AssignmentStrategy | None = None,
    ):
        self._orch = orchestrator
        self._assignment = assignment or RoundRobinAssigner()

    def load_contracts(self) -> list[SprintContract]:
        """Load contracts from the artifact store."""
        contracts: list[tuple[str, SprintContract]] = []
        artifacts = self._orch.artifacts.list_artifacts()
        for art in artifacts:
            if "sprint-contract" in art["name"] and art["name"].endswith(".json"):
                content = self._orch.artifacts.read(art["name"])
                if content:
                    try:
                        data = json.loads(content)
                        contracts.append((art["name"], SprintContract.model_validate(data)))
                    except Exception:
                        pass
        contracts.sort(key=lambda item: (item[1].wave, item[0], item[1].id))
        return [contract for _, contract in contracts]

    def create_tasks_from_contracts(self, agent_names: list[str] | None = None) -> list:
        """Convert contracts to TaskStore tasks with wave dependencies."""
        from clawteam.team.models import TaskPriority
        from clawteam.team.tasks import TaskStore

        contracts = self.load_contracts()
        store = TaskStore(self._orch.team_name)
        created_tasks = []
        wave_task_ids: dict[int, list[str]] = {}  # wave -> [task_ids]
        assigned_contracts = self._assignment.assign(contracts, agent_names or [])
        contract_assignees: dict[str, list[str]] = {}
        for agent_name, items in assigned_contracts.items():
            for contract in items:
                contract_assignees.setdefault(contract.id, []).append(agent_name)

        for contract in contracts:
            # Determine blocked_by from previous waves
            blocked_by: list[str] = []
            for dep_wave in range(1, contract.wave):
                blocked_by.extend(wave_task_ids.get(dep_wave, []))

            assignees = list(contract.assigned_to or contract_assignees.get(contract.id, []))
            owner = assignees[0] if assignees else ""
            if assignees:
                contract.assigned_to = assignees

            task = store.create(
                subject=contract.title,
                description=contract.description,
                owner=owner,
                priority=TaskPriority.high,
                blocked_by=blocked_by if blocked_by else None,
                metadata={
                    "contract_id": contract.id,
                    "wave": contract.wave,
                    "assigned_to": assignees,
                },
            )

            wave_task_ids.setdefault(contract.wave, []).append(task.id)
            contract.tasks = [task.id]
            created_tasks.append(task)

        return created_tasks

    def assign_to_agents(
        self,
        agent_names: list[str],
    ) -> dict[str, list[SprintContract]]:
        """Assign contracts to agents using the assignment strategy."""
        contracts = self.load_contracts()
        return self._assignment.assign(contracts, agent_names)

    def check_wave_completion(self, wave: int) -> bool:
        """Check if all tasks in a wave are completed."""
        from clawteam.team.models import TaskStatus
        from clawteam.team.tasks import TaskStore

        store = TaskStore(self._orch.team_name)
        tasks = store.list_tasks()
        wave_tasks = [
            t for t in tasks
            if t.metadata.get("wave") == wave
        ]
        return all(t.status == TaskStatus.completed for t in wave_tasks)
