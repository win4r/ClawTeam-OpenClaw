# Contributing to ClawTeam-OpenClaw

Thanks for your interest in contributing! This guide helps you get started quickly.

## Setup

```bash
git clone https://github.com/win4r/ClawTeam-OpenClaw.git
cd ClawTeam-OpenClaw
pip install -e ".[dev]"
```

## Development workflow

1. **Create a branch** from `main`:
   ```bash
   git checkout -b feat/your-feature main
   ```

2. **Make your changes** — keep PRs focused on one thing.

3. **Run checks** before committing:
   ```bash
   ruff check clawteam/ tests/
   pytest tests/
   ```

4. **Submit a PR** against `main`. Fill in the PR template.

## Code style

- **Linter**: [ruff](https://docs.astral.sh/ruff/) — `ruff check` must pass with zero warnings.
- **Line length**: 100 characters (configured in `pyproject.toml`).
- **Imports**: sorted by ruff (`I` rules). Run `ruff check --fix` to auto-sort.
- **Python**: 3.10+ — use `from __future__ import annotations` if needed.

## PR guidelines

- **One PR = one feature/fix.** Don't bundle unrelated changes.
- **Add tests** for new functionality. We have 450+ tests — keep the bar high.
- **Keep diffs small.** PRs over 500 lines are hard to review. If your feature is large, split it into sequential PRs.
- **Update CHANGELOG.md** under `[Unreleased]` for user-facing changes.

## Testing

```bash
pytest tests/                    # full suite
pytest tests/test_foo.py -v     # single file
pytest -k "test_name"           # single test
```

## Project structure

```
clawteam/
├── cli/           # CLI commands (typer)
├── spawn/         # Agent spawn backends (tmux, subprocess)
├── team/          # Team lifecycle, mailbox, tasks
├── templates/     # Team templates
├── transport/     # File-based message transport
└── workspace/     # Workspace overlay management
```

## Need help?

Open an issue or check existing ones — we're happy to guide first-time contributors.
