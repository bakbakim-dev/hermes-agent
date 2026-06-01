from __future__ import annotations

import pytest


def test_manifest_parses_and_exposes_plugin_permissions(tmp_path):
    from hermes_cli.plugins import PluginManager

    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir()
    manifest_path = plugin_dir / "plugin.yaml"
    manifest_path.write_text(
        "name: sample\n"
        "version: 1.0.0\n"
        "permissions:\n"
        "  - tools\n"
        "  - network\n",
        encoding="utf-8",
    )

    manifest = PluginManager()._parse_manifest(manifest_path, plugin_dir, "user", "")

    assert manifest is not None
    assert manifest.permissions == ["tools", "network"]


def test_manifest_rejects_unknown_plugin_permissions(tmp_path):
    from hermes_cli.plugins import PluginManager

    plugin_dir = tmp_path / "plugin"
    plugin_dir.mkdir()
    manifest_path = plugin_dir / "plugin.yaml"
    manifest_path.write_text(
        "name: sample\n"
        "permissions:\n"
        "  - root_everything\n",
        encoding="utf-8",
    )

    assert PluginManager()._parse_manifest(manifest_path, plugin_dir, "user", "") is None


def test_untrusted_plugin_tool_registration_requires_tools_permission():
    from hermes_cli.plugins import PluginContext, PluginManager, PluginManifest

    manifest = PluginManifest(name="sample", source="user", permissions=[])
    ctx = PluginContext(manifest, PluginManager())

    with pytest.raises(PermissionError, match="tools"):
        ctx.register_tool(
            name="sample_tool",
            toolset="sample",
            schema={"type": "object", "properties": {}},
            handler=lambda args: "ok",
        )
