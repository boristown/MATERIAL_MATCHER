import pytest

from material_matcher.plugins import PluginRegistry


def test_register_and_create_plugin() -> None:
    registry = PluginRegistry()
    registry.register("matcher", "exact", lambda config: {"kind": "exact", **config})

    instance = registry.create("matcher", "exact", {"case_sensitive": False})
    assert instance["kind"] == "exact"
    assert instance["case_sensitive"] is False


def test_duplicate_plugin_is_rejected() -> None:
    registry = PluginRegistry()
    registry.register("matcher", "exact", lambda config: config)
    with pytest.raises(ValueError, match="already registered"):
        registry.register("matcher", "exact", lambda config: config)


def test_unknown_plugin_is_rejected() -> None:
    registry = PluginRegistry()
    with pytest.raises(KeyError, match="unknown plugin"):
        registry.create("matcher", "missing", {})
