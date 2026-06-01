"""Runtime adapters for context hygiene, secrets, memory tiering, and tool routing.

These helpers used to live in ``temp_personal_ops_tools.py``. Keeping them here
makes the temporary runtime dispatcher thinner while preserving the same public
``personal_runtime`` actions.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

try:
    import yaml
except Exception:  # pragma: no cover - optional dependency
    yaml = None


HERMES_HOME = Path(os.getenv("HERMES_HOME", str(Path.home() / ".hermes")))
HERMES_CONFIG_PATH = HERMES_HOME / "config.yaml"


def _read_yaml(path: Path, default: Any) -> Any:
    if yaml is None:
        return default
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _runtime_default_repo_path() -> Path:
    configured = os.getenv("HERMES_AGENT_REPO_PATH", "").strip()
    if configured:
        return Path(configured).expanduser()
    common = Path("/home/ubuntu/hermes-agent")
    if common.exists():
        return common
    return Path.cwd()


def runtime_context_budget_audit(args: Dict[str, Any]) -> Dict[str, Any]:
    from plugins.personal_ops.context_budget import audit_context_budget

    repo_path = Path(args.get("repo_path") or _runtime_default_repo_path())
    return audit_context_budget(
        hermes_home=HERMES_HOME,
        repo_path=repo_path,
        write_event=bool(args.get("write_event", True)),
    )


def runtime_profile_prune_plan(args: Dict[str, Any]) -> Dict[str, Any]:
    from plugins.personal_ops.context_budget import prune_profile_recommendations

    data = _read_yaml(HERMES_CONFIG_PATH, {}) or {}
    keep_plugins = args.get("keep_plugins")
    if isinstance(keep_plugins, str):
        keep_plugins = [item.strip() for item in keep_plugins.split(",") if item.strip()]
    if not isinstance(keep_plugins, list):
        keep_plugins = None
    return prune_profile_recommendations(config_data=data, keep_plugins=keep_plugins)


def runtime_context_contributors_report(args: Dict[str, Any]) -> Dict[str, Any]:
    from plugins.personal_ops.context_budget import summarize_turn_context_contributors

    return summarize_turn_context_contributors(
        hermes_home=HERMES_HOME,
        limit=int(args.get("limit") or 200),
    )


def runtime_secret_inventory(args: Dict[str, Any]) -> Dict[str, Any]:
    from plugins.personal_ops.context_budget import build_secret_inventory

    repo_path = Path(args.get("repo_path") or _runtime_default_repo_path())
    return build_secret_inventory(hermes_home=HERMES_HOME, repo_path=repo_path)


def runtime_no_agent_cron_plan(args: Dict[str, Any]) -> Dict[str, Any]:
    from plugins.personal_ops.context_budget import build_no_agent_cron_plan

    del args
    return build_no_agent_cron_plan()


def runtime_tool_router_status(args: Dict[str, Any]) -> Dict[str, Any]:
    from plugins.personal_ops.tool_router import summarize_tool_router_events

    return summarize_tool_router_events(
        hermes_home=HERMES_HOME,
        limit=int(args.get("limit") or 200),
    )


def runtime_tool_router_simulate(args: Dict[str, Any]) -> Dict[str, Any]:
    from plugins.personal_ops.tool_router import simulate_tool_route

    tool_name = str(args.get("tool_name") or args.get("tool") or "").strip()
    if not tool_name:
        raise ValueError("tool_name is required")
    return simulate_tool_route(
        tool_name,
        intent_text=str(args.get("request") or args.get("intent") or args.get("title") or ""),
        intent=str(args.get("explicit_intent") or ""),
    )


def runtime_memory_tier(args: Dict[str, Any]) -> Dict[str, Any]:
    from plugins.personal_ops.context_budget import classify_memory_destination

    content = str(args.get("content") or args.get("text") or "").strip()
    memory_type = str(args.get("memory_type") or args.get("type") or "note").strip()
    if not content:
        raise ValueError("content is required")
    result = classify_memory_destination(content, memory_type=memory_type)
    return {"success": True, "action": "memory_tier", "content": content, "memory_type": memory_type, **result}
