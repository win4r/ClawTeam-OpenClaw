---
name: ClawTeam Multi-Agent Coordination
description: >
  This skill should be used when the user asks to "create a team", "spawn agents",
  "assign tasks", "coordinate multiple agents", "check team status", "view kanban board",
  "send messages between agents", "manage team tasks", "monitor team progress",
  or mentions "clawteam", "multi-agent coordination", "team collaboration",
  "agent inbox", "task board", "spawn worker". This skill should also be triggered
  when the current task is complex enough to benefit from splitting into subtasks
  and delegating to multiple agents — for example when the user asks to "build a
  full-stack app", "refactor the entire codebase", "implement multiple features
  in parallel", or when the agent determines that the work scope exceeds what a
  single agent can efficiently handle alone. Provides comprehensive guidance for
  using the ClawTeam CLI to orchestrate multi-agent teams with task management,
  messaging, and monitoring.
version: 0.2.0
---

# ClawTeam Multi-Agent Coordination

ClawTeam is a framework-agnostic CLI tool for coordinating multiple AI agents as a team.
It provides file-based team management, inter-agent messaging, shared task tracking with
dependency resolution, plan approval workflows, and terminal-based monitoring dashboards.

All operations are performed via the `clawteam` CLI. Data is stored in `~/.clawteam/` by default.

## Installation

```bash
pip install clawteam
```

Requires Python 3.10+. For P2P transport support: `pip install clawteam[p2p]`.

## Prerequisites

- `tmux` installed (used by default spawn backend)
- A CLI coding agent (e.g. `claude`, `codex`, or any command-line agent)
- A git repository (for worktree isolation)

## Core Concepts

**Teams** — A named group of agents with one leader and zero or more workers. Created via
`clawteam team spawn-team`. The leader approves joins, reviews plans, and coordinates shutdown.

**Inbox** — File-based message queue per agent. `inbox send` for point-to-point, `inbox broadcast`
for all members. `inbox receive` consumes messages (destructive); `inbox peek` reads without consuming.

**Tasks** — Shared task board with statuses: `pending`, `in_progress`, `completed`, `blocked`.
Tasks support dependency chains (`--blocks`, `--blocked-by`). Completing a task auto-unblocks dependents.

**Board** — Terminal kanban dashboard. `board show` for single team, `board overview` for all teams,
`board live` for real-time auto-refresh, `board attach` for tiled tmux view of all agents.

**Identity** — Each agent has env vars (`CLAWTEAM_AGENT_ID`, `CLAWTEAM_AGENT_NAME`, `CLAWTEAM_AGENT_TYPE`,
`CLAWTEAM_TEAM_NAME`). Set automatically when spawned via `clawteam spawn`.

## Quick Start

### Set Up a Team with Tasks

```bash
# Set identity for the current session
export CLAWTEAM_AGENT_ID="leader-001"
export CLAWTEAM_AGENT_NAME="leader"
export CLAWTEAM_AGENT_TYPE="leader"

# Create team
clawteam team spawn-team my-team -d "Project team" -n leader

# Create tasks
clawteam task create my-team "Design system" -o leader
clawteam task create my-team "Implement feature" -o worker1
clawteam task create my-team "Write tests" -o worker2

# View board
clawteam board show my-team
```

### Spawn and Coordinate Agents

```bash
# Spawn workers — defaults: tmux backend, claude command, git worktree isolation, skip-permissions on
clawteam spawn --team my-team --agent-name worker1 --task "Implement the auth module"
clawteam spawn --team my-team --agent-name worker2 --task "Write unit tests"

# Or explicitly specify backend and command (positional args: [BACKEND] [COMMAND])
clawteam spawn tmux claude --team my-team --agent-name worker3 --task "Build API endpoints"
clawteam spawn subprocess claude --team my-team --agent-name worker4 --task "Run linting"

# Watch all agents working simultaneously (tiled tmux panes)
clawteam board attach my-team

# Send instructions
clawteam inbox send my-team worker1 "Start implementing the auth module"

# Monitor task board
clawteam board live my-team --interval 3
```

### Spawn Defaults

Spawning agents uses sensible defaults — no flags needed for the common case:

| Setting | Default | Override |
|---------|---------|----------|
| Backend | `tmux` | `clawteam spawn subprocess ...` |
| Command | `claude` | `clawteam spawn tmux my-cmd ...` |
| Workspace | `auto` (git worktree) | `--no-workspace` or config `workspace=never` |
| Permissions | skip (no approval needed) | `--no-skip-permissions` or config `skip_permissions=false` |

Agents spawned with defaults get:
- Their own **git worktree** (isolated branch, no conflicts with other agents)
- **Full tool permissions** (`--dangerously-skip-permissions`) so they can work autonomously
- A **tmux window** you can watch with `board attach`

### Task Lifecycle

```bash
# Create with dependencies
clawteam task create my-team "Deploy" --blocked-by <impl-task-id>,<test-task-id>

# Update status
clawteam task update my-team <task-id> --status in_progress
clawteam task update my-team <task-id> --status completed  # auto-unblocks dependents

# Filter tasks
clawteam task list my-team --status blocked
clawteam task list my-team --owner worker1
```

### Waiting for Sub-Agents

```bash
# Block until all tasks complete (no timeout)
clawteam task wait my-team

# With timeout and custom poll interval
clawteam task wait my-team --timeout 300 --poll-interval 10

# Monitor a specific agent's inbox instead of the leader
clawteam task wait my-team --agent coordinator

# JSON streaming output (NDJSON: progress + message events, then final result)
clawteam --json task wait my-team --timeout 600
```

### Watching Agents Work

```bash
# Tile all agent tmux windows into one view (best way to observe)
clawteam board attach my-team

# Or attach to the tmux session manually and switch windows with Ctrl-b + number
tmux attach -t clawteam-my-team
```

## Command Groups

| Group | Purpose | Key Commands |
|-------|---------|-------------|
| `team` | Team lifecycle | `spawn-team`, `discover`, `status`, `request-join`, `approve-join`, `cleanup` |
| `inbox` | Messaging | `send`, `broadcast`, `receive`, `peek`, `watch` |
| `task` | Task management | `create`, `get`, `update`, `list`, `wait` |
| `board` | Monitoring | `show`, `overview`, `live`, `attach`, `serve` |
| `plan` | Plan approval | `submit`, `approve`, `reject` |
| `lifecycle` | Agent lifecycle | `request-shutdown`, `approve-shutdown`, `idle` |
| `spawn` | Process spawning | `spawn [backend] [command]` (defaults: tmux, claude) |
| `identity` | Identity management | `show`, `set` |

## JSON Output

All commands support `--json` for machine-readable output. Place the flag before the subcommand:

```bash
clawteam --json team discover
clawteam --json board show my-team
clawteam --json task list my-team --status pending
```

Combine with `jq` for scripting:

```bash
clawteam --json board show my-team | jq '.taskSummary'
clawteam --json task list my-team | jq '.[].subject'
```

## Important Notes

- `inbox receive` **consumes** messages (deletes files). Use `inbox peek` for non-destructive reads.
- Task status `blocked` is **auto-set** when `--blocked-by` is specified at creation.
- Completing a task **auto-unblocks** any tasks that list it in `blockedBy`.
- `clawteam spawn` defaults to **tmux** backend with **git worktree** isolation and **skip-permissions**.
- All file writes use atomic tmp+rename to prevent data corruption.
- Identity env vars are set automatically when spawning via `clawteam spawn`.
- Use `board attach <team>` to watch all agents in a tiled tmux layout.

## Additional Resources

### Reference Files

For detailed command arguments, data models, and storage layout:
- **`references/cli-reference.md`** — Complete CLI reference with all commands, options, and data models

For step-by-step coordination workflows and common patterns:
- **`references/workflows.md`** — Multi-agent workflows: team setup, spawn coordination, join protocol, plan approval, graceful shutdown, monitoring patterns
