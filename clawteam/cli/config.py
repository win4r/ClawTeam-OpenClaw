"""Config commands for clawteam."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path
from typing import Optional

import typer
from rich.table import Table

from clawteam.cli._helpers import (
    _dump,
    _load_questionary,
    _output,
    _parse_key_value_items,
    _profile_wizard_style,
    _questionary_safe_ask,
    console,
)

config_app = typer.Typer(help="Configuration management")


@config_app.command("show")
def config_show():
    """Show all configuration settings and their sources."""
    from clawteam.config import get_effective, scalar_config_keys

    keys = scalar_config_keys()
    data = {}
    for k in keys:
        val, source = get_effective(k)
        data[k] = {"value": val, "source": source}

    def _human(d):
        table = Table(title="Configuration")
        table.add_column("Key", style="cyan")
        table.add_column("Value")
        table.add_column("Source", style="dim")
        for k in keys:
            v = d[k]["value"]
            table.add_row(k, str(v) if v != "" else "(empty)", d[k]["source"])
        console.print(table)

    _output(data, _human)


@config_app.command("set")
def config_set(
    key: str = typer.Argument(
        ...,
        help="Config key (e.g. data_dir, user, transport, workspace, default_backend, skip_permissions, gource_path)",
    ),
    value: str = typer.Argument(..., help="Config value"),
):
    """Persistently set a configuration value."""
    from clawteam.config import ClawTeamConfig, load_config, save_config, scalar_config_keys

    valid_keys = set(scalar_config_keys())
    if key not in valid_keys:
        console.print(f"[red]Invalid key '{key}'. Valid: {', '.join(sorted(valid_keys))}[/red]")
        raise typer.Exit(1)

    cfg = load_config()
    # Handle boolean fields (skip_permissions)
    field_info = ClawTeamConfig.model_fields[key]
    if field_info.annotation is bool:
        setattr(cfg, key, value.lower() in ("true", "1", "yes"))
    else:
        setattr(cfg, key, value)
    save_config(cfg)

    _output(
        {"status": "saved", "key": key, "value": value},
        lambda d: console.print(f"[green]OK[/green] {key} = {value}"),
    )


@config_app.command("get")
def config_get(
    key: str = typer.Argument(
        ...,
        help="Config key (e.g. data_dir, user, transport, workspace, default_backend, skip_permissions, gource_path)",
    ),
):
    """Get the effective value of a config key."""
    from clawteam.config import get_effective, scalar_config_keys

    valid_keys = set(scalar_config_keys())
    if key not in valid_keys:
        console.print(f"[red]Invalid key '{key}'. Valid: {', '.join(sorted(valid_keys))}[/red]")
        raise typer.Exit(1)

    val, source = get_effective(key)
    _output(
        {"key": key, "value": val, "source": source},
        lambda d: console.print(f"{key} = {val or '(empty)'}  [dim]({source})[/dim]"),
    )


preset_app = typer.Typer(help="Shared endpoint presets for generating client-scoped profiles")

profile_app = typer.Typer(help="Reusable agent runtime profiles")


@preset_app.command("list")
def preset_list():
    """List built-in and local presets."""
    from clawteam.spawn.presets import list_presets

    presets = list_presets()

    def _human(data):
        if not data:
            console.print("[dim]No presets configured.[/dim]")
            return
        table = Table(title="Presets")
        table.add_column("Name", style="cyan")
        table.add_column("Source")
        table.add_column("Clients")
        table.add_column("Auth Env")
        table.add_column("Base URL")
        table.add_column("Description")
        for name, item in sorted(data.items()):
            preset = item["preset"]
            table.add_row(
                name,
                item["source"],
                ", ".join(sorted(preset.get("client_overrides", {}).keys())) or "(none)",
                preset.get("auth_env", "") or "(unset)",
                preset.get("base_url", "") or "(default)",
                preset.get("description", "") or "",
            )
        console.print(table)

    _output(
        {
            name: {"preset": _dump(preset), "source": source}
            for name, (preset, source) in presets.items()
        },
        _human,
    )


@preset_app.command("show")
def preset_show(
    name: str = typer.Argument(..., help="Preset name"),
):
    """Show a single preset."""
    from clawteam.spawn.presets import load_preset

    try:
        preset, source = load_preset(name)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    data = {"preset": _dump(preset), "source": source}

    def _human(d):
        preset = d["preset"]
        console.print(f"[bold cyan]{name}[/bold cyan]  [dim]({d['source']})[/dim]")
        console.print(f"  Description: {preset.get('description') or ''}")
        console.print(f"  Auth env: {preset.get('auth_env') or '(unset)'}")
        console.print(f"  Base URL: {preset.get('base_url') or '(default)'}")
        if preset.get("env"):
            console.print("  Shared env:")
            for key, value in sorted(preset["env"].items()):
                console.print(f"    {key}={value}")
        if preset.get("client_overrides"):
            console.print("  Client overrides:")
            for client, profile in sorted(preset["client_overrides"].items()):
                command = " ".join(profile.get("command", [])) or profile.get("agent") or "(unset)"
                model = profile.get("model") or "(default)"
                base_url = profile.get("base_url") or preset.get("base_url") or "(default)"
                console.print(f"    {client}: {command} | model={model} | base_url={base_url}")

    _output(data, _human)


@preset_app.command("set")
def preset_set(
    name: str = typer.Argument(..., help="Preset name"),
    description: Optional[str] = typer.Option(None, "--description", help="Preset description"),
    auth_env: Optional[str] = typer.Option(None, "--auth-env", help="Default source env var holding provider auth"),
    base_url: Optional[str] = typer.Option(None, "--base-url", help="Default base URL shared by clients"),
    env: list[str] = typer.Option(None, "--env", help="Shared env assignment KEY=VALUE"),
):
    """Create or update a shared preset."""
    from clawteam.spawn.presets import editable_preset, save_preset

    preset = editable_preset(name)
    if description is not None:
        preset.description = description
    if auth_env is not None:
        preset.auth_env = auth_env
    if base_url is not None:
        preset.base_url = base_url
    if env:
        preset.env = _parse_key_value_items(env, label="env")

    save_preset(name, preset)
    _output(
        {"status": "saved", "preset": name},
        lambda d: console.print(f"[green]OK[/green] Saved preset '{name}'"),
    )


@preset_app.command("set-client")
def preset_set_client(
    preset_name: str = typer.Argument(..., help="Preset name"),
    client: str = typer.Argument(..., help="Client name (claude/codex/gemini/kimi)"),
    agent: Optional[str] = typer.Option(None, "--agent", help="Default client CLI name"),
    description: Optional[str] = typer.Option(None, "--description", help="Client-specific description"),
    command: Optional[str] = typer.Option(None, "--command", help="Exact command string"),
    model: Optional[str] = typer.Option(None, "--model", help="Default model"),
    base_url: Optional[str] = typer.Option(None, "--base-url", help="Client-specific base URL override"),
    base_url_env: Optional[str] = typer.Option(None, "--base-url-env", help="Destination env var for base URL injection"),
    api_key_env: Optional[str] = typer.Option(None, "--api-key-env", help="Client-specific source env var override"),
    api_key_target_env: Optional[str] = typer.Option(None, "--api-key-target-env", help="Destination env var receiving the resolved API key"),
    env: list[str] = typer.Option(None, "--env", help="Static env assignment KEY=VALUE"),
    env_map: list[str] = typer.Option(None, "--env-map", help="Runtime env mapping DEST=SOURCE_ENV"),
    arg: list[str] = typer.Option(None, "--arg", help="Extra argument appended to the agent command"),
):
    """Create or update a client override inside a preset."""
    from clawteam.config import AgentProfile
    from clawteam.spawn.presets import editable_preset, save_preset

    preset = editable_preset(preset_name)
    normalized_client = client.strip().lower().replace("claude-code", "claude").replace("codex-cli", "codex")
    existing = preset.client_overrides.get(normalized_client, AgentProfile())
    profile = existing.model_copy(deep=True)

    if agent is not None:
        profile.agent = agent
    if description is not None:
        profile.description = description
    if command is not None:
        profile.command = shlex.split(command)
    if model is not None:
        profile.model = model
    if base_url is not None:
        profile.base_url = base_url
    if base_url_env is not None:
        profile.base_url_env = base_url_env
    if api_key_env is not None:
        profile.api_key_env = api_key_env
    if api_key_target_env is not None:
        profile.api_key_target_env = api_key_target_env
    if env:
        profile.env = _parse_key_value_items(env, label="env")
    if env_map:
        profile.env_map = _parse_key_value_items(env_map, label="env-map")
    if arg:
        profile.args = list(arg)
    if not profile.command and not profile.agent:
        profile.agent = normalized_client

    preset.client_overrides[normalized_client] = profile
    save_preset(preset_name, preset)
    _output(
        {"status": "saved", "preset": preset_name, "client": normalized_client},
        lambda d: console.print(
            f"[green]OK[/green] Saved client override '{normalized_client}' in preset '{preset_name}'"
        ),
    )


@preset_app.command("copy")
def preset_copy(
    source: str = typer.Argument(..., help="Source preset"),
    target: str = typer.Argument(..., help="Target local preset name"),
):
    """Copy a built-in or local preset into a new local preset."""
    from clawteam.spawn.presets import copy_preset, list_presets

    if target in list_presets():
        console.print(f"[red]Preset '{target}' already exists.[/red]")
        raise typer.Exit(1)

    try:
        copy_preset(source, target)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    _output(
        {"status": "copied", "source": source, "target": target},
        lambda d: console.print(
            f"[green]OK[/green] Copied preset '{source}' to '{target}'"
        ),
    )


@preset_app.command("remove")
def preset_remove(
    name: str = typer.Argument(..., help="Local preset name"),
):
    """Remove a locally configured preset."""
    from clawteam.spawn.presets import remove_preset

    if not remove_preset(name):
        console.print(
            f"[red]Local preset '{name}' not found.[/red] [dim](Built-ins cannot be removed.)[/dim]"
        )
        raise typer.Exit(1)

    _output(
        {"status": "removed", "preset": name},
        lambda d: console.print(f"[green]OK[/green] Removed preset '{name}'"),
    )


@preset_app.command("remove-client")
def preset_remove_client(
    preset_name: str = typer.Argument(..., help="Preset name"),
    client: str = typer.Argument(..., help="Client name"),
):
    """Remove a single client override from a local preset."""
    from clawteam.spawn.presets import remove_preset_client

    if not remove_preset_client(preset_name, client):
        console.print(
            f"[red]Client override '{client}' not found in local preset '{preset_name}'.[/red]"
        )
        raise typer.Exit(1)

    _output(
        {"status": "removed", "preset": preset_name, "client": client},
        lambda d: console.print(
            f"[green]OK[/green] Removed client override '{client}' from preset '{preset_name}'"
        ),
    )


@preset_app.command("generate-profile")
def preset_generate_profile(
    preset_name: str = typer.Argument(..., help="Preset name"),
    client: str = typer.Argument(..., help="Client name"),
    name: Optional[str] = typer.Option(None, "--name", help="Target profile name (default: <client>-<preset>)"),
    force: bool = typer.Option(False, "--force", help="Overwrite existing profile"),
):
    """Generate a single profile from a preset."""
    from clawteam.spawn.presets import generate_profile_from_preset
    from clawteam.spawn.profiles import list_profiles, save_profile

    try:
        profile_name, profile = generate_profile_from_preset(preset_name, client, name=name)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    if profile_name in list_profiles() and not force:
        console.print(
            f"[red]Profile '{profile_name}' already exists. Use --force to overwrite.[/red]"
        )
        raise typer.Exit(1)

    save_profile(profile_name, profile)
    _output(
        {"status": "saved", "profile": profile_name, "preset": preset_name, "client": client},
        lambda d: console.print(
            f"[green]OK[/green] Generated profile '{profile_name}' from preset '{preset_name}' for client '{client}'"
        ),
    )


@preset_app.command("bootstrap")
def preset_bootstrap(
    preset_name: str = typer.Argument(..., help="Preset name"),
    client: list[str] = typer.Option(None, "--client", help="Client to generate (repeatable). Defaults to all clients defined by the preset"),
    force: bool = typer.Option(False, "--force", help="Overwrite existing profiles"),
):
    """Generate one profile per client from a preset."""
    from clawteam.spawn.presets import generate_profile_from_preset, load_preset, preset_clients
    from clawteam.spawn.profiles import list_profiles, save_profile

    try:
        preset, _ = load_preset(preset_name)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    clients = client or preset_clients(preset)
    if not clients:
        console.print(f"[red]Preset '{preset_name}' does not define any clients.[/red]")
        raise typer.Exit(1)

    existing_profiles = list_profiles()
    generated: list[str] = []
    skipped: list[str] = []

    for item in clients:
        try:
            profile_name, profile = generate_profile_from_preset(preset_name, item)
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
            raise typer.Exit(1)
        if profile_name in existing_profiles and not force:
            skipped.append(profile_name)
            continue
        save_profile(profile_name, profile)
        generated.append(profile_name)

    data = {
        "preset": preset_name,
        "generated": generated,
        "skipped": skipped,
    }

    def _human(d):
        if d["generated"]:
            console.print(
                f"[green]OK[/green] Generated profiles from '{preset_name}': {', '.join(d['generated'])}"
            )
        if d["skipped"]:
            console.print(
                f"[yellow]Skipped existing profiles[/yellow]: {', '.join(d['skipped'])}"
            )

    _output(data, _human)


@profile_app.command("list")
def profile_list():
    """List configured agent profiles."""
    from clawteam.spawn.profiles import list_profiles

    profiles = list_profiles()

    def _human(data):
        if not data:
            console.print("[dim]No profiles configured.[/dim]")
            return
        table = Table(title="Profiles")
        table.add_column("Name", style="cyan")
        table.add_column("Agent")
        table.add_column("Model")
        table.add_column("Base URL")
        table.add_column("Description")
        for name, profile in sorted(data.items()):
            agent = profile.get("agent") or (" ".join(profile.get("command", [])) if profile.get("command") else "")
            table.add_row(
                name,
                agent or "(unset)",
                profile.get("model", "") or "(default)",
                profile.get("base_url", "") or "(default)",
                profile.get("description", "") or "",
            )
        console.print(table)

    _output({name: _dump(profile) for name, profile in profiles.items()}, _human)


@profile_app.command("show")
def profile_show(
    name: str = typer.Argument(..., help="Profile name"),
):
    """Show a single profile."""
    from clawteam.spawn.profiles import load_profile

    try:
        profile = load_profile(name)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    data = _dump(profile)

    def _human(d):
        console.print(f"[bold cyan]{name}[/bold cyan]")
        console.print(f"  Agent: {d.get('agent') or '(unset)'}")
        console.print(f"  Command: {' '.join(d.get('command', [])) or '(unset)'}")
        console.print(f"  Model: {d.get('model') or '(default)'}")
        console.print(f"  Base URL: {d.get('base_url') or '(default)'}")
        if d.get("base_url_env"):
            console.print(f"  Base URL target env: {d['base_url_env']}")
        console.print(f"  API key env: {d.get('api_key_env') or '(unset)'}")
        if d.get("api_key_target_env"):
            console.print(f"  API key target env: {d['api_key_target_env']}")
        console.print(f"  Description: {d.get('description') or ''}")
        if d.get("args"):
            console.print(f"  Extra args: {' '.join(d['args'])}")
        if d.get("env"):
            console.print("  Env:")
            for key, value in sorted(d["env"].items()):
                console.print(f"    {key}={value}")
        if d.get("env_map"):
            console.print("  Env map:")
            for key, value in sorted(d["env_map"].items()):
                console.print(f"    {key} <- ${value}")

    _output(data, _human)


@profile_app.command("set")
def profile_set(
    name: str = typer.Argument(..., help="Profile name"),
    agent: Optional[str] = typer.Option(None, "--agent", help="Default agent CLI name (claude/codex/gemini/kimi/nanobot)"),
    description: Optional[str] = typer.Option(None, "--description", help="Profile description"),
    command: Optional[str] = typer.Option(None, "--command", help="Exact command string (e.g. 'kimi --config-file ~/.kimi/config.toml')"),
    model: Optional[str] = typer.Option(None, "--model", help="Default model"),
    base_url: Optional[str] = typer.Option(None, "--base-url", help="Provider base URL"),
    base_url_env: Optional[str] = typer.Option(None, "--base-url-env", help="Destination env var for base URL injection"),
    api_key_env: Optional[str] = typer.Option(None, "--api-key-env", help="Source env var holding the API key"),
    api_key_target_env: Optional[str] = typer.Option(None, "--api-key-target-env", help="Destination env var receiving the resolved API key"),
    env: list[str] = typer.Option(None, "--env", help="Static env assignment KEY=VALUE"),
    env_map: list[str] = typer.Option(None, "--env-map", help="Runtime env mapping DEST=SOURCE_ENV"),
    arg: list[str] = typer.Option(None, "--arg", help="Extra argument appended to the agent command"),
):
    """Create or update a profile."""
    from clawteam.config import AgentProfile
    from clawteam.spawn.profiles import list_profiles, save_profile

    existing = list_profiles().get(name, AgentProfile())
    profile = existing.model_copy(deep=True)

    if agent is not None:
        profile.agent = agent
    if description is not None:
        profile.description = description
    if command is not None:
        profile.command = shlex.split(command)
    if model is not None:
        profile.model = model
    if base_url is not None:
        profile.base_url = base_url
    if base_url_env is not None:
        profile.base_url_env = base_url_env
    if api_key_env is not None:
        profile.api_key_env = api_key_env
    if api_key_target_env is not None:
        profile.api_key_target_env = api_key_target_env
    if env:
        profile.env = _parse_key_value_items(env, label="env")
    if env_map:
        profile.env_map = _parse_key_value_items(env_map, label="env-map")
    if arg:
        profile.args = list(arg)

    if not profile.command and not profile.agent:
        console.print("[red]Profile must define either --agent or --command.[/red]")
        raise typer.Exit(1)

    save_profile(name, profile)
    _output(
        {"status": "saved", "profile": name},
        lambda d: console.print(f"[green]OK[/green] Saved profile '{name}'"),
    )


@profile_app.command("remove")
def profile_remove(
    name: str = typer.Argument(..., help="Profile name"),
):
    """Remove a profile."""
    from clawteam.spawn.profiles import remove_profile

    if not remove_profile(name):
        console.print(f"[red]Unknown profile '{name}'[/red]")
        raise typer.Exit(1)

    _output(
        {"status": "removed", "profile": name},
        lambda d: console.print(f"[green]OK[/green] Removed profile '{name}'"),
    )


@profile_app.command("test")
def profile_test(
    name: str = typer.Argument(..., help="Profile name"),
    prompt: str = typer.Option("Reply with exactly CLAWTEAM_PROFILE_OK", "--prompt", help="Smoke test prompt"),
    cwd: Optional[str] = typer.Option(None, "--cwd", help="Working directory for the test run"),
):
    """Run a non-interactive smoke test for a profile."""
    from clawteam.spawn.adapters import NativeCliAdapter
    from clawteam.spawn.command_validation import validate_spawn_command
    from clawteam.spawn.profiles import apply_profile, load_profile

    try:
        profile = load_profile(name)
        command, env, agent = apply_profile(profile)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    adapter = NativeCliAdapter()
    prepared = adapter.prepare_command(
        command,
        prompt=prompt,
        cwd=cwd,
        skip_permissions=True,
        interactive=False,
    )
    command_error = validate_spawn_command(prepared.normalized_command, path=os.environ.get("PATH"), cwd=cwd)
    if command_error:
        console.print(f"[red]{command_error}[/red]")
        raise typer.Exit(1)

    run_env = os.environ.copy()
    run_env.update(env)
    result = subprocess.run(
        prepared.final_command,
        cwd=cwd,
        env=run_env,
        capture_output=True,
        text=True,
    )
    data = {
        "profile": name,
        "agent": agent,
        "command": prepared.final_command,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }

    def _human(d):
        console.print(f"Profile: [cyan]{d['profile']}[/cyan]")
        console.print(f"Agent: [cyan]{d['agent']}[/cyan]")
        console.print(f"Command: {' '.join(shlex.quote(part) for part in d['command'])}")
        console.print(f"Return code: {d['returncode']}")
        if d["stdout"]:
            console.print("\n[bold]stdout[/bold]")
            console.print(d["stdout"].rstrip())
        if d["stderr"]:
            console.print("\n[bold]stderr[/bold]")
            console.print(d["stderr"].rstrip())

    _output(data, _human)
    if result.returncode != 0:
        raise typer.Exit(1)


@profile_app.command("wizard")
def profile_wizard():
    """Launch an interactive TUI for creating profiles from providers or manually."""
    from clawteam.config import AgentProfile
    from clawteam.spawn.presets import generate_profile_from_preset, list_presets, preset_clients
    from clawteam.spawn.profiles import list_profiles, save_profile

    questionary = _load_questionary()
    style = _profile_wizard_style(questionary)
    clients = [
        questionary.Choice("Claude Code", "claude"),
        questionary.Choice("Codex", "codex"),
        questionary.Choice("Gemini CLI", "gemini"),
        questionary.Choice("Kimi CLI", "kimi"),
        questionary.Choice("Nanobot", "nanobot"),
    ]
    preset_catalog = list_presets()

    console.print("[bold cyan]ClawTeam Profile Wizard[/bold cyan]")
    setup_mode = _questionary_safe_ask(
        questionary.select(
            "Choose a setup mode",
            choices=[
                questionary.Choice("Quick setup", "quick"),
                questionary.Choice("Advanced setup", "advanced"),
            ],
            style=style,
        )
    )
    client = _questionary_safe_ask(
        questionary.select(
            "Choose a client",
            choices=clients,
            style=style,
        )
    )

    provider_choices = []
    for preset_name, (preset, source) in sorted(preset_catalog.items()):
        if client in preset_clients(preset):
            description = preset.description or "Recommended provider setup"
            provider_choices.append(
                questionary.Choice(
                    title=f"{preset_name}  [{source}]  {description}",
                    value=preset_name,
                )
            )
    provider_choices.append(
        questionary.Choice("Custom endpoint / manual configuration", "__custom__")
    )
    provider_name = _questionary_safe_ask(
        questionary.select(
            "Choose a provider template",
            choices=provider_choices,
            style=style,
        )
    )

    if provider_name == "__custom__":
        suggested_name = f"{client}-custom"
        profile = AgentProfile(agent=client, description=f"Custom {client} profile")
    else:
        suggested_name = f"{client}-{provider_name}"
        _, profile = generate_profile_from_preset(provider_name, client, name=suggested_name)

    profile_name = _questionary_safe_ask(
        questionary.text(
            "Profile name",
            default=suggested_name,
            style=style,
        )
    )

    profile = profile.model_copy(deep=True)
    quick_known_provider = setup_mode == "quick" and provider_name != "__custom__"
    edit_recommended_settings = setup_mode == "advanced" or provider_name == "__custom__"

    if quick_known_provider:
        console.print(
            f"[dim]Using recommended settings from provider template '{provider_name}'.[/dim]"
        )
        edit_recommended_settings = _questionary_safe_ask(
            questionary.confirm(
                "Edit recommended model / endpoint / auth settings?",
                default=False,
                style=style,
            )
        )

    if not quick_known_provider or edit_recommended_settings:
        profile.description = _questionary_safe_ask(
            questionary.text(
                "Description",
                default=profile.description,
                style=style,
            )
        )
        profile.model = _questionary_safe_ask(
            questionary.text(
                "Default model",
                default=profile.model,
                style=style,
            )
        )
        profile.base_url = _questionary_safe_ask(
            questionary.text(
                "Base URL",
                default=profile.base_url,
                style=style,
            )
        )
        profile.api_key_env = _questionary_safe_ask(
            questionary.text(
                "API key env var name",
                default=profile.api_key_env,
                style=style,
            )
        )

    configure_advanced = setup_mode == "advanced"
    if setup_mode == "quick":
        configure_advanced = _questionary_safe_ask(
            questionary.confirm(
                "Open advanced options (command, args, env overrides)?",
                default=False,
                style=style,
            )
        )

    if configure_advanced:
        profile.agent = _questionary_safe_ask(
            questionary.text(
                "Agent CLI name",
                default=profile.agent or (Path(profile.command[0]).name if profile.command else ""),
                style=style,
            )
        )
        command_default = " ".join(profile.command)
        command_raw = _questionary_safe_ask(
            questionary.text(
                "Exact command override (optional)",
                default=command_default,
                style=style,
                instruction="Leave empty to use the agent CLI name.",
            )
        )
        profile.command = shlex.split(command_raw) if command_raw.strip() else []
        args_raw = _questionary_safe_ask(
            questionary.text(
                "Extra args (optional)",
                default=" ".join(profile.args),
                style=style,
                instruction="Example: --config-file ~/.kimi/config.toml",
            )
        )
        profile.args = shlex.split(args_raw) if args_raw.strip() else []

        env_assignments = dict(profile.env)
        while _questionary_safe_ask(
            questionary.confirm("Add a static env assignment?", default=False, style=style)
        ):
            key = _questionary_safe_ask(questionary.text("Env key", style=style))
            value = _questionary_safe_ask(questionary.text("Env value", style=style))
            env_assignments[key] = value
        profile.env = env_assignments

        env_map_assignments = dict(profile.env_map)
        while _questionary_safe_ask(
            questionary.confirm("Add an env mapping from an existing shell variable?", default=False, style=style)
        ):
            dest = _questionary_safe_ask(
                questionary.text("Destination env key", style=style)
            )
            source = _questionary_safe_ask(
                questionary.text("Source shell env var", style=style)
            )
            env_map_assignments[dest] = source
        profile.env_map = env_map_assignments

    if not profile.command and not profile.agent:
        console.print("[red]Profile must define either an agent CLI name or a command.[/red]")
        raise typer.Exit(1)

    console.print("\n[bold]Profile preview[/bold]")
    console.print(f"  Name: {profile_name}")
    console.print(f"  Agent: {profile.agent or '(unset)'}")
    console.print(f"  Command: {' '.join(profile.command) or '(derived from agent)'}")
    console.print(f"  Model: {profile.model or '(default)'}")
    console.print(f"  Base URL: {profile.base_url or '(default)'}")
    console.print(f"  API key env: {profile.api_key_env or '(unset)'}")
    if profile.args:
        console.print(f"  Extra args: {' '.join(profile.args)}")
    if profile.env:
        console.print("  Static env:")
        for key, value in sorted(profile.env.items()):
            console.print(f"    {key}={value}")
    if profile.env_map:
        console.print("  Env map:")
        for key, value in sorted(profile.env_map.items()):
            console.print(f"    {key} <- ${value}")

    existing_profiles = list_profiles()
    if profile_name in existing_profiles:
        overwrite = _questionary_safe_ask(
            questionary.confirm(
                f"Profile '{profile_name}' already exists. Overwrite it?",
                default=False,
                style=style,
            )
        )
        if not overwrite:
            console.print("[yellow]Wizard cancelled without saving.[/yellow]")
            raise typer.Exit(1)

    save_profile(profile_name, profile)
    console.print(f"[green]OK[/green] Saved profile '{profile_name}'")

    normalized_client = (profile.agent or "").lower()
    if normalized_client in {"claude", "claude-code"}:
        if _questionary_safe_ask(
            questionary.confirm(
                "Run `clawteam profile doctor claude` now to suppress first-run onboarding?",
                default=True,
                style=style,
            )
        ):
            profile_doctor("claude")

    if _questionary_safe_ask(
        questionary.confirm("Run a smoke test for this profile now?", default=False, style=style)
    ):
        test_cwd = _questionary_safe_ask(
            questionary.text(
                "Working directory for the smoke test (optional)",
                default="",
                style=style,
            )
        )
        profile_test(profile_name, cwd=test_cwd or None)


@profile_app.command("doctor")
def profile_doctor(
    client: str = typer.Argument(..., help="Client to repair (currently: claude)"),
):
    """Repair client-specific local runtime state for profiles."""
    normalized = client.strip().lower()
    if normalized not in {"claude", "claude-code"}:
        console.print(
            f"[red]Unsupported profile doctor target '{client}'. Supported: claude[/red]"
        )
        raise typer.Exit(1)

    claude_state_path = Path.home() / ".claude.json"
    before_exists = claude_state_path.exists()
    data: dict[str, object]
    if before_exists:
        try:
            data = json.loads(claude_state_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}
    else:
        data = {}

    data["hasCompletedOnboarding"] = True
    claude_state_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    result = {
        "client": "claude",
        "path": str(claude_state_path),
        "created": not before_exists,
        "hasCompletedOnboarding": True,
    }

    def _human(d):
        action = "Created" if d["created"] else "Updated"
        console.print(
            f"[green]OK[/green] {action} Claude state at '{d['path']}' "
            "with hasCompletedOnboarding=true"
        )

    _output(result, _human)


@config_app.command("health")
def config_health():
    """Health check for the data directory (shared directory diagnostics)."""
    import os
    import time as _time

    from clawteam.config import get_effective
    from clawteam.team.manager import TeamManager
    from clawteam.team.models import get_data_dir

    checks = {}

    # Data directory
    data_dir = get_data_dir()
    val, source = get_effective("data_dir")
    checks["data_dir"] = str(data_dir)
    checks["data_dir_source"] = source

    # Exists
    checks["exists"] = data_dir.exists()

    # Writable
    try:
        test_file = data_dir / ".health-check"
        start = _time.monotonic()
        test_file.write_text("ok", encoding="utf-8")
        content = test_file.read_text(encoding="utf-8")
        elapsed = (_time.monotonic() - start) * 1000
        test_file.unlink()
        checks["writable"] = content == "ok"
        checks["latency_ms"] = round(elapsed, 2)
    except Exception as e:
        checks["writable"] = False
        checks["latency_ms"] = -1
        checks["write_error"] = str(e)

    # Mount point check
    try:
        checks["is_mount"] = os.path.ismount(str(data_dir))
    except Exception:
        checks["is_mount"] = False

    # Teams count
    try:
        teams = TeamManager.discover_teams()
        checks["teams_count"] = len(teams)
    except Exception:
        checks["teams_count"] = 0

    # User
    user_val, user_source = get_effective("user")
    checks["user"] = user_val
    checks["user_source"] = user_source

    def _human(d):
        console.print(f"\nData Directory: [cyan]{d['data_dir']}[/cyan]  [dim]({d['data_dir_source']})[/dim]")
        console.print(f"  Exists:     {'[green]yes[/green]' if d['exists'] else '[red]no[/red]'}")
        console.print(f"  Writable:   {'[green]yes[/green]' if d['writable'] else '[red]no[/red]'}")
        if d['latency_ms'] >= 0:
            color = "green" if d['latency_ms'] < 50 else "yellow" if d['latency_ms'] < 200 else "red"
            console.print(f"  Latency:    [{color}]{d['latency_ms']:.1f} ms[/{color}]")
        console.print(f"  Mount point: {'[yellow]yes (remote/shared)[/yellow]' if d['is_mount'] else '[dim]no (local)[/dim]'}")
        console.print(f"  Teams:      {d['teams_count']}")
        console.print(f"  User:       {d['user'] or '(not set)'}  [dim]({d['user_source']})[/dim]")

    _output(checks, _human)


