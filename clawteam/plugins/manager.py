"""Plugin discovery and lifecycle management."""

from __future__ import annotations

import importlib
import json
import sys
from typing import Any

from clawteam.plugins.base import HarnessPlugin


class PluginManager:
    """Discovers, loads, and manages ClawTeam plugins."""

    def __init__(self) -> None:
        self._loaded: dict[str, HarnessPlugin] = {}

    # ── Discovery ─────────────────────────────────────────────────────

    def discover(self) -> dict[str, dict[str, Any]]:
        """Discover all available plugins from entry points, config, and local dirs.

        Returns {name: {version, description, source}} without loading.
        """
        found: dict[str, dict[str, Any]] = {}

        # 1. Entry points
        try:
            from importlib.metadata import entry_points
            group = entry_points(group="clawteam.plugins")
            for ep in group:
                found[ep.name] = {
                    "version": "?",
                    "description": f"entry_point: {ep.value}",
                    "source": "entry_point",
                }
        except Exception:
            pass

        # 2. Config plugins
        try:
            from clawteam.config import load_config
            cfg = load_config()
            for mod_path in cfg.plugins:
                name = mod_path.rsplit(".", 1)[-1]
                found[name] = {
                    "version": "?",
                    "description": f"config: {mod_path}",
                    "source": "config",
                }
        except Exception:
            pass

        # 3. Local plugin directories
        try:
            from clawteam.team.models import get_data_dir
            plugins_dir = get_data_dir() / "plugins"
            if plugins_dir.is_dir():
                for d in plugins_dir.iterdir():
                    manifest = d / "plugin.json"
                    if manifest.is_file():
                        data = json.loads(manifest.read_text(encoding="utf-8"))
                        found[data.get("name", d.name)] = {
                            "version": data.get("version", "?"),
                            "description": data.get("description", ""),
                            "source": "local",
                            "path": str(d),
                        }
        except Exception:
            pass

        # Include already-loaded
        for name, plugin in self._loaded.items():
            if name not in found:
                found[name] = {
                    "version": plugin.version,
                    "description": plugin.description,
                    "source": "loaded",
                }

        return found

    def get_info(self, name: str) -> dict[str, Any] | None:
        """Get detailed info for a named plugin."""
        all_plugins = self.discover()
        return all_plugins.get(name)

    # ── Loading ───────────────────────────────────────────────────────

    def load_from_module(self, module_path: str) -> HarnessPlugin | None:
        """Load a plugin from a dotted module path.

        The module should have a top-level class inheriting HarnessPlugin.
        """
        try:
            mod = importlib.import_module(module_path)
        except Exception as exc:
            print(f"[clawteam] Failed to import plugin {module_path}: {exc}", file=sys.stderr)
            return None

        for attr_name in dir(mod):
            obj = getattr(mod, attr_name)
            if (
                isinstance(obj, type)
                and issubclass(obj, HarnessPlugin)
                and obj is not HarnessPlugin
            ):
                return self._instantiate_and_register(obj)
        return None

    def load_from_entry_point(self, name: str) -> HarnessPlugin | None:
        """Load a plugin by entry_point name."""
        try:
            from importlib.metadata import entry_points
            group = entry_points(group="clawteam.plugins")
            for ep in group:
                if ep.name == name:
                    cls = ep.load()
                    if isinstance(cls, type) and issubclass(cls, HarnessPlugin):
                        return self._instantiate_and_register(cls)
        except Exception:
            pass
        return None

    def load_all_from_config(self) -> int:
        """Load all plugins listed in config. Returns count loaded."""
        try:
            from clawteam.config import load_config
            cfg = load_config()
        except Exception:
            return 0
        count = 0
        for mod_path in cfg.plugins:
            if self.load_from_module(mod_path) is not None:
                count += 1
        return count

    def _instantiate_and_register(self, cls: type) -> HarnessPlugin:
        plugin = cls()
        ctx = self._build_context()
        plugin.on_register(ctx)
        self._loaded[plugin.name] = plugin
        return plugin

    def _build_context(self):
        """Build a HarnessContext for plugin registration."""
        from clawteam.events.global_bus import get_event_bus
        from clawteam.harness.context import HarnessContext
        return HarnessContext(bus=get_event_bus())

    # ── Introspection ─────────────────────────────────────────────────

    def loaded_plugins(self) -> dict[str, HarnessPlugin]:
        return dict(self._loaded)

    def unload(self, name: str) -> bool:
        plugin = self._loaded.pop(name, None)
        if plugin:
            plugin.on_unregister()
            return True
        return False
