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
    team_workspace_dir: str = "",
    memory_scope: str = "",
    intent: str = "",
    end_state: str = "",
    constraints: list[str] | None = None,
    team_size: int = 1,
    team_members: list[str] | None = None,
) -> str:
    """Build agent prompt: identity + mission + task + optional workspace info.

    Args:
        team_members: Full list of team member names (including self and leader)
                      for mesh communication awareness.
    """
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
    # Team roster — full mesh awareness
    if team_members and len(team_members) > 1:
        others = [m for m in team_members if m != agent_name]
        lines.extend([
            "",
            "## Team Roster",
            f"- You: {agent_name}",
            f"- Teammates ({len(others)}): {', '.join(others)}",
            "- You have a direct 1:1 communication link to every teammate via `clawteam inbox send`.",
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
    if workspace_dir or team_workspace_dir:
        lines.extend(["", "## Workspace"])
        if workspace_dir:
            lines.extend([
                "- **Your workspace:**",
                f"  - Path: {workspace_dir}",
                f"  - Branch: {workspace_branch}",
                "  - This is your isolated worktree — safe to experiment and develop.",
            ])
        if team_workspace_dir:
            lines.extend([
                "- **Team shared workspace:**",
                f"  - Path: {team_workspace_dir}",
                "  - ALL team members share this directory. Put **deliverables and shared outputs** here.",
                "  - Coordinate file changes via `clawteam inbox` to avoid conflicts.",
            ])
    elif workspace_dir:
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
        "",
        "### Mesh Communication (Full-Connectivity)",
        "- You have a direct 1:1 communication link to EVERY team member via `clawteam inbox send`.",
        f"- To message the leader: `clawteam inbox send {team_name} {leader_name} \"<message>\"`",
    ])
    # Add per-teammate send instructions if team roster is available
    if team_members:
        others = [m for m in team_members if m != agent_name and m != leader_name]
        if others:
            lines.append(f"- To message a teammate (e.g., {others[0]}): `clawteam inbox send {team_name} <teammate-name> \"<message>\"`")
            lines.append(f"  All teammates: {', '.join(others)}")
            lines.append(f"- You can also message MULTIPLE teammates by sending to each individually.")
    lines.extend([
        "- When you finish ALL tasks, send a summary to the leader:",
        f'  `clawteam inbox send {team_name} {leader_name} "All tasks completed. <brief summary>"`',
        "- If you are blocked or need help from any teammate, message them directly.",
        "- IMPORTANT: After sending a message via `clawteam inbox send`, check your own inbox for replies:",
        f'  `clawteam inbox receive {team_name}`',
        f"- To see who else is on the team, use: `clawteam team status {team_name}`",
        "",
        "### ClawTeam CLI Reference",
        "Here are all the clawteam commands you may need during your work:",
        "",
        "**Task Management**",
        f"- `clawteam task list {team_name} --owner <name>` — list tasks assigned to you",
        f"- `clawteam task list {team_name} --status pending` — list pending tasks",
        f"- `clawteam task get {team_name} <task-id>` — view task details",
        f"- `clawteam task update {team_name} <task-id> --status in_progress` — start a task",
        f"- `clawteam task update {team_name} <task-id> --status completed` — finish a task",
        f"- `clawteam task wait {team_name}` — wait for ALL tasks to complete",
        "",
        "**Communication**",
        f"- `clawteam inbox send {team_name} <name> \"<message>\"` — send a message to any agent",
        f"- `clawteam inbox broadcast {team_name} \"<message>\"` — broadcast to all team members",
        f"- `clawteam inbox receive {team_name}` — read and consume new messages",
        f"- `clawteam inbox peek {team_name}` — peek at messages without consuming",
        f"- `clawteam inbox log {team_name}` — view full message history",
        "",
        "**Monitoring**",
        f"- `clawteam board show {team_name}` — kanban board (tasks by status)",
        f"- `clawteam board show {team_name} --mode agents` — agent grid view (each agent's slot)",
        "",
        "**Reporting & Lifecycle**",
        f"- `clawteam cost report {team_name} --input-tokens <N> --output-tokens <N> --cost-cents <N>`",
        f"- `clawteam session save {team_name} --session-id <id>`",
        "- When all tasks are done, type `exit` to terminate this session.",
        "",
        METACOGNITION_BLOCK,
        "",
    ])
    return "\n".join(lines)
