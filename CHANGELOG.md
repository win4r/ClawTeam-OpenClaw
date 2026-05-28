# Changelog

All notable changes to ClawTeam-OpenClaw are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [PEP 440](https://peps.python.org/pep-0440/) with `+openclaw` local identifier.

## [Unreleased]

### Added

- **Upstream sync 2026-05-28** — merged 197 upstream commits, including PR #154 (session capture/resume + leader watcher + runtime injection), keepalive subprocess worker recovery, generalized runtime injection for interactive backends, MCP support, harness/conductor/exit_journal scaffolding, multi-backend runtime resolution (`_resolve_runtime_backend`), `scalar_config_keys`, `format_timestamp`, gource board, profiles/hooks/plugins, and CJK README (`README_KR.md`).
- **`is_pi_command` predicate** integrated into spawn validation and runtime injection paths.
- **Skill injection via `--skill`** (claude-only `--append-system-prompt`).
- **tmux env-source temp file** (avoids ~16k cmd-length limit on heavy env payloads).
- **`is_leader` `remain-on-exit`** for leader panes.

### Changed

- `runtime inject/watch` now resolves per-agent backend via registry instead of hard-wiring `TmuxBackend()`; gracefully rejects `subprocess` agents from `runtime watch`.
- `spawn` command no longer silently swaps unrecognized backend positionals into the command position (upstream behaviour); misordered args now surface as `Unknown spawn backend: X` with `_spawn_backend_hint` instructions.
- Qwen now uses `--yolo` (consistent with Gemini/Kimi/Opencode/Hermes) instead of `--dangerously-skip-permissions`.
- Gemini tmux interactive flag changed from `-p` to `-i`.

### Fork-specific protections retained

- Default agent remains `openclaw` (not `claude`).
- OpenClaw allowlist hint + `_ensure_worker_workspace` + `propagate_openclaw_gateway_token` (PR #51).
- Hermes `chat` insert + `--source tool` + `-q` prompt path.
- `lifecycle on-exit` via `trap EXIT` (PR #60 auto-respawn) — kept in addition to upstream's optional `is_leader` `remain-on-exit`.
- `subprocess_wrapper` (PR #60) — fork wraps spawned subprocesses for auto-respawn instead of upstream's `build_keepalive_shell_command`.
- `platform_compat` + `normalize_backend_name` (Windows portability).

### Known follow-ups (xfail)

5 spawn-backend tests are marked `pytest.mark.xfail(strict=False)` because upstream PR #154's `build_keepalive_shell_command` / tmux `set-hook pane-exited` / docker-wrapped-nanobot path / `--append-system-prompt` ordering are not yet ported to fork's `subprocess_wrapper` / `trap EXIT` / manual-flag path. Tracked for a follow-up port. None of these block bot operation.

## [0.3.0+openclaw1] - 2026-04-04

### Added

- **Per-agent model resolution** with 7-level priority chain: CLI > agent model > agent tier > template strategy > template model > config default > None ([#53](https://github.com/win4r/ClawTeam-OpenClaw/pull/53))
- **Cost Dashboard MVP** — real-time token/cost aggregation by agent, model, and task dimensions with `clawteam board cost` command ([#52](https://github.com/win4r/ClawTeam-OpenClaw/pull/52))
- **Circuit Breaker** — healthy → degraded → open tri-state with half-open probing for agent failure isolation ([#52](https://github.com/win4r/ClawTeam-OpenClaw/pull/52))
- **Retry with exponential backoff** — `RetryConfig` + `spawn_with_retry()` for resilient agent spawning ([#52](https://github.com/win4r/ClawTeam-OpenClaw/pull/52))
- **Idempotency keys** for `create()` and `send()` — deduplication for production reliability ([#52](https://github.com/win4r/ClawTeam-OpenClaw/pull/52))
- **Max 4 workers warning** — backed by Google/MIT empirical research (arXiv:2512.08296) ([#50](https://github.com/win4r/ClawTeam-OpenClaw/pull/50))
- **Intent-based prompts** — military C2 Auftragstaktik-inspired `intent` / `end_state` / `constraints` fields in AgentDef ([#50](https://github.com/win4r/ClawTeam-OpenClaw/pull/50))
- **Boids emergence rules** — Reynolds 1986 flocking rules adapted for LLM agent coordination ([#50](https://github.com/win4r/ClawTeam-OpenClaw/pull/50))
- **Metacognitive self-assessment** — confidence tagging in agent outputs ([#50](https://github.com/win4r/ClawTeam-OpenClaw/pull/50))
- **Runtime live injection** — `runtime inject/state/watch` CLI commands for tmux inbox messaging at runtime (cherry-picked from upstream [#85](https://github.com/HKUDS/ClawTeam/pull/85)) ([#54](https://github.com/win4r/ClawTeam-OpenClaw/pull/54))
- **OpenClaw 4.2 compatibility** — workspace isolation for workers, allowlist path hints, `--agent` flag detection ([#56](https://github.com/win4r/ClawTeam-OpenClaw/pull/56))

### Fixed

- Waiter zero-tasks edge case (cherry-picked from upstream [#101](https://github.com/HKUDS/ClawTeam/pull/101)) ([#54](https://github.com/win4r/ClawTeam-OpenClaw/pull/54))
- Windows `Path.rename()` → `os.replace()` in 5 files (cherry-picked from upstream [#102](https://github.com/HKUDS/ClawTeam/pull/102)) ([#54](https://github.com/win4r/ClawTeam-OpenClaw/pull/54))
- TOCTOU race condition in idempotency check ([#52](https://github.com/win4r/ClawTeam-OpenClaw/pull/52))
- `cost_rate()` timezone fragility ([#52](https://github.com/win4r/ClawTeam-OpenClaw/pull/52))
- Import sorting (ruff I001) ([#45](https://github.com/win4r/ClawTeam-OpenClaw/pull/45))
- Spawn registry cleanup after agent exit ([#41](https://github.com/win4r/ClawTeam-OpenClaw/pull/41))

### Changed

- Project URLs now point to `win4r/ClawTeam-OpenClaw` instead of upstream
- Version bump from 0.2.0 to 0.3.0

## [0.2.0+openclaw1] - 2026-03-29

### Added

- OpenClaw as default agent (first-class support)
- Kimi / Qwen / OpenCode CLI support
- Subproject workspace overlay ([#27](https://github.com/win4r/ClawTeam-OpenClaw/pull/27))
- Zombie agent detection ([#36](https://github.com/win4r/ClawTeam-OpenClaw/pull/36))
- Shared memory scope ([#26](https://github.com/win4r/ClawTeam-OpenClaw/pull/26))
- Agent parameter handling for openclaw_agent ([#6](https://github.com/win4r/ClawTeam-OpenClaw/pull/6))
- 11-language README
- GitHub Actions CI
- PEP 440 versioning

### Fixed

- Trust prompt timeout ([#21](https://github.com/win4r/ClawTeam-OpenClaw/pull/21))
- Spawn registry cleanup after exit ([#41](https://github.com/win4r/ClawTeam-OpenClaw/pull/41))
- Skill context cleanup ([#44](https://github.com/win4r/ClawTeam-OpenClaw/pull/44))
