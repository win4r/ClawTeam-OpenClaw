"""Agent prompt builder — identity + task only.

Coordination knowledge (how to use clawteam CLI) is provided
by the ClawTeam Skill, not duplicated here.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Boids-inspired coordination rules (Reynolds 1986, adapted for LLM agents)
# Injected when team_size > 1 to enable emergent coordination.
# ---------------------------------------------------------------------------

BOIDS_RULES = """## Coordination Rules

As a member of a multi-agent team, follow these four rules:

1. **Separation** — Do not duplicate work another agent has done or is doing. Check task statuses before starting.
2. **Alignment** — Follow the team lead's direction and maintain consistent standards (code style, naming, approach).
3. **Cohesion** — Proactively share discoveries by writing to the shared workspace. Make your findings visible to the team.
4. **Boundary** — Stay within your assigned scope. Do not modify files or areas owned by other agents without coordination."""

# ---------------------------------------------------------------------------
# Metacognitive self-evaluation block
# Injected into agent prompts so agents report confidence and escalate
# when uncertain. Based on cognitive architecture research (metacognition).
# ---------------------------------------------------------------------------

METACOGNITION_BLOCK = """## Self-Evaluation

After completing each task, include a confidence assessment:
- Tag your output with `[confidence: 0.X]` where X is 0-10 (e.g., `[confidence: 0.8]`).
- If confidence < 0.6, explain what you are uncertain about and recommend human review.
- If you encounter something outside your expertise, say so and suggest escalation rather than guessing."""


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
    intent: str = "",
    end_state: str = "",
    constraints: list[str] | None = None,
    team_size: int = 1,
) -> str:
    """Build agent prompt: identity + mission + task + optional workspace info."""
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
    # Mission section (Auftragstaktik: intent + end_state + constraints)
    if intent or end_state or constraints:
        lines.extend(["", "## Mission\n"])
        if intent:
            lines.append(f"**Intent:** {intent}")
        if end_state:
            lines.append(f"**End State:** {end_state}")
        if constraints:
            lines.append("**Constraints:**")
            for c in constraints:
                lines.append(f"- {c}")
    if workspace_dir:
        lines.extend([
            "",
            "## Workspace",
            f"- Working directory: {workspace_dir}",
            f"- Branch: {workspace_branch}",
            "- This is an isolated git worktree. Your changes do not affect the main branch.",
        ])
    if memory_scope:
        lines.extend([
            "",
            "## Shared Memory",
            f"- Your team shares memory scope `{memory_scope}`.",
            f"- Use `memory_store` with scope `{memory_scope}` for team-shared knowledge.",
            "- Use `memory_recall` to access memories stored by other team members in this scope.",
        ])
    if team_size > 1:
        lines.extend(["", BOIDS_RULES])
    lines.extend([
        "",
        "## Task\n",
        task,
        "",
        "## Coordination Protocol\n",
        "- IMPORTANT: spawned OpenClaw workers run under exec allowlist mode. Use only the allowlisted executable path from $CLAWTEAM_BIN, not arbitrary shell commands.",
        f"- First action: run `clawteam task list {team_name} --owner {agent_name}` to discover your task ID.",
        f"- Starting a task: `clawteam task update {team_name} <task-id> --status in_progress`",
        f"- Finishing a task: `clawteam task update {team_name} <task-id> --status completed`",
        "- When you finish all tasks, send a summary to the leader:",
        f'  `clawteam inbox send {team_name} {leader_name} "All tasks completed. <brief summary>"`',
        "- If you are blocked or any clawteam command is denied/fails, message the leader immediately with the exact error text:",
        f'  `clawteam inbox send {team_name} {leader_name} "Blocked: <exact error>"`',
        f"- After finishing work, report your costs: `clawteam cost report {team_name} --input-tokens <N> --output-tokens <N> --cost-cents <N>`",
        f"- Before finishing, save your session: `clawteam session save {team_name} --session-id <id>`",
        "- When you finish all tasks, type `exit` to terminate this session.",
        "",
        METACOGNITION_BLOCK,
        "",
    ])
    return "\n".join(lines)
