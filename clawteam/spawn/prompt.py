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
) -> str:
    """Build agent prompt: identity + task + optional workspace info."""
    lines = [
        "## Identity\n",
        f"- Name: {agent_name}",
        f"- ID: {agent_id}",
    ]
    if user:
        lines.append(f"- User: {user}")
    lines.extend([
        f"- Type: {agent_type}",
        f"- Team: {team_name}",
        f"- Leader: {leader_name}",
    ])
    if workspace_dir:
        lines.extend([
            "",
            "## Workspace",
            f"- Working directory: {workspace_dir}",
            f"- Branch: {workspace_branch}",
            "- This is an isolated git worktree. Your changes do not affect the main branch.",
        ])
    lines.extend([
        "",
        "## Task\n",
        task,
        "",
        "## Execution Rules\n",
        "- Work only on your assigned task unless the leader explicitly changes scope.",
        "- Use real validation whenever possible; do not claim success without running relevant checks.",
        "- Do not use mock/stub results to pretend the task is complete.",
        "- If blocked, send a concrete blocker message to the leader immediately.",
        "- If work fails and the owner/next action/flow are clear, mark the task failed with failure_kind=regular.",
        "- If work fails and owner/next action/flow are unclear, mark the task failed with failure_kind=complex and escalate to the leader.",
        "- When done, report exact files changed, commands run, actual results, and remaining risks.",
        "- Do not silently stop after partial progress.",
        "- If QA fails, route the work back for implementation instead of presenting it as delivered.",
        "- 'PR created' does not mean 'merge-ready'.",
        "- A task is complete only when its stated Done when conditions are actually satisfied.",
        "",
        "## Coordination Protocol\n",
        f"- Use `clawteam task list {team_name} --owner {agent_name}` to see your tasks.",
        f"- Starting a task: `clawteam task update {team_name} <task-id> --status in_progress`",
        f"- Finishing a task: `clawteam task update {team_name} <task-id> --status completed`",
        f"- Regular fail with clear retry route: `clawteam task update {team_name} <task-id> --status failed --failure-kind regular --failure-note \"<evidence>\"`",
        f"- Complex fail needing leader decision: `clawteam task update {team_name} <task-id> --status failed --failure-kind complex --failure-root-cause \"<cause>\" --failure-evidence \"<evidence>\" --failure-recommended-next-owner \"<owner>\" --failure-recommended-action \"<action>\"`",
        "- When you finish all tasks, send a summary to the leader:",
        f'  `clawteam inbox send {team_name} {leader_name} "All tasks completed. <brief summary>"`',
        "- If you are blocked or need help, message the leader:",
        f'  `clawteam inbox send {team_name} {leader_name} "Need help: <description>"`',
        f"- After finishing work, report your costs: `clawteam cost report {team_name} --input-tokens <N> --output-tokens <N> --cost-cents <N>`",
        f"- Before finishing, save your session: `clawteam session save {team_name} --session-id <id>`",
        "",
    ])
    return "\n".join(lines)
