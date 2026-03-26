"""Agent prompt builder — identity + task only.

Coordination knowledge (how to use clawteam CLI) is provided
by the ClawTeam Skill, not duplicated here.
"""

from __future__ import annotations

import os
import shlex

from clawteam.spawn.cli_env import resolve_clawteam_executable
from clawteam.task.terminal_commands import build_terminal_task_update_command


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
    task_execution_id: str = "",
) -> str:
    """Build agent prompt: identity + task + optional workspace info."""
    clawteam_bin = resolve_clawteam_executable()
    shell_env = [
        ("CLAWTEAM_AGENT_NAME", agent_name),
        ("CLAWTEAM_AGENT_ID", agent_id),
        ("CLAWTEAM_AGENT_TYPE", agent_type),
        ("CLAWTEAM_TEAM_NAME", team_name),
        ("CLAWTEAM_BIN", clawteam_bin),
    ]
    data_dir = os.environ.get("CLAWTEAM_DATA_DIR", "").strip()
    if data_dir:
        shell_env.append(("CLAWTEAM_DATA_DIR", data_dir))
    if task_execution_id:
        shell_env.append(("CLAWTEAM_TASK_EXECUTION_ID", task_execution_id))
    runtime_completion_signal_path = os.environ.get("CLAWTEAM_RUNTIME_COMPLETION_SIGNAL_PATH", "").strip()
    if runtime_completion_signal_path:
        shell_env.append(("CLAWTEAM_RUNTIME_COMPLETION_SIGNAL_PATH", runtime_completion_signal_path))
    identity_prefix = " ".join(
        f"{key}={shlex.quote(value)}" for key, value in shell_env
    )
    clawteam_cmd = shlex.quote(clawteam_bin)
    bootstrap_cmd = (
        f"eval $({identity_prefix} {clawteam_cmd} identity set --agent-name {shlex.quote(agent_name)} "
        f"--agent-id {shlex.quote(agent_id)} --agent-type {shlex.quote(agent_type)} "
        f"--team {shlex.quote(team_name)}"
        f"{f' --data-dir {shlex.quote(data_dir)}' if data_dir else ''} --shell)"
    )
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
    if memory_scope:
        lines.extend([
            "",
            "## Shared Memory",
            f"- Your team shares memory scope `{memory_scope}`.",
            f"- Use `memory_store` with scope `{memory_scope}` for team-shared knowledge.",
            f"- Use `memory_recall` to access memories stored by other team members in this scope.",
        ])
    complete_task_cmd = build_terminal_task_update_command(
        executable=clawteam_bin,
        team_name=team_name,
        task_id="<task-id>",
        status="completed",
        execution_id=task_execution_id,
    )
    regular_fail_cmd = build_terminal_task_update_command(
        executable=clawteam_bin,
        team_name=team_name,
        task_id="<task-id>",
        status="failed",
        execution_id=task_execution_id,
        failure_kind="regular",
        failure_note="<evidence>",
    )
    complex_fail_cmd = build_terminal_task_update_command(
        executable=clawteam_bin,
        team_name=team_name,
        task_id="<task-id>",
        status="failed",
        execution_id=task_execution_id,
        failure_kind="complex",
        failure_root_cause="<cause>",
        failure_evidence="<evidence>",
        failure_recommended_next_owner="<owner>",
        failure_recommended_action="<action>",
    )

    lines.extend([
        "",
        "## Task\n",
        task,
        "",
        "## Execution Rules\n",
        "- Work only on your assigned task and the scope written in that task's Source Request / Scoped Brief / Out of Scope sections.",
        "- Leader messages may clarify or prioritize within that scope, but they do not approve new endpoints, APIs, schemas, pages, tabs, workflows, or deliverables by themselves.",
        "- If a leader message appears to expand scope beyond the task brief, stop and ask for a new task or explicit human-approved scope change instead of implementing it silently.",
        "- Use real validation whenever possible; do not claim success without running relevant checks.",
        "- Do not use mock/stub results to pretend the task is complete.",
        "- If blocked, send a concrete blocker message to the leader immediately.",
        "- If work fails and the owner/next action/flow are clear, mark the task failed with failure_kind=regular.",
        "- If work fails and owner/next action/flow are unclear, mark the task failed with failure_kind=complex and escalate to the leader.",
        "- Workflow topology belongs to the leader/template/state machine, not to workers improvising new dependency chains.",
        "- Do not create new repair/retry/review tasks or rewire blocked_by/on_fail edges unless the leader explicitly instructs you to do so.",
        "- When done, report exact files changed, commands run, actual results, and remaining risks.",
        "- Do not silently stop after partial progress.",
        "- If QA fails, route the work back for implementation instead of presenting it as delivered.",
        "- 'PR created' does not mean 'merge-ready'.",
        "- A task is complete only when its stated Done when conditions are actually satisfied.",
        "- Use structured result blocks instead of free-form prose.",
        "- Keep summary, evidence, validation, and next action in separate sections.",
        "- Do not mix optional suggestions into required fixes.",
        "- If a section has no content, write `none` instead of omitting the section.",
        "",
        "## Result Block Formats\n",
        "- SETUP_RESULT must include exactly these headings: status, remote_status, remote_head, detached_worktree, detached_head, install, baseline_validation, known_limitations, next_action.",
        "- SETUP_RESULT remote_status must be confirmed_latest, cached_only, or unreachable.",
        "- For setup tasks, fail closed: do not claim latest main unless `git ls-remote --heads <remote> <branch>` succeeded; if remote probing fails or times out, report cached_only or unreachable explicitly.",
        "- For setup tasks, if you need a bounded remote probe, do not rely on Linux-only `timeout`; use `python3` / subprocess timeout or the host tool's timeout so the same step works on macOS too.",
        "- For setup tasks, detached worktree evidence must include the path plus actual `git rev-parse HEAD` / `git status --short --branch` output from that detached workspace.",
        "- For setup tasks, baseline validation must be discovered before execution (for example pyproject / README / Makefile / package.json / tests); do not guess a test path and present that as proof.",
        "- DEV_RESULT must include exactly these headings: status, summary, changed_files, validation, known_issues, next_action.",
        "- QA_RESULT must include exactly these headings: status, summary, evidence, validation, risk, next_action.",
        "- REVIEW_RESULT must include exactly these headings: decision, summary, architecture_review, required_fixes, evidence, validation, next_action.",
        "- Keep required_fixes limited to must-fix items; put nice-to-have ideas outside that section or write `none`.",
        "",
        "## Coordination Protocol\n",
        "- IMPORTANT: OpenClaw shell/tool calls may not inherit your ClawTeam identity automatically.",
        "- Before using `clawteam`, bootstrap your identity in the current shell:",
        f"  `{bootstrap_cmd}`",
        "- If you run one-off commands instead of bootstrapping, prefix them explicitly with your identity:",
        f"  `{identity_prefix} {clawteam_cmd} task list {team_name} --owner {agent_name}`",
        f"- Use `{identity_prefix} {clawteam_cmd} task list {team_name} --owner {agent_name}` to see your tasks.",
        f"- Starting a task: `{identity_prefix} {clawteam_cmd} task update {team_name} <task-id> --status in_progress`",
        f"- Finishing a task: `{identity_prefix} {complete_task_cmd}`",
        "- Do not use `task create`, `--add-blocked-by`, or `--add-on-fail` to improvise workflow routing unless the leader explicitly tells you to change topology.",
        f"- Regular fail with clear retry route: `{identity_prefix} {regular_fail_cmd}`",
        f"- Complex fail needing leader decision: `{identity_prefix} {complex_fail_cmd}`",
        "- When you finish all tasks, send a summary to the leader:",
        f'  `{identity_prefix} {clawteam_cmd} inbox send {team_name} {leader_name} "All tasks completed. <brief summary>"`',
        "- If you are blocked or need help, message the leader:",
        f'  `{identity_prefix} {clawteam_cmd} inbox send {team_name} {leader_name} "Need help: <description>"`',
        f"- After finishing work, report your costs: `{identity_prefix} {clawteam_cmd} cost report {team_name} --input-tokens <N> --output-tokens <N> --cost-cents <N>`",
        f"- Before finishing, save your session: `{identity_prefix} {clawteam_cmd} session save {team_name} --session-id <id>`",
        "",
    ])
    return "\n".join(lines)
