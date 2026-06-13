# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

`clawteam` is a Python CLI for orchestrating swarms of CLI coding agents (OpenClaw, Claude Code, Codex, Hermes, nanobot, Cursor, etc.). This repo is `win4r/ClawTeam-OpenClaw` — a fork of `HKUDS/ClawTeam` where the **default agent is `openclaw`** instead of `claude`. The `+openclaw` PEP 440 local identifier in the version (e.g. `0.3.0+openclaw1`) must be preserved on bumps.

There is no server and no database. All state is JSON files under `~/.clawteam/` (overridable via `CLAWTEAM_DATA_DIR`). Agents coordinate via the shared filesystem: kanban tasks, per-recipient inboxes, team configs, git worktree registries.

## Common commands

```bash
# Dev install (from repo root)
pip install -e ".[dev]"          # dev deps: pytest, ruff
pip install -e ".[p2p]"          # optional ZeroMQ P2P transport

# Lint + test — same commands CI runs (.github/workflows/ci.yml)
ruff check clawteam/ tests/
pytest tests/                    # full suite
pytest tests/test_spawn_backends.py -v        # one file
pytest tests/test_board.py::test_foo -v        # one test
pytest -k "mailbox"              # by name

# CLI entry points
clawteam <subcommand>            # installed script
python -m clawteam <subcommand>  # module entry (clawteam/__main__.py)
```

Tests auto-isolate: `tests/conftest.py` monkeypatches both `CLAWTEAM_DATA_DIR` and `HOME` to `tmp_path`, so no test can touch real `~/.clawteam/` or `~/.clawteam/config.json`.

## Architecture — the big picture

### CLI surface

**All commands live in a single file: `clawteam/cli/commands.py` (~2700 lines).** It uses typer sub-apps:

| Sub-app | Purpose |
|---------|---------|
| `config` | `show` / `set` / `get` / `health` |
| `team` | `spawn-team` / `discover` / `status` / `request-join` / `approve-join` / `cleanup` |
| `inbox` | `send` / `broadcast` / `receive` / `peek` / `log` / `watch` |
| `task` | `create` / `get` / `update` / `list` / `stats` / `wait` |
| `cost` | `report` / `show` / `budget` |
| `session` | `save` / `show` / `clear` |
| `plan` | `submit` / `approve` / `reject` |
| `lifecycle` | `request-shutdown` / `approve-shutdown` / `idle` / `on-exit` / `check-zombies` |
| `runtime` | tmux-only live injection: `inject` / `watch` / `state` |
| `identity` | `show` / `set` |
| `board` | `show` / `overview` / `live` / `serve` (web UI) / `attach` (tmux tiled view) |
| `workspace` | `list` / `checkpoint` / `merge` / `cleanup` / `status` |
| `template` | `list` / `show` |
| (top-level) | `spawn` and `launch` |

Subtle trap: `spawn` takes `--team` / `-t`, but `launch` takes `--team-name` / `-t`. These flag names are intentionally different and appear in user docs — do not "harmonize" them.

The `_output(data, human_fn)` helper picks JSON vs. human-readable output based on the global `--json` flag. Always call it instead of `print()` for command results.

### Two pluggable backends

**Transport** (`clawteam/transport/`) — how messages move between agents.
- `Transport` ABC → `FileTransport` (default, writes `inboxes/{agent}/msg-*.json` atomically) or `P2PTransport` (ZMQ PUSH/PULL with FileTransport fallback, requires `[p2p]` extra).
- `MailboxManager` in `clawteam/team/mailbox.py` builds `TeamMessage` pydantic models, serialises, delegates bytes to the transport.
- Selection: `CLAWTEAM_TRANSPORT` env var → config → `"file"`.

**TaskStore** (`clawteam/store/`) — kanban task persistence.
- `BaseTaskStore` ABC → `FileTaskStore` (only implementation today). Shim at `clawteam/team/tasks.py` preserves the legacy `TaskStore` import path.
- Selection: `CLAWTEAM_TASK_STORE` env var → config → `"file"`.

Both factories live in `clawteam/{transport,store}/__init__.py`.

### Spawn system

Splits cleanly in two:

1. **Backend** (`clawteam/spawn/{base,tmux_backend,subprocess_backend}.py`) — how the process is launched.
   - `SpawnBackend` ABC → `TmuxBackend` (one tmux session per team, `clawteam-{team}`, one window per agent) or `SubprocessBackend`.
   - Factory: `get_backend(name)` in `clawteam/spawn/__init__.py`. `normalize_backend_name()` forces `tmux → subprocess` on Windows.
   - Default per-platform from `platform_compat.default_spawn_backend()`: `tmux` on Unix, `subprocess` on Windows.
   - `spawn_with_retry()` wraps a backend with exponential-backoff retry.

2. **Command prep** (`clawteam/spawn/adapters.py`) — how CLI flags/args are assembled.
   - `NativeCliAdapter.prepare_command()` is the dispatcher. Each supported CLI has an `is_foo_command()` predicate in `adapters.py` + `command_validation.py`, and its own branch for flag injection:
     - `claude`/`qwen` → append `--dangerously-skip-permissions` when `skip_permissions`.
     - `codex` → `--dangerously-bypass-approvals-and-sandbox`.
     - `gemini`/`kimi`/`opencode`/`hermes` → `--yolo`.
     - `hermes` → insert `chat` subcommand if command is bare `hermes`, add `--source tool`, pass prompt via `-q` (NOT `--continue`, which resumes an existing session).
     - `openclaw` → `--session <name>`, `--message <prompt>` (or `--local --session-id` when using the `agent` subcommand).
     - `kimi` / `nanobot` → `-w <cwd>` + `--print -p` / `-m`.
     - Generic fallback → `-p <prompt>`.
   - When adding a new CLI: extend both `command_validation.py` (predicate + validation) and `adapters.py` (branch in `prepare_command`).

### Prompt construction

`clawteam/spawn/prompt.py::build_agent_prompt()` assembles every spawned agent's system prompt: Identity → Mission (Auftragstaktik-style `intent` / `end_state` / `constraints`) → Workspace → Shared Memory → Boids rules (only when `team_size > 1`) → Task → Coordination Protocol → Metacognition block.

**Coordination knowledge (how to use the `clawteam` CLI) lives in the Skill file (`skills/openclaw/SKILL.md`), not here.** The prompt only tells the agent to call the CLI; the skill teaches it which commands exist. Do not duplicate command docs into `prompt.py`.

### Per-agent model resolution

`clawteam/model_resolution.py::resolve_model()` implements a **7-level priority chain**: CLI `--model` > agent-level `model` > agent `model_tier` (`strong`/`balanced`/`cheap`) > template `model_strategy = "auto"` (auto-assigns `strong` to anything containing `leader`/`reviewer`/`architect`/`manager`) > template `model` > config `default_model` > `None`. Tier table is `DEFAULT_TIERS` in the same file, overridable via config `model_tiers`.

### Templates

TOML files under `clawteam/templates/` (`hedge-fund.toml`, `code-review.toml`, `research-paper.toml`, `strategy-room.toml`) define team archetypes. `clawteam/templates/__init__.py::load_template()` searches `~/.clawteam/templates/` first (user overrides) then the built-in dir. User-supplied fields like `{goal}`, `{team_name}`, `{agent_name}` are substituted by `render_task()` — it uses a `_SafeDict` that preserves unknown placeholders rather than raising `KeyError`.

`DEFAULT_MAX_AGENTS = 4` (backed by arXiv:2512.08296). Exceeding this triggers a `check_agent_count()` warning unless `--force` is passed. Don't raise this ceiling casually.

### Filesystem layout under `~/.clawteam/`

```
teams/{team}/
  config.json        # TeamConfig — members, lead_agent_id, description
  inboxes/{agent}/   # FileTransport msg-*.json (atomic writes)
  events/            # event log (non-consuming history)
  peers/             # P2P peer discovery
  plans/             # plan approval docs
tasks/{team}/        # FileTaskStore task-*.json
costs/{team}/        # CostEvent records + rolling cache
sessions/{team}/     # per-agent session IDs (for --resume)
workspaces/{team}/   # workspace-registry.json (mapping of agent → worktree path + branch)
config.json          # global config, ALWAYS at ~/.clawteam/ (never affected by CLAWTEAM_DATA_DIR)
```

Config path is intentionally fixed (`clawteam/config.py::config_path()`): `CLAWTEAM_DATA_DIR` relocates team/task/inbox state but NOT global config.

## Cross-cutting conventions

### Path discipline (security-critical)

Every user-supplied name (team, agent, user, plan ID, inbox recipient…) must flow through `clawteam/paths.py`:
- `validate_identifier(value, kind)` — regex `^[A-Za-z0-9._-]+$`, rejects empty / `.` / `..`.
- `ensure_within_root(root, *parts)` — rejects any path that resolves outside `root`.

If you accept a name from the CLI, config, or a message and join it into a filesystem path, you MUST use these. Grep for existing uses in `clawteam/team/manager.py`, `clawteam/team/mailbox.py`, `clawteam/workspace/manager.py` for the pattern.

### Atomic writes + advisory locks

All shared JSON state is written via `clawteam/fileutil.py`:
- `atomic_write_text(path, content)` — mkstemp in target dir → fsync → `os.replace`. Windows retries on `PermissionError`.
- `file_locked(path)` — exclusive advisory lock on `<path>.lock` (fcntl on Unix, msvcrt on Windows). Use for read-modify-write sequences.

Never call `Path.rename()` on writeable state. Use `os.replace()` — `Path.rename()` fails on Windows when the destination exists. This fix was explicitly cherry-picked from upstream (#102).

### Windows portability

`clawteam/platform_compat.py` centralises cross-platform shims: `is_windows()`, `default_spawn_backend()`, `exclusive_file_lock()`, `pid_alive()`, `install_signal_handlers()`, `shell_join()`, `shell_quote()`. Go through these — don't add `import fcntl` at module top level outside this file.

The `tmux` backend is unavailable on Windows; `board attach` hard-requires it. `board serve` (web UI) is the cross-platform alternative.

### Pydantic model conventions

Most models (in `clawteam/team/models.py`, `clawteam/templates/__init__.py`, etc.) use `model_config = {"populate_by_name": True}` with `Field(alias="camelCaseOnDisk")`. Dumped JSON uses `by_alias=True, exclude_none=True` to match the teammate-tool spec. Serialising must preserve this — see `_dump()` in `cli/commands.py` and `MailboxManager.send()` for the canonical pattern.

### Environment variable layering

Config resolution order throughout the codebase is: env var → `~/.clawteam/config.json` → default. Canonical env vars: `CLAWTEAM_DATA_DIR`, `CLAWTEAM_USER`, `CLAWTEAM_TEAM_NAME`, `CLAWTEAM_TRANSPORT`, `CLAWTEAM_TASK_STORE`, `CLAWTEAM_WORKSPACE`, `CLAWTEAM_DEFAULT_BACKEND`, `CLAWTEAM_SKIP_PERMISSIONS`, `CLAWTEAM_DEFAULT_MODEL`. `AgentIdentity.from_env()` additionally honours legacy `OPENCLAW_*` / `CLAUDE_CODE_*` prefixes for back-compat.

### Ruff

`line-length = 100`, `select = ["E", "F", "I", "N", "W"]`, `ignore = ["E501"]`. Import sorting is enforced (`I001`). Run `ruff check --fix` to auto-sort before committing. CI fails on any ruff warning.

## Fork-specific gotchas

- **OpenClaw is the default.** The spawn command defaults to `["openclaw"]` and the adapter has openclaw-specific flag handling. Do not change this to `claude` — the upstream project does that, this fork deliberately does not.
- **OpenClaw exec-approval mode must be `allowlist`, not `full`**, otherwise spawned workers hang on interactive permission prompts. The README install step 5 configures this; `skills/openclaw/SKILL.md` references `$CLAWTEAM_BIN` so the allowlist can pin the exact path.
- **Hermes quirks**: workers use `hermes chat --yolo --source tool -q "<task>"`. The `chat` subcommand is auto-inserted only when the command is bare `hermes`. Never add `--continue` on spawn — it resumes existing sessions only. Hermes sometimes completes without running `clawteam inbox send`; if `inbox peek` is empty but the kanban shows COMPLETED, fall back to `tmux capture-pane -t clawteam-<team>:<window> -p -S -500`.
- **Hermes `--source tool` is a known upstream no-op on Hermes ≤ 0.8.0.** The adapter passes it correctly; Hermes's `run_agent.py:1057` / `:6600` short-circuit `self.platform or os.environ.get(...)` so the env var set by `cmd_chat` is never consulted. Spawned workers currently show up under `source=cli` in `hermes sessions list`. See `skills/hermes/SKILL.md § Known upstream issues` for the one-line fix. Do not "helpfully" add workarounds in the adapter — there's no env var or flag that can override Hermes's hardcoded `platform="cli"`, and the correct fix lives upstream.
- **Built-in templates default to openclaw.** To spawn Hermes workers from a template: `clawteam launch <template> --command hermes --force`. (On `spawn`, specify the backend before the Hermes command: `clawteam spawn tmux hermes --team ...` or `clawteam spawn subprocess hermes --team ...`.)
- **CHANGELOG** follows Keep a Changelog. Cherry-picks from upstream go under `### Fixed` with `(cherry-picked from upstream #XXX)` suffix, and new features reference the local `win4r/ClawTeam-OpenClaw` PR number.
