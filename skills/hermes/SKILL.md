---
name: clawteam
description: "Multi-agent swarm orchestration. USE THIS (not delegate_task) when the user says team/swarm/multi-agent/clawteam/parallel-agents/agent-team, or asks for multi-perspective analysis (stocks, research, code review, strategy). Spawns N Hermes workers in tmux windows with git worktree isolation, file-based inboxes, and a kanban board. Four built-in templates: hedge-fund (7 analyst agents), research-paper, code-review, strategy-room."
version: 0.3.0
author: ClawTeam / Hermes Adapter
license: MIT
metadata:
  hermes:
    tags: [Multi-Agent, Swarm, Coordination, Teams]
---

# ClawTeam - Multi-Agent Swarm Coordination for Hermes

## When To Use This Skill

USE CLAWTEAM (not `delegate_task`) when:
- User explicitly says: clawteam, team, swarm, multi-agent, parallel agents, agent team
- User asks for multi-perspective analysis that benefits from specialist agents (e.g., "analyze TSLA stock" -> hedge-fund template has 7 specialist analysts)
- User wants research across multiple sources (research-paper template)
- User wants code review from multiple angles (code-review template)
- User wants business strategy brainstorming (strategy-room template)

DO NOT use `delegate_task` for these cases. `delegate_task` is a single sub-agent; clawteam is 5-7 specialist agents running in parallel with a kanban board and shared inboxes. For stock/research/review questions, clawteam produces dramatically better output.

## Critical Flags (get these right the first time)

For `clawteam launch`:
- `--team-name` (NOT `--team`)
- `-g` or `--goal` for the prompt
- `--command hermes` (REQUIRED for Hermes users — templates default to `openclaw` and will fail with gateway token errors if OpenClaw isn't set up)
- `--force` to suppress the max-agent warning

For `clawteam spawn` (manual mode):
- `-t <team>` team name
- `-n <agent-name>` agent name
- `--task "<prompt>"` task description
- `--no-workspace` to skip git worktree creation (optional)
- Trailing positional arg: `hermes` (NOT `--command hermes`)

## Launch a Template (Recommended Path)

```bash
# Stock analysis (Hermes-native template using gbrain for output — RECOMMENDED for Hermes users)
clawteam launch hedge-fund-hermes --team-name tesla --goal "Analyze TSLA" --force

# Stock analysis (original OpenClaw-style template — relies on clawteam inbox send which Hermes workers often skip)
clawteam launch hedge-fund --team-name tesla --goal "Analyze TSLA" --command hermes --force

# Research paper summary
clawteam launch research-paper --team-name papers --goal "Survey arxiv 2024.X" --command hermes --force

# Code review (multiple perspectives)
clawteam launch code-review --team-name review1 --goal "Review PR #42" --command hermes --force

# Business strategy
clawteam launch strategy-room --team-name strat --goal "Q2 planning" --command hermes --force
```

## Reading Output from `hedge-fund-hermes` (Preferred Path)

The Hermes-native template stores each analyst's findings as a gbrain page with a predictable slug. After launch + ~2 minutes wait:

```bash
# Query all findings at once
mcp_gbrain_query("<team-name> analyst")

# Or read each analyst's page directly
for analyst in buffett growth technical fundamentals sentiment risk; do
  mcp_gbrain_get_page("<team-name>-$analyst")
done

# Portfolio manager stores the final synthesis here
mcp_gbrain_get_page("<team-name>-final-report")
```

**Why this works better than `hedge-fund`**: Hermes workers reliably call `mcp_gbrain_put_page` because gbrain is their native MCP surface. They often skip the `clawteam inbox send` step in the OpenClaw-style template.

Benefits:
- Findings persist in Postgres across sessions
- No tmux scrollback fragility
- Next week's analysis can query prior reports
- Cross-agent memory works natively

## CRITICAL: Timing Expectations (DO NOT cleanup early)

Spawned Hermes workers need substantial time to produce output:
- **Boot: 20-40 seconds per worker** (loading 62 tools + 113 skills + MCP servers)
- **Research/analysis: 1-5 minutes** depending on task complexity
- **Hedge-fund template (7 analysts running in parallel): typically 2-5 minutes total**

After launching a team, WAIT before checking results. NEVER check inboxes within the first 60 seconds — they will be empty and you will incorrectly conclude the team failed.

Correct polling pattern for a hedge-fund team:

```bash
# Launch
clawteam launch hedge-fund --team-name <name> --goal "<prompt>" --command hermes --force

# Wait for boot (mandatory, do not skip)
sleep 60

# Poll the board every 30 seconds until tasks move to COMPLETED.
# Maximum total wait: ~5 minutes. Use tmux capture to see worker progress.
for i in 1 2 3 4 5 6 7 8; do
  sleep 30
  echo "=== tick $i ($(( i * 30 + 60 ))s elapsed) ==="
  clawteam board show <name>
  # Check if any non-leader task is COMPLETED (then continue monitoring)
  # Break the loop only when most/all tasks show COMPLETED
done

# Only read inboxes after tasks show COMPLETED on the board
for agent in portfolio-manager buffett-analyst growth-analyst technical-analyst fundamentals-analyst sentiment-analyst risk-manager; do
  echo "=== $agent ==="
  clawteam inbox peek <name> --agent $agent
done

# Clean up ONLY after you've read the reports
clawteam team cleanup <name> --force
```

If inboxes are still empty after 5 minutes, something is wrong (token auth, model provider, or worker crashed). Inspect instead of giving up:

```bash
clawteam team status <name>                                  # Check liveness of each agent
tmux list-windows -t clawteam-<name> 2>/dev/null             # Confirm tmux panes exist
tmux capture-pane -t clawteam-<name>:0 -p 2>&1 | tail -30    # Inspect worker 0's output
```

## Manual Inbox/Cleanup Commands (reference)

```bash
clawteam board show <team>                   # Kanban view
clawteam board live <team>                   # Auto-refreshing board
clawteam inbox peek <team> --agent <name>    # Peek one agent's inbox
clawteam team status <team>                  # Agent liveness + health
clawteam team cleanup <team> --force         # Delete team (only after reading reports)
```

## Manual Team Setup (For Custom Teams)

When no template fits:

```bash
# 1. Create team
clawteam team spawn-team my-team -d "Goal description" -n leader

# 2. Spawn Hermes workers (hermes is a positional arg at the end, NOT --command hermes)
clawteam spawn -t my-team -n researcher --task "Research X" --no-workspace hermes
clawteam spawn -t my-team -n writer --task "Write report based on researcher's findings" --no-workspace hermes

# 3. Monitor
clawteam board show my-team
```

## How The Hermes Adapter Builds Commands

When ClawTeam spawns a Hermes worker, the adapter builds:

```
hermes chat --yolo --source tool -q "<task prompt>"
```

Notes on each flag:
- `chat` subcommand inserted only if user passed bare `hermes`
- `--yolo` when `skip_permissions=True` (default for clawteam)
- `--source tool` tags the session so clawteam spawns don't pollute your user session list
- `-q "<prompt>"` passes the task as a one-shot query
- No `--continue` — Hermes auto-generates a fresh session ID per spawn
- `-m <model>` added if `--model` was passed to clawteam

## Brain-Aware Teams

Spawned Hermes workers inherit MCP servers from `~/.hermes/config.yaml`. If you have gbrain configured, every worker automatically has knowledge brain access. Use this for:

- Shared context: workers read/write brain pages to share findings
- Knowledge accumulation: discoveries get stored in gbrain
- Cross-agent memory: worker B queries what worker A stored

Include brain instructions in task prompts:
```bash
clawteam spawn -t research -n analyst --task "Research topic X. Query gbrain for prior work first. Store findings as brain pages." --no-workspace hermes
```

## Command Reference

### Team Management

| Command | Description |
|---------|-------------|
| `clawteam team spawn-team <name> -d "<desc>" -n <leader>` | Create team |
| `clawteam team discover` | List all teams |
| `clawteam team status <team>` | Show team status |
| `clawteam team cleanup <team> --force` | Delete team |

### Launching Templates

| Command | Description |
|---------|-------------|
| `clawteam launch <template> --team-name <name> --goal "<prompt>" --command hermes --force` | One-command team launch |
| `clawteam template list` | List available templates |

### Spawning Agents Manually

| Command | Description |
|---------|-------------|
| `clawteam spawn -t <team> -n <name> --task "<prompt>" hermes` | Spawn Hermes worker |
| `clawteam spawn -t <team> -n <name> --task "<prompt>" --skip-permissions hermes` | Spawn with --yolo |
| `clawteam spawn -t <team> -n <name> --task "<prompt>" -m claude-sonnet-4 hermes` | Spawn with specific model |

### Task Management

| Command | Description |
|---------|-------------|
| `clawteam task create <team> "<desc>" -o <owner>` | Create task |
| `clawteam task create <team> "<desc>" -o <owner> --blocked-by <id>` | Create with dependency |
| `clawteam task update <team> <id> --status completed` | Complete task |
| `clawteam task list <team>` | List all tasks |

### Messaging

| Command | Description |
|---------|-------------|
| `clawteam msg send <team> --from <name> --to <name> "<msg>"` | Direct message |
| `clawteam msg broadcast <team> --from <name> "<msg>"` | Broadcast to all |
| `clawteam inbox peek <team> --agent <name>` | Peek at inbox |
| `clawteam inbox receive <team>` | Drain your own inbox |

### Monitoring

| Command | Description |
|---------|-------------|
| `clawteam board show <team>` | Kanban board |
| `clawteam board attach <team>` | Tmux tiled view (requires terminal) |
| `clawteam board live <team>` | Auto-refreshing board |
| `clawteam board serve --port 8080` | Web dashboard |

## Known Failure Modes

1. **risk-manager crash**: The risk-manager agent is prone to crashing mid-execution (`"Agent 'risk-manager' exited unexpectedly. Reset N task(s) to pending"`). This can leave the team's final synthesis incomplete. If this happens, read tmux scrollback for the portfolio-manager (leader) window first — it may have the final recommendation before the crash.

2. **Inbox empty despite COMPLETED tasks**: Hermes workers write to tmux scrollback, not to the inbox system. The kanban board reflects task state but not content. Always capture tmux panes to read actual output.

3. **Workers do not persist findings**: Unless explicitly instructed to use gbrain, agent outputs exist only in tmux scrollback and are lost when the session is cleaned up. Always include brain-instructions in analysis goals.

## CRITICAL: Inbox Peek Is Unreliable — Use Tmux Capture

`clawteam inbox peek` often returns EMPTY even when tasks show COMPLETED on the board. The actual agent outputs live in **tmux scrollback**, not in the inbox system.

**Always use tmux pane capture to read agent reports:**

```bash
# List all tmux windows for the team
tmux list-windows -t clawteam-<team-name> 2>/dev/null

# Capture each window's scrollback (each window = one agent)
for win in $(tmux list-windows -t clawteam-<team-name> -F '#{window_index}' 2>/dev/null); do
  echo -e "\n\n=== Window $win ==="
  tmux capture-pane -t clawteam-<team-name>:$win -p 2>&1 | tail -100
done
```

**Also:** When launching a team for analysis work, include brain-instructions in the goal so agents store findings in gbrain — this provides a persistent fallback when tmux sessions are lost:

```bash
clawteam launch hedge-fund --team-name <name> --goal "Analyze AAPL. IMPORTANT: After completing your analysis, store key findings as brain pages using mcp_gbrain_put_page so findings persist even if the tmux session is lost." --command hermes --force
```

## Anti-Patterns (Do Not Do)

- Don't use `delegate_task` when the user asks for multi-agent/swarm/team analysis. Use clawteam.
- Don't pass `--team` (the flag is `--team-name`).
- Don't pass `--command hermes` to `spawn` (it's a positional arg at the end). That flag only works on `launch`.
- Don't forget `--command hermes` on `launch` — templates default to openclaw.
- Don't assume templates will use Hermes by default. They don't. Always pass `--command hermes`.
- Don't clean up the team before reading final reports — BUT `inbox peek` alone is unreliable; always ALSO capture tmux panes.
- Don't rely on `clawteam inbox peek` alone — tasks can be COMPLETED on the board while inbox messages are empty. Tmux scrollback capture is the source of truth.
