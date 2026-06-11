from __future__ import annotations

import json
import logging
logger = logging.getLogger(__name__)
import re
import random
import hashlib
import os
import subprocess
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover - Python builds without tzdata
    ZoneInfo = None

import httpx
try:
    import yaml
except Exception:  # pragma: no cover - optional dependency
    yaml = None

try:
    from .gym_attendance import record_arrival as _gym_record_arrival
    from .gym_attendance import record_departure as _gym_record_departure
    from .gym_attendance import monthly_report as _gym_monthly_report
    from .gym_attendance import workout_task_for_day as _gym_workout_task_for_day
except Exception:  # pragma: no cover - gym attendance is best-effort
    _gym_record_arrival = None  # type: ignore[assignment]
    _gym_record_departure = None  # type: ignore[assignment]
    _gym_monthly_report = None  # type: ignore[assignment]
    _gym_workout_task_for_day = None  # type: ignore[assignment]

from .runtime_context_tools import runtime_context_budget_audit as _runtime_context_budget_audit
from .runtime_context_tools import runtime_context_contributors_report as _runtime_context_contributors_report
from .runtime_context_tools import runtime_memory_tier as _runtime_memory_tier
from .runtime_context_tools import runtime_no_agent_cron_plan as _runtime_no_agent_cron_plan
from .runtime_context_tools import runtime_profile_prune_plan as _runtime_profile_prune_plan
from .runtime_context_tools import runtime_secret_inventory as _runtime_secret_inventory
from .runtime_context_tools import runtime_tool_router_simulate as _runtime_tool_router_simulate
from .runtime_context_tools import runtime_tool_router_status as _runtime_tool_router_status
from .promptfoo_suite import export_promptfoo_suite as _export_promptfoo_suite

HERMES_HOME = Path(os.getenv("HERMES_HOME", str(Path.home() / ".hermes")))
APPROVALS_PATH = HERMES_HOME / "personal_ops_approvals.json"
EVENTS_PATH = HERMES_HOME / "personal_ops_events.jsonl"
FOCUS_GUARD_STATE_PATH = HERMES_HOME / "focus_guard_state.json"
FOCUS_GUARD_EVENT_LOG_PATH = HERMES_HOME / "focus_guard_events.jsonl"
ADAPTIVE_COMPANION_STATE_PATH = HERMES_HOME / "adaptive_companion_state.json"
ADAPTIVE_COMPANION_EVENTS_PATH = HERMES_HOME / "adaptive_companion_events.jsonl"
HERMES_CONFIG_PATH = HERMES_HOME / "config.yaml"
LIVE_WATCH_STATE_PATH = HERMES_HOME / "live_watch_state.json"
EVENT_ROUTER_STATE_PATH = HERMES_HOME / "event_router_state.json"
PRESENCE_STATE_PATH = HERMES_HOME / "presence_state.json"
NUDGE_BUDGET_STATE_PATH = HERMES_HOME / "nudge_budget_state.json"
MOOD_ROUTER_STATE_PATH = HERMES_HOME / "mood_router_state.json"
VOICE_CAPTURE_LOG_PATH = HERMES_HOME / "voice_capture_log.jsonl"
WORK_LOG_PATH = HERMES_HOME / "work_log.jsonl"
SELF_IMPROVE_STATE_PATH = HERMES_HOME / "self_improve_state.json"
SELF_IMPROVE_PIPELINES_PATH = HERMES_HOME / "self_improve_pipelines.json"
OPERATOR_STATE_PATH = HERMES_HOME / "operator_state.json"
OPERATOR_BRIEF_LOG_PATH = HERMES_HOME / "operator_briefs.jsonl"
TODOIST_REPAIR_QUEUE_PATH = HERMES_HOME / "todoist_repair_queue.json"
OPERATOR_MEMORY_PATH = HERMES_HOME / "operator_memory.json"
TODOIST_RULES_PATH = HERMES_HOME / "todoist_rules.json"
SELF_IMPROVE_PROPOSALS_PATH = HERMES_HOME / "self_improve_proposals.json"
TRACE_LOG_PATH = HERMES_HOME / "runtime_traces.jsonl"
PROMPTFOO_EVALS_PATH = HERMES_HOME / "promptfoo_eval_cases.json"
PROMPTFOO_CONFIG_PATH = HERMES_HOME / "promptfoo_config.json"
CALENDAR_STATE_PATH = HERMES_HOME / "calendar_state.json"
ORCHESTRATION_JOBS_DB_PATH = HERMES_HOME / "orchestration_jobs.sqlite3"
CRON_JOBS_PATH = HERMES_HOME / "cron" / "jobs.json"
RUNTIME_SERVICE_NAME = "hermes-gateway.service"
ADAPTIVE_COMPANION_REPEAT_COOLDOWN_MINUTES = 90
ADAPTIVE_COMPANION_SAME_TASK_COOLDOWN_MINUTES = 360
ADAPTIVE_COMPANION_DAILY_TASK_PATTERN_LIMIT = 2
ADAPTIVE_COMPANION_DAILY_TASK_LIMIT = 3
ADAPTIVE_COMPANION_REASON_ANCHOR_TTL_MINUTES = 20
PRESENCE_SIGNAL_TTL_MINUTES = 45
PRESENCE_PROACTIVE_CONFIDENCE_MINIMUM = 0.70
NUDGE_BUDGET_DAILY_PRESSURE_LIMIT = 5
QUIET_HOURS_START = 7
QUIET_HOURS_END = 22
HERMES_LOCAL_TIMEZONE = os.getenv("HERMES_LOCAL_TIMEZONE", "America/Edmonton")

TODOIST_BASE = "https://api.todoist.com/api/v1"
CLICKUP_BASE = "https://api.clickup.com/api/v2"
TWILIO_BASE = "https://api.twilio.com/2010-04-01/Accounts"


def _tool_result(data=None, **kwargs) -> str:
    if data is not None:
        return json.dumps(data, ensure_ascii=False)
    return json.dumps(kwargs, ensure_ascii=False)


def _tool_error(message, **extra) -> str:
    result = {"error": str(message)}
    if extra:
        result.update(extra)
    return json.dumps(result, ensure_ascii=False)


def _now() -> int:
    return int(time.time())


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _append_event(event_type: str, data: Dict[str, Any]) -> None:
    EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {"ts": _now(), "type": event_type, **data}
    with EVENTS_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _append_jsonl(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(data, ensure_ascii=False) + "\n")


def _read_jsonl_recent(path: Path, *, limit: int = 100) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []

    rows: List[Dict[str, Any]] = []
    for line in lines[-limit:]:
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except Exception:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _read_jsonl_all(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    rows: List[Dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except Exception:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _minimal_yaml_load(text: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    stack: List[tuple[int, Dict[str, Any]]] = [(-1, result)]
    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if value:
            parent[key] = value
        else:
            child: Dict[str, Any] = {}
            parent[key] = child
            stack.append((indent, child))
    return result


def _minimal_yaml_dump(data: Dict[str, Any], *, indent: int = 0) -> str:
    lines: List[str] = []
    pad = " " * indent
    for key, value in data.items():
        if isinstance(value, dict):
            lines.append(f"{pad}{key}:")
            lines.append(_minimal_yaml_dump(value, indent=indent + 2).rstrip())
        else:
            lines.append(f"{pad}{key}: {value}")
    return "\n".join(line for line in lines if line) + "\n"


_FOCUS_GUARD_AVOIDANCE_TERMS = (
    "avoid",
    "avoidance",
    "optimiz",
    "productivity app",
    "perfect productivity",
    "system",
    "research",
    "endlessly",
)
_FOCUS_GUARD_SUSPICIOUS_TERMS = (
    "organize",
    "notes",
    "prep",
    "prepare",
    "softer substitute",
    "could be useful",
)

_FOCUS_GUARD_SEMANTIC_AVOIDANCE_GROUPS = {
    "avoidance": [r"\bavoid(ance|s|ed|ing)?\b"],
    "system_optimizing": [
        r"\boptimi[sz](e|es|ed|ing|ation|ations)?\b",
        r"\bsetup\b", r"\bset\s+up\b",
        r"\bworkflow(s)?\b",
        r"\bdashboard(s)?\b",
        r"\btool(s)?\b",
        r"\bconfig(ure|uration|uring|ures|ed)?\b",
        r"\brefactor(s|ed|ing)?\b",
        r"\brebuild(s|ing)?\b",
        r"\bdotfile(s)?\b",
        r"\bclean(ing)?\s+repo\b"
    ],
    "meta_productivity": [
        r"\bproductivity\s+app(s)?\b",
        r"\bperfect\s+productivity\b",
        r"\bnotetaking\b", r"\bnote-taking\b",
        r"\btime\s+track(ing|er|ers)?\b",
        r"\borgani[sz]e\s+task(s)?\b",
        r"\bcolor\s+code(d|s)?\b",
        r"\btodoist\s+rule(s)?\b"
    ],
    "endless_research": [
        r"\bresearch(es|ed|ing)?\b",
        r"\bendless(ly)?\b",
        r"\bexplore\s+framework(s)?\b",
        r"\bread\s+blog(s)?\b",
        r"\bwatch\s+tutorial(s)?\b",
        r"\blookup\s+option(s)?\b",
        r"\bgather\s+reference(s)?\b"
    ],
    "procrastination_rituals": [
        r"\bprepare\s+desktop\b",
        r"\bclean\s+workspace\b",
        r"\bbackup\s+file(s)?\b",
        r"\breorgani[sz]e\s+folder(s)?\b",
        r"\bupdate\s+package(s)?\b"
    ]
}

_FOCUS_GUARD_SEMANTIC_SUSPICIOUS_GROUPS = {
    "organizing": [r"\borgani[sz](e|es|ed|ing|ation|ations)?\b"],
    "notes": [r"\bnote(s)?\b"],
    "preparation": [
        r"\bprep(s|ped|ping)?\b",
        r"\bprepare(s|d|ing)?\b",
        r"\bpreparatory\b"
    ],
    "substitutes": [
        r"\bsofter\s+substitute\b",
        r"\bcould\s+be\s+useful\b"
    ]
}

_ADAPTIVE_COMPANION_META_DEFLECTION_TERMS = (
    "you're just ai",
    "you are just ai",
    "you're fake",
    "you are fake",
    "i programmed you",
)
_ADAPTIVE_COMPANION_SUSPICIOUS_TERMS = (
    "research",
    "optimize",
    "setup",
    "system",
    "workflow",
    "dashboard",
    "new app",
    "tool",
    "compare",
    "explore",
)
_ADAPTIVE_COMPANION_FALSE_PREP_TERMS = (
    "set up",
    "setup",
    "dashboard",
    "workflow",
    "system",
    "organize",
    "prepare",
    "prep",
    "before starting",
)
_ADAPTIVE_COMPANION_COMFORT_TERMS = (
    "easier",
    "easy",
    "cleaner",
    "warm up",
    "admin first",
    "quick win",
    "later",
)
