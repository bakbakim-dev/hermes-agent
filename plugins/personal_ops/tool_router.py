"""Intent-aware tool routing for Hermes personal operations.

This module deliberately defaults to enforcement for high-risk tools. It still
records deterministic allow/deny recommendations for observability, and
``HERMES_TOOL_ROUTER_ENFORCE=false`` can be used for a temporary audit-only
session when debugging the router itself.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Set


LOW_RISK_DEFAULT_TOOLS: Set[str] = {
    "personal_runtime",
    "personal_todoist",
    "personal_focus_guard",
    "personal_security",
    "memory_search",
    "memory_list",
}

TOOL_CLASSES: Dict[str, str] = {
    "personal_todoist": "todoist_read_or_draft_write",
    "personal_runtime": "runtime_read_or_diagnostic",
    "personal_focus_guard": "personal_ops_read",
    "personal_security": "approval_and_policy",
    "terminal": "shell_command",
    "execute_command": "shell_command",
    "run_shell_command": "shell_command",
    "browser": "browser_logged_in",
    "browser_navigate": "browser_logged_in",
    "browser_click": "browser_logged_in",
    "browser_type": "browser_logged_in",
}

INTENT_TOOLSETS: Dict[str, Set[str]] = {
    "personal_ops": {"personal_todoist", "personal_runtime", "personal_focus_guard", "personal_security"},
    "todoist": {"personal_todoist", "personal_runtime", "personal_security"},
    "memory": {"personal_runtime", "memory_search", "memory_list"},
    "coding": {"personal_runtime"},
    "browser": {"personal_runtime", "browser", "browser_navigate", "browser_click", "browser_type"},
    "unknown": LOW_RISK_DEFAULT_TOOLS,
}

HIGH_RISK_CLASSES = {
    "shell_command",
    "browser_logged_in",
    "external_write",
    "financial",
    "public_post",
    "code_patch",
}


@dataclass
class ToolRouteDecision:
    tool_name: str
    intent: str
    tool_class: str
    allowed: bool
    approval_required: bool
    enforce_mode: bool
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "intent": self.intent,
            "tool_class": self.tool_class,
            "allowed": self.allowed,
            "approval_required": self.approval_required,
            "enforce_mode": self.enforce_mode,
            "reasons": list(self.reasons),
        }


def router_enforce_default() -> bool:
    """Return whether the tool router should block by default.

    Hermes is now an approval-gated personal operator; high-risk tools should be
    blocked unless the user deliberately opts into audit-only mode.
    """
    raw = os.environ.get("HERMES_TOOL_ROUTER_ENFORCE")
    if raw is None or not raw.strip():
        return True
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def classify_intent(text: str) -> str:
    lowered = (text or "").lower()
    if any(word in lowered for word in ("todoist", "task", "today", "overdue", "repair", "recurring")):
        return "todoist"
    if any(word in lowered for word in ("memory", "remember", "forget", "preference", "rule")):
        return "memory"
    if any(word in lowered for word in ("code", "test", "repo", "patch", "commit", "bug", "gateway")):
        return "coding"
    if any(word in lowered for word in ("browser", "website", "hevy", "calendar", "chrome", "login")):
        return "browser"
    if any(word in lowered for word in ("workout", "gym", "home", "family", "nudge", "brief")):
        return "personal_ops"
    return "unknown"


def tool_class_for(tool_name: str) -> str:
    if tool_name in TOOL_CLASSES:
        return TOOL_CLASSES[tool_name]
    lowered = tool_name.lower()
    if any(word in lowered for word in ("terminal", "shell", "command", "exec")):
        return "shell_command"
    if "browser" in lowered or "playwright" in lowered:
        return "browser_logged_in"
    if any(word in lowered for word in ("post", "send", "publish")):
        return "external_write"
    return "unclassified"


def route_tool_call(
    *,
    tool_name: str,
    intent_text: str = "",
    explicit_intent: str = "",
    enforce: bool | None = None,
) -> ToolRouteDecision:
    intent = explicit_intent or classify_intent(intent_text)
    allowed_tools = INTENT_TOOLSETS.get(intent, LOW_RISK_DEFAULT_TOOLS)
    tool_class = tool_class_for(tool_name)
    enforce_mode = router_enforce_default() if enforce is None else bool(enforce)

    reasons: List[str] = []
    allowed = tool_name in allowed_tools or tool_class not in HIGH_RISK_CLASSES
    approval_required = tool_class in HIGH_RISK_CLASSES

    if tool_name not in allowed_tools:
        reasons.append(f"Tool is not in the narrow allow-list for intent '{intent}'.")
    if approval_required:
        reasons.append(f"Tool class '{tool_class}' is high risk and should be approval-gated.")
    if not enforce_mode:
        reasons.append("Router is in audit mode; decision is logged but not blocked.")

    return ToolRouteDecision(
        tool_name=tool_name,
        intent=intent,
        tool_class=tool_class,
        allowed=allowed,
        approval_required=approval_required,
        enforce_mode=enforce_mode,
        reasons=reasons,
    )


def append_tool_route_event(hermes_home: Path, decision: ToolRouteDecision, args: Mapping[str, Any] | None = None) -> None:
    event_path = Path(hermes_home) / "tool_router_events.jsonl"
    event_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "type": "tool_route_decision",
        "created_at": _now(),
        "decision": decision.to_dict(),
        "arg_keys": sorted(str(key) for key in (args or {}).keys()),
    }
    with open(event_path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def pre_tool_call_router(
    *,
    tool_name: str,
    args: Mapping[str, Any] | None = None,
    session_id: str = "",
    **_: Any,
) -> Dict[str, Any] | None:
    from hermes_cli.config import get_hermes_home

    intent_text = ""
    if isinstance(args, Mapping):
        intent_text = " ".join(
            str(args.get(key) or "")
            for key in ("intent", "request", "query", "title", "action")
        )
    decision = route_tool_call(tool_name=tool_name, intent_text=intent_text)
    try:
        append_tool_route_event(get_hermes_home(), decision, args)
    except Exception:
        pass
    if decision.enforce_mode and not decision.allowed:
        return {
            "action": "block",
            "message": (
                f"Tool '{tool_name}' was blocked by the Hermes tool router. "
                + " ".join(decision.reasons)
            ),
        }
    return None


def summarize_tool_router_events(*, hermes_home: Path, limit: int = 200) -> Dict[str, Any]:
    path = Path(hermes_home) / "tool_router_events.jsonl"
    events: List[Dict[str, Any]] = []
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    by_class: Dict[str, int] = {}
    high_risk = 0
    for event in events:
        decision = event.get("decision") or {}
        cls = str(decision.get("tool_class") or "unknown")
        by_class[cls] = by_class.get(cls, 0) + 1
        if decision.get("approval_required"):
            high_risk += 1
    return {
        "success": True,
        "action": "tool_router_status",
        "event_count": len(events),
        "high_risk_seen": high_risk,
        "by_class": by_class,
        "enforce_mode": router_enforce_default(),
        "event_path": str(path),
    }


def simulate_tool_route(tool_name: str, *, intent_text: str = "", intent: str = "") -> Dict[str, Any]:
    return {
        "success": True,
        "action": "tool_router_simulate",
        "decision": route_tool_call(
            tool_name=tool_name,
            intent_text=intent_text,
            explicit_intent=intent,
            enforce=False,
        ).to_dict(),
    }
