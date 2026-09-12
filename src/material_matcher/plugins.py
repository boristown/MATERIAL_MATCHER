from __future__ import annotations

from collections.abc import Callable
from typing import Any


PluginFactory = Callable[[dict[str, Any]], Any]


class PluginRegistry:
    """Runtime plugin registry keyed by kind and plugin id.

    The core engine depends only on this registry. Customer names and customer
    field names must never be used for dispatch.
    """

    def __init__(self) -> None:
        self._factories: dict[str, dict[str, PluginFactory]] = {}

    def register(self, kind: str, plugin_id: str, factory: PluginFactory) -> None:
        kind_map = self._factories.setdefault(kind, {})
        if plugin_id in kind_map:
            raise ValueError(f"plugin already registered: {kind}/{plugin_id}")
        kind_map[plugin_id] = factory

    def create(self, kind: str, plugin_id: str, config: dict[str, Any] | None = None) -> Any:
        try:
            factory = self._factories[kind][plugin_id]
        except KeyError as exc:
            raise KeyError(f"unknown plugin: {kind}/{plugin_id}") from exc
        return factory(config or {})

    def list_plugins(self) -> dict[str, list[str]]:
        return {kind: sorted(entries) for kind, entries in sorted(self._factories.items())}


registry = PluginRegistry()
