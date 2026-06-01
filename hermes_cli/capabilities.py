from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional


def _truth(value: bool) -> str:
    return "Yes" if value else "No"


def _plugin_default_status(info: Dict[str, Any]) -> str:
    if info.get("source") == "bundled" and info.get("kind") in {"backend", "platform", "model-provider"}:
        return "default-on"
    if info.get("kind") == "exclusive":
        return "provider-selected"
    return "opt-in"


def _requirements(info: Dict[str, Any]) -> List[str]:
    raw = info.get("requires_env") or info.get("requirements") or []
    result: List[str] = []
    for item in raw:
        if isinstance(item, str):
            result.append(item)
        elif isinstance(item, dict):
            name = item.get("name") or item.get("env") or item.get("var")
            if name:
                result.append(str(name))
    return sorted(set(result))


def build_capability_matrix(
    *,
    plugin_infos: Optional[Iterable[Dict[str, Any]]] = None,
    toolsets: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    if plugin_infos is None:
        from hermes_cli.plugins import get_plugin_manager

        manager = get_plugin_manager()
        manager.discover_and_load()
        plugin_infos = manager.list_plugins()
    if toolsets is None:
        from tools.registry import registry

        toolsets = registry.get_available_toolsets()

    rows: List[Dict[str, Any]] = []
    for info in plugin_infos:
        requirements = _requirements(info)
        key = str(info.get("key") or info.get("name") or "")
        rows.append(
            {
                "id": f"plugin:{key}",
                "capability": key,
                "type": f"plugin/{info.get('kind', 'standalone')}",
                "implemented": True,
                "enabled": bool(info.get("enabled")),
                "default_status": _plugin_default_status(info),
                "requires_credentials": bool(requirements),
                "requirements": requirements,
                "notes": str(info.get("error") or ""),
            }
        )

    for name, info in sorted((toolsets or {}).items()):
        requirements = _requirements(info)
        rows.append(
            {
                "id": f"toolset:{name}",
                "capability": name,
                "type": "toolset",
                "implemented": bool(info.get("tools")),
                "enabled": bool(info.get("available")),
                "default_status": "runtime-gated",
                "requires_credentials": bool(requirements),
                "requirements": requirements,
                "notes": f"{len(info.get('tools') or [])} tool(s)",
            }
        )
    return sorted(rows, key=lambda row: row["id"])


def render_capability_markdown(rows: Iterable[Dict[str, Any]]) -> str:
    lines = [
        "| Capability | Type | Implemented | Enabled | Default | Credentials | Notes |",
        "|---|---:|---:|---:|---|---|---|",
    ]
    for row in rows:
        requirements = ", ".join(row.get("requirements") or [])
        credentials = requirements if row.get("requires_credentials") else "No"
        lines.append(
            "| {capability} | {type} | {implemented} | {enabled} | {default} | {credentials} | {notes} |".format(
                capability=row.get("capability", ""),
                type=row.get("type", ""),
                implemented=_truth(bool(row.get("implemented"))),
                enabled=_truth(bool(row.get("enabled"))),
                default=row.get("default_status", ""),
                credentials=credentials,
                notes=str(row.get("notes") or "").replace("\n", " "),
            )
        )
    return "\n".join(lines)
