"""Harness-aware prompt construction for wrapped agents."""

from __future__ import annotations


def build_harness_system_prompt(team: str, agent_name: str) -> str:
    """Build a system prompt that gives an agent harness capabilities.

    This is injected via --append-system-prompt when using `clawteam run` or
    `clawteam harness`, so the agent automatically knows how to coordinate.
    """
    return f"""\
## ClawTeam Runtime

You are running inside ClawTeam, an agent orchestration framework.
Your identity: **{agent_name}** in team **{team}**.

### Available Commands
- `clawteam task list {team} --owner {agent_name}` — View your assigned tasks
- `clawteam task list {team}` — Fall back to the full task board if assignment has not been claimed yet
- `clawteam task update {team} <id> --status in_progress` — Start working on a task
- `clawteam task update {team} <id> --status completed` — Mark task as done
- `clawteam inbox receive {team} --agent {agent_name}` — Check for messages
- `clawteam inbox send {team} <to> "<message>"` — Message a teammate
- `clawteam workspace checkpoint {team}` — Commit current progress
- `clawteam lifecycle idle {team}` — Signal you're ready for more work
- `clawteam cost report {team} --input-tokens <N> --output-tokens <N> --cost-cents <N>` — Report costs

### Protocol
1. Check your tasks: `clawteam task list {team} --owner {agent_name}`
2. If that list is empty, inspect `clawteam task list {team}` and your inbox before declaring yourself idle
3. For each task, update status to in_progress before starting
4. Commit changes frequently with git
5. Mark tasks completed when done
6. Check for new messages and tasks after completing your batch
7. If idle, signal with `clawteam lifecycle idle {team}`
8. The harness manages your lifecycle — focus on the task at hand
"""


def build_wrapped_prompt(
    agent_name: str,
    goal: str,
    team: str,
) -> str:
    """Build the initial user prompt for a wrapped agent."""
    if not goal:
        return ""
    return f"""\
## Your Task

{goal}

---
You are agent **{agent_name}** in team **{team}**.
Use `clawteam task list {team} --owner {agent_name}` to check for assigned tasks.
If that is empty, fall back to `clawteam task list {team}` and your inbox before declaring yourself idle.
When done, signal completion with `clawteam inbox send {team} leader "All tasks completed."`.
"""
