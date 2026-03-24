"""Agent prompt builder — identity + task only.

Coordination knowledge (how to use clawteam CLI) is provided
by the ClawTeam Skill, not duplicated here.
"""

from __future__ import annotations


def build_agent_prompt(
    agent_name: str,
    agent_id: str,
    agent_type: str,
    team_name: str,
    leader_name: str,
    task: str,
    user: str = "",
    workspace_dir: str = "",
    workspace_branch: str = "",
    memory_scope: str = "",
    task_id: str = "",
) -> str:
    """Build agent prompt: identity + task + optional workspace info."""
    lines = [
        "## Identity\n",
        f"- Name: {agent_name}",
        f"- ID: {agent_id}",
    ]
    if user:
        lines.append(f"- User: {user}")
    lines.extend(
        [
            f"- Type: {agent_type}",
            f"- Team: {team_name}",
            f"- Leader: {leader_name}",
        ]
    )
    if workspace_dir:
        lines.extend(
            [
                "",
                "## Workspace",
                f"- Working directory: {workspace_dir}",
                f"- Branch: {workspace_branch}",
                "- This is an isolated git worktree. Your changes do not affect the main branch.",
            ]
        )
    if memory_scope:
        lines.extend(
            [
                "",
                "## Shared Memory",
                f"- Your team shares memory scope `{memory_scope}`.",
                f"- Use `memory_store` with scope `{memory_scope}` for team-shared knowledge.",
                f"- Use `memory_recall` to access memories stored by other team members in this scope.",
            ]
        )
    if task_id:
        lines.extend(
            [
                "",
                "## Task ID",
                f"- Your task ID: {task_id}",
                f"- Use this ID when updating task status: `clawteam task update {team_name} {task_id} --status <status>`",
            ]
        )
    lines.extend(
        [
            "",
            "## Task\n",
            task,
            "",
            "## Coordination Protocol\n",
            f"- Use `clawteam task list {team_name} --owner {agent_name}` to see your tasks.",
            f"- Starting a task: `clawteam task update {team_name} <task-id> --status in_progress`",
            f"- Finishing a task: `clawteam task update {team_name} <task-id> --status completed`",
            "- When you finish all tasks, send a summary to the leader:",
            f'  `clawteam inbox send {team_name} {leader_name} "All tasks completed. <brief summary>"`',
            "- If you are blocked or need help, message the leader:",
            f'  `clawteam inbox send {team_name} {leader_name} "Need help: <description>"`',
            f"- After finishing work, report your costs: `clawteam cost report {team_name} --input-tokens <N> --output-tokens <N> --cost-cents <N>`",
            f"- Before finishing, save your session: `clawteam session save {team_name} --session-id <id>`",
            "",
        ]
    )
    return "\n".join(lines)
