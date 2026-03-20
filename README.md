<h1 align="center">ClawTeam-OpenClaw</h1>

<p align="center">
  <strong>Multi-agent swarm coordination for CLI coding agents — <a href="https://openclaw.ai">OpenClaw</a> as default</strong>
</p>

<p align="center">
  <a href="https://github.com/HKUDS/ClawTeam"><img src="https://img.shields.io/badge/upstream-HKUDS%2FClawTeam-purple?style=for-the-badge" alt="Upstream"></a>
  <a href="#-quick-start"><img src="https://img.shields.io/badge/Quick_Start-3_min-blue?style=for-the-badge" alt="Quick Start"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge" alt="License"></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-≥3.10-blue?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/agents-OpenClaw_%7C_Claude_Code_%7C_Codex_%7C_nanobot-blueviolet" alt="Agents">
  <img src="https://img.shields.io/badge/transport-File_%7C_ZeroMQ_P2P-orange" alt="Transport">
  <img src="https://img.shields.io/badge/version-0.3.0-teal" alt="Version">
</p>

> **Fork of [HKUDS/ClawTeam](https://github.com/HKUDS/ClawTeam)** with deep OpenClaw integration: default `openclaw` agent, per-agent session isolation, exec approval auto-config, and production-hardened spawn backends. All upstream fixes are synced.

You set the goal. The agent swarm handles the rest — spawning workers, splitting tasks, coordinating, and merging results.

Works with [OpenClaw](https://openclaw.ai) (default), [Claude Code](https://claude.ai/claude-code), [Codex](https://openai.com/codex), [nanobot](https://github.com/HKUDS/nanobot), [Cursor](https://cursor.com), and any CLI agent.

---

## Why ClawTeam?

Current AI agents are powerful but work in **isolation**. ClawTeam lets agents self-organize into teams — splitting work, communicating, and converging on results without human micromanagement.

| | ClawTeam | Other multi-agent frameworks |
|---|---------|----------------------------|
| **Who uses it** | The AI agents themselves | Humans writing orchestration code |
| **Setup** | `pip install` + one prompt | Docker, cloud APIs, YAML configs |
| **Infrastructure** | Filesystem + tmux | Redis, message queues, databases |
| **Agent support** | Any CLI agent | Framework-specific only |
| **Isolation** | Git worktrees (real branches) | Containers or virtual envs |

---

## How It Works

<table>
<tr>
<td width="33%">

### Agents Spawn Agents
The leader calls `clawteam spawn` to create workers. Each gets its own **git worktree**, **tmux window**, and **identity**.

```bash
clawteam spawn --team my-team \
  --agent-name worker1 \
  --task "Implement auth module"
```

</td>
<td width="33%">

### Agents Talk to Agents
Workers check inboxes, update tasks, and report results — all through CLI commands **auto-injected** into their prompt.

```bash
clawteam task list my-team --owner me
clawteam inbox send my-team leader \
  "Auth done. All tests passing."
```

</td>
<td width="33%">

### You Just Watch
Monitor the swarm from a tiled tmux view or Web UI. The leader handles coordination.

```bash
clawteam board attach my-team
# Or web dashboard
clawteam board serve --port 8080
```

</td>
</tr>
</table>

---

## Quick Start

### Option 1: Let the Agent Drive (Recommended)

Install ClawTeam, then prompt your agent:

```
"Build a web app. Use clawteam to split the work across multiple agents."
```

The agent auto-creates a team, spawns workers, assigns tasks, and coordinates — all via `clawteam` CLI.

### Option 2: Drive It Manually

```bash
# Create a team
clawteam team spawn-team my-team -d "Build the auth module" -n leader

# Spawn workers — each gets a git worktree + tmux window
clawteam spawn --team my-team --agent-name alice --task "Implement OAuth2 flow"
clawteam spawn --team my-team --agent-name bob   --task "Write unit tests for auth"

# Watch them work
clawteam board attach my-team
```

### Supported Agents

| Agent | Spawn Command | Status |
|-------|--------------|--------|
| [OpenClaw](https://openclaw.ai) | `clawteam spawn tmux openclaw --team ...` | **Default** |
| [Claude Code](https://claude.ai/claude-code) | `clawteam spawn tmux claude --team ...` | Full support |
| [Codex](https://openai.com/codex) | `clawteam spawn tmux codex --team ...` | Full support |
| [nanobot](https://github.com/HKUDS/nanobot) | `clawteam spawn tmux nanobot --team ...` | Full support |
| [Cursor](https://cursor.com) | `clawteam spawn subprocess cursor --team ...` | Experimental |
| Custom scripts | `clawteam spawn subprocess python --team ...` | Full support |

---

## Install

### Step 1: Prerequisites

ClawTeam requires **Python 3.10+**, **tmux**, and at least one CLI coding agent (OpenClaw, Claude Code, Codex, etc.).

**Check what you already have:**

```bash
python3 --version   # Need 3.10+
tmux -V             # Need any version
openclaw --version  # Or: claude --version / codex --version
```

**Install missing prerequisites:**

| Tool | macOS | Ubuntu/Debian |
|------|-------|---------------|
| Python 3.10+ | `brew install python@3.12` | `sudo apt update && sudo apt install python3 python3-pip` |
| tmux | `brew install tmux` | `sudo apt install tmux` |
| OpenClaw | `pip install openclaw` | `pip install openclaw` |

> If using Claude Code or Codex instead of OpenClaw, install those per their own docs. OpenClaw is the default but not strictly required.

### Step 2: Install ClawTeam

> **Important:** Do not use `pip install clawteam` — that installs the upstream version from PyPI, which defaults to `claude` and lacks the OpenClaw adaptations. Always install from this repo.

```bash
git clone https://github.com/win4r/ClawTeam-OpenClaw.git
cd ClawTeam-OpenClaw
pip install -e .
```

Optional — P2P transport (ZeroMQ):

```bash
pip install -e ".[p2p]"
```

### Step 3: Create the `~/bin/clawteam` symlink

Spawned agents run in fresh shells that may not have pip's bin directory in PATH. A symlink in `~/bin` ensures `clawteam` is always reachable:

```bash
mkdir -p ~/bin
ln -sf "$(which clawteam)" ~/bin/clawteam
```

If `which clawteam` returns nothing, find the binary manually:

```bash
# Common locations:
# ~/.local/bin/clawteam
# /opt/homebrew/bin/clawteam
# /usr/local/bin/clawteam
# /Library/Frameworks/Python.framework/Versions/3.*/bin/clawteam
find / -name clawteam -type f 2>/dev/null | head -5
```

Then ensure `~/bin` is in your PATH — add this to `~/.zshrc` or `~/.bashrc` if it isn't:

```bash
export PATH="$HOME/bin:$PATH"
```

### Step 4: Install the OpenClaw skill (OpenClaw users only)

The skill file teaches OpenClaw agents how to use ClawTeam through natural language. Skip this step if you're not using OpenClaw.

```bash
mkdir -p ~/.openclaw/workspace/skills/clawteam
cp skills/openclaw/SKILL.md ~/.openclaw/workspace/skills/clawteam/SKILL.md
```

### Step 5: Configure exec approvals (OpenClaw users only)

Spawned OpenClaw agents need permission to run `clawteam` commands. Without this, agents will block on interactive permission prompts.

```bash
# Ensure security mode is "allowlist" (not "full")
python3 -c "
import json, pathlib
p = pathlib.Path.home() / '.openclaw' / 'exec-approvals.json'
if p.exists():
    d = json.loads(p.read_text())
    d.setdefault('defaults', {})['security'] = 'allowlist'
    p.write_text(json.dumps(d, indent=2))
    print('exec-approvals.json updated: security = allowlist')
else:
    print('exec-approvals.json not found — run openclaw once first, then re-run this step')
"

# Add clawteam to the allowlist
openclaw approvals allowlist add --agent "*" "*/clawteam"
```

> If `openclaw approvals` fails, the OpenClaw gateway may not be running. Start it first, then retry.

### Step 6: Verify

```bash
clawteam --version          # Should print version
clawteam config health      # Should show all green
```

If using OpenClaw, also verify the skill is loaded:

```bash
openclaw skills list | grep clawteam
```

### Automated installer

Steps 2–6 above are also available as a single script:

```bash
git clone https://github.com/win4r/ClawTeam-OpenClaw.git
cd ClawTeam-OpenClaw
bash scripts/install-openclaw.sh
```

### Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| `clawteam: command not found` | pip bin dir not in PATH | Run Step 3 (symlink + PATH) |
| Spawned agents can't find `clawteam` | Agents run in fresh shells without pip PATH | Verify `~/bin/clawteam` symlink exists and `~/bin` is in PATH |
| `openclaw approvals` fails | Gateway not running | Start `openclaw gateway` first, then retry Step 5 |
| `exec-approvals.json not found` | OpenClaw never ran | Run `openclaw` once to generate config, then retry Step 5 |
| Agents block on permission prompts | Exec approvals security is "full" | Run Step 5 to switch to "allowlist" |
| `pip install -e .` fails | Missing build deps | Run `pip install hatchling` first |

---

## Use Cases

### 1. Autonomous ML Research — 8 Agents x 8 GPUs

Based on [@karpathy/autoresearch](https://github.com/karpathy/autoresearch). One prompt launches 8 research agents across H100s that design 2000+ experiments autonomously.

```
Human: "Use 8 GPUs to optimize train.py. Read program.md for instructions."

Leader agent:
├── Spawns 8 agents, each assigned a research direction (depth, width, LR, batch size...)
├── Each agent gets its own git worktree for isolated experiments
├── Every 30 min: checks results, cross-pollinates best configs to new agents
├── Reassigns GPUs as agents finish — fresh agents start from best known config
└── Result: val_bpb 1.044 → 0.977 (6.4% improvement) across 2430 experiments in ~30 GPU-hours
```

Full results: [novix-science/autoresearch](https://github.com/novix-science/autoresearch)

### 2. Agentic Software Engineering

```
Human: "Build a full-stack todo app with auth, database, and React frontend."

Leader agent:
├── Creates tasks with dependency chains (API schema → auth + DB → frontend → tests)
├── Spawns 5 agents (architect, 2 backend, frontend, tester) in separate worktrees
├── Dependencies auto-resolve: architect completes → backend unblocks → tester unblocks
├── Agents coordinate via inbox: "Here's the OpenAPI spec", "Auth endpoints ready"
└── Leader merges all worktrees into main when complete
```

### 3. AI Hedge Fund — Template Launch

A TOML template spawns a complete 7-agent investment team with one command:

```bash
clawteam launch hedge-fund --team fund1 --goal "Analyze AAPL, MSFT, NVDA for Q2 2026"
```

5 analyst agents (value, growth, technical, fundamentals, sentiment) work in parallel. Risk manager synthesizes all signals. Portfolio manager makes final decisions.

Templates are TOML files — **create your own** for any domain.

---

## Features

<table>
<tr>
<td width="50%">

### Agent Self-Organization
- Leader spawns and manages workers
- Auto-injected coordination prompt — zero manual setup
- Workers self-report status and idle state
- Any CLI agent can participate

### Workspace Isolation
- Each agent gets its own **git worktree**
- No merge conflicts between parallel agents
- Checkpoint, merge, and cleanup commands
- Branch naming: `clawteam/{team}/{agent}`

### Task Tracking with Dependencies
- Shared kanban: `pending` → `in_progress` → `completed` / `blocked`
- `--blocked-by` chains with auto-unblock on completion
- `task wait` blocks until all tasks complete

</td>
<td width="50%">

### Inter-Agent Messaging
- Point-to-point inboxes (send, receive, peek)
- Broadcast to all team members
- File-based (default) or ZeroMQ P2P transport

### Monitoring & Dashboards
- `board show` — terminal kanban
- `board live` — auto-refreshing dashboard
- `board attach` — tiled tmux view of all agents
- `board serve` — Web UI with real-time updates

### Team Templates
- TOML files define team archetypes (roles, tasks, prompts)
- One command: `clawteam launch <template>`
- Variable substitution: `{goal}`, `{team_name}`, `{agent_name}`

</td>
</tr>
</table>

**Also:** plan approval workflows, graceful lifecycle management, `--json` output on all commands, cross-machine support (NFS/SSHFS or P2P), multi-user namespacing, spawn validation with auto-rollback, `fcntl` file locking for concurrent safety.

---

## OpenClaw Integration

This fork makes [OpenClaw](https://openclaw.ai) the **default agent**. Without ClawTeam, each OpenClaw agent works in isolation. ClawTeam transforms it into a multi-agent platform.

| Capability | OpenClaw Alone | OpenClaw + ClawTeam |
|-----------|---------------|-------------------|
| **Task assignment** | Manual per-agent messaging | Leader autonomously splits, assigns, monitors |
| **Parallel development** | Shared working directory | Isolated git worktrees per agent |
| **Dependencies** | Manual polling | `--blocked-by` with auto-unblock |
| **Communication** | Only through AGI relay | Direct point-to-point inbox + broadcast |
| **Observability** | Read logs | Kanban board + tiled tmux view |

Once the skill is installed, talk to your OpenClaw bot in any channel:

| What you say | What happens |
|-------------|-------------|
| "Create a 5-agent team to build a web app" | Creates team, tasks, spawns 5 agents in tmux |
| "Launch a hedge-fund analysis team" | `clawteam launch hedge-fund` with 7 agents |
| "Check the status of my agent team" | `clawteam board show` with kanban output |

```
  You (Telegram/Discord/TUI)
         │
         ▼
  ┌──────────────────┐
  │  OpenClaw Gateway │  ← activates clawteam skill
  └────────┬─────────┘
           │
           ▼
  ┌──────────────────┐     clawteam spawn     ┌─────────────────┐
  │  Leader Agent    │ ─────────────────────► │  openclaw tui   │
  │  (openclaw)      │ ──┐                    │  (tmux window)  │
  │                  │   │                    │  git worktree   │
  │  Manages swarm   │   ├──────────────────► ├─────────────────┤
  │  via clawteam    │   │                    │  openclaw tui   │
  │  CLI             │   ├──────────────────► ├─────────────────┤
  └──────────────────┘   │                    │  openclaw tui   │
                         └──────────────────► └─────────────────┘
                                               All coordinate via
                                               ~/.clawteam/ (tasks, inboxes)
```

---

## Architecture

```
  Human: "Optimize this LLM"
         │
         ▼
  ┌──────────────┐     clawteam spawn     ┌──────────────┐
  │  Leader      │ ──────────────────────► │  Worker      │
  │  (any agent) │ ──────┐                │  git worktree │
  │              │       ├──────────────► │  tmux window  │
  │  spawn       │       │                ├──────────────┤
  │  task create │       ├──────────────► │  Worker      │
  │  inbox send  │       │                │  git worktree │
  │  board show  │       └──────────────► │  tmux window  │
  └──────────────┘                        └──────────────┘
                                                 │
                                                 ▼
                                      ┌─────────────────────┐
                                      │    ~/.clawteam/     │
                                      │ ├── teams/   (who) │
                                      │ ├── tasks/   (what)│
                                      │ ├── inboxes/ (talk)│
                                      │ └── workspaces/    │
                                      └─────────────────────┘
```

All state lives in `~/.clawteam/` as JSON files. No database, no server. Atomic writes with `fcntl` file locking ensure crash safety.

| Setting | Env Var | Default |
|---------|---------|---------|
| Data directory | `CLAWTEAM_DATA_DIR` | `~/.clawteam` |
| Transport | `CLAWTEAM_TRANSPORT` | `file` |
| Workspace mode | `CLAWTEAM_WORKSPACE` | `auto` |
| Spawn backend | `CLAWTEAM_DEFAULT_BACKEND` | `tmux` |

---

## Command Reference

<details open>
<summary><strong>Core Commands</strong></summary>

```bash
# Team lifecycle
clawteam team spawn-team <team> -d "description" -n <leader>
clawteam team discover                    # List all teams
clawteam team status <team>               # Show members
clawteam team cleanup <team> --force      # Delete team

# Spawn agents
clawteam spawn --team <team> --agent-name <name> --task "do this"
clawteam spawn tmux codex --team <team> --agent-name <name> --task "do this"

# Task management
clawteam task create <team> "subject" -o <owner> --blocked-by <id1>,<id2>
clawteam task update <team> <id> --status completed   # auto-unblocks dependents
clawteam task list <team> --status blocked --owner worker1
clawteam task wait <team> --timeout 300

# Messaging
clawteam inbox send <team> <to> "message"
clawteam inbox broadcast <team> "message"
clawteam inbox receive <team>             # consume messages
clawteam inbox peek <team>                # read without consuming

# Monitoring
clawteam board show <team>                # terminal kanban
clawteam board live <team> --interval 3   # auto-refresh
clawteam board attach <team>              # tiled tmux view
clawteam board serve --port 8080          # web UI
```

</details>

<details>
<summary><strong>Workspace, Plan, Lifecycle, Config</strong></summary>

```bash
# Workspace (git worktree management)
clawteam workspace list <team>
clawteam workspace checkpoint <team> <agent>    # auto-commit
clawteam workspace merge <team> <agent>         # merge back to main
clawteam workspace cleanup <team> <agent>       # remove worktree

# Plan approval
clawteam plan submit <team> <agent> "plan" --summary "TL;DR"
clawteam plan approve <team> <plan-id> <agent> --feedback "LGTM"
clawteam plan reject <team> <plan-id> <agent> --feedback "Revise X"

# Lifecycle
clawteam lifecycle request-shutdown <team> <agent> --reason "done"
clawteam lifecycle approve-shutdown <team> <request-id> <agent>
clawteam lifecycle idle <team>

# Templates
clawteam launch <template> --team <name> --goal "Build X"
clawteam template list

# Config
clawteam config show
clawteam config set transport p2p
clawteam config health
```

</details>

---

## Roadmap

| Version | What | Status |
|---------|------|--------|
| v0.3 | File + P2P transport, Web UI, multi-user, templates | Shipped |
| v0.4 | Redis transport — cross-machine messaging | Planned |
| v0.5 | Shared state layer — team config across machines | Planned |
| v0.6 | Agent marketplace — community templates | Exploring |
| v0.7 | Adaptive scheduling — dynamic task reassignment | Exploring |
| v1.0 | Production-grade — auth, permissions, audit logs | Exploring |

---

## Contributing

We welcome contributions:

- **Agent integrations** — support for more CLI agents
- **Team templates** — TOML templates for new domains
- **Transport backends** — Redis, NATS, etc.
- **Dashboard improvements** — Web UI, Grafana
- **Documentation** — tutorials and best practices

---

## Acknowledgements

- [@karpathy/autoresearch](https://github.com/karpathy/autoresearch) — autonomous ML research framework
- [OpenClaw](https://openclaw.ai) — default agent backend
- [Claude Code](https://claude.ai/claude-code) and [Codex](https://openai.com/codex) — supported AI coding agents
- [ai-hedge-fund](https://github.com/virattt/ai-hedge-fund) — hedge fund template inspiration
- [CLI-Anything](https://github.com/HKUDS/CLI-Anything) — sister project

## License

MIT — free to use, modify, and distribute.

---

<div align="center">

**ClawTeam** — *Agent Swarm Intelligence.*

</div>
