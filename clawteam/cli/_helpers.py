"""Shared state and helpers for clawteam CLI commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from clawteam import __version__

app = typer.Typer(
    name="clawteam",
    help="Framework-agnostic multi-agent coordination CLI",
    no_args_is_help=True,
)
console = Console()


# ---------------------------------------------------------------------------
# Global options via callback
# ---------------------------------------------------------------------------

_json_output: bool = False
_data_dir: str | None = None


def _version_callback(value: bool):
    if value:
        console.print(f"clawteam v{__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        None, "--version", "-v", callback=_version_callback, is_eager=True,
        help="Show version and exit.",
    ),
    json_out: bool = typer.Option(
        False, "--json", help="Output JSON instead of human-readable text.",
    ),
    data_dir: Optional[str] = typer.Option(
        None, "--data-dir", help="Override data directory (default: ~/.clawteam).",
    ),
    transport: Optional[str] = typer.Option(
        None, "--transport", help="Transport backend: file or p2p.",
    ),
):
    """clawteam - Framework-agnostic multi-agent coordination CLI."""
    global _json_output, _data_dir
    _json_output = json_out
    if data_dir:
        import os
        os.environ["CLAWTEAM_DATA_DIR"] = data_dir
        _data_dir = data_dir
    if transport:
        import os
        os.environ["CLAWTEAM_TRANSPORT"] = transport


def _dump(model) -> dict:
    """Dump a pydantic model to dict with by_alias and exclude_none."""
    return json.loads(model.model_dump_json(by_alias=True, exclude_none=True))


def _output(data: dict | list, human_fn=None):
    """Output data as JSON or human-readable."""
    if _json_output:
        print(json.dumps(data, indent=2, ensure_ascii=False))
    elif human_fn:
        human_fn(data)
    else:
        print(json.dumps(data, indent=2, ensure_ascii=False))


def _spawn_backend_hint(backend: str | None, team: str | None) -> str:
    """Return a helpful hint when spawn positional args are misordered."""
    if not backend or team:
        return ""
    return (
        " Hint: the first positional argument to `clawteam spawn` is the backend "
        "(`tmux` or `subprocess`), not the team name. Use `--team <name>` to set "
        "the team explicitly."
    )


def _load_skill_content(name: str) -> str | None:
    """Load skill content from ~/.claude/skills.

    Supports both directory format (skills/<name>/SKILL.md) and
    single-file format (skills/<name>.md).
    """
    skills_root = Path.home() / ".claude" / "skills"
    skill_dir = skills_root / name
    if skill_dir.is_dir():
        skill_file = skill_dir / "SKILL.md"
        if not skill_file.exists():
            markdown_files = sorted(skill_dir.glob("*.md"))
            skill_file = markdown_files[0] if markdown_files else None
        if skill_file and skill_file.exists():
            return skill_file.read_text(encoding="utf-8")

    single_file = skills_root / f"{name}.md"
    if single_file.exists():
        return single_file.read_text(encoding="utf-8")
    return None


def _parse_key_value_items(items: list[str], *, label: str) -> dict[str, str]:
    """Parse repeated KEY=VALUE CLI options into a dict."""
    parsed: dict[str, str] = {}
    for item in items:
        if "=" not in item:
            console.print(f"[red]Invalid {label} '{item}'. Expected KEY=VALUE.[/red]")
            raise typer.Exit(1)
        key, value = item.split("=", 1)
        if not key:
            console.print(f"[red]Invalid {label} '{item}'. Key cannot be empty.[/red]")
            raise typer.Exit(1)
        parsed[key] = value
    return parsed


def _load_questionary():
    """Import questionary lazily so non-TUI flows do not depend on it at runtime."""
    try:
        import questionary
    except ImportError as exc:  # pragma: no cover - import error path is trivial
        console.print(
            "[red]Questionary is not installed. Reinstall ClawTeam with its default "
            "dependencies to use `clawteam profile wizard`.[/red]"
        )
        raise typer.Exit(1) from exc
    return questionary


def _profile_wizard_style(questionary):
    return questionary.Style(
        [
            ("qmark", "fg:#22c55e bold"),
            ("question", "bold"),
            ("answer", "fg:#38bdf8 bold"),
            ("pointer", "fg:#f59e0b bold"),
            ("highlighted", "fg:#f59e0b bold"),
            ("selected", "fg:#22c55e"),
            ("instruction", "fg:#94a3b8 italic"),
        ]
    )


def _questionary_safe_ask(control):
    answer = control.ask()
    if answer is None:
        console.print("[yellow]Cancelled.[/yellow]")
        raise typer.Exit(1)
    return answer


# ============================================================================
# Config Commands
# ============================================================================
