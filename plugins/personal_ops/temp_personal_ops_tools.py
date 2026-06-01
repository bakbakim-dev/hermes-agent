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


def _focus_guard_due_sort_key(task: Dict[str, Any]) -> tuple[int, str]:
    due = task.get("due")
    if not isinstance(due, dict):
        return (1, "")

    due_value = str(due.get("datetime") or due.get("date") or "").strip()
    if not due_value:
        return (1, "")
    return (0, due_value)


def _focus_guard_pick_most_important_task(tasks: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not tasks:
        return None

    return min(
        tasks,
        key=lambda task: (
            -int(task.get("priority") or 1),
            _focus_guard_due_sort_key(task),
        ),
    )


def _focus_guard_classify_task(task: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    # We only match semantic patterns against the task title (content).
    # Using the description causes false positives when the description contains instructions
    # like "avoid swinging" or "avoid soreness" or "machine setup".
    text = str(task.get("content") or "").strip().lower()

    task_title = str(task.get("content") or "").strip()

    # Load rules state from todoist_rules.json
    rules_state = _todoist_rules_read_state()

    # 1. Check direct task metadata overrides
    task_key = str(task.get("task_key") or _operator_task_id(task) or task_title.lower().strip())
    metadata = dict(rules_state.get("task_metadata") or {}).get(task_key) or {}
    task_type_override = str(metadata.get("task_type") or "").strip().lower()
    if task_type_override == "avoidance":
        return {
            "label": "avoidance",
            "should_postpone": True,
            "reason": "Task explicitly marked as avoidance in custom rules metadata.",
        }
    elif task_type_override == "suspicious":
        return {
            "label": "suspicious",
            "should_postpone": False,
            "reason": "Task explicitly marked as suspicious in custom rules metadata.",
        }

    # 2. Check custom regex/pattern rules
    custom_rules = list(rules_state.get("rules") or [])
    for rule in custom_rules:
        pattern = str(rule.get("pattern") or "").strip().lower()
        regex_pattern = str(rule.get("regex") or "").strip()
        label = str(rule.get("label") or "").strip().lower()
        if not label:
            continue

        matched = False
        if pattern and pattern in text:
            matched = True
        elif regex_pattern:
            try:
                if re.search(regex_pattern, text, re.IGNORECASE):
                    matched = True
            except Exception:
                pass

        if matched:
            if label in ("avoid", "avoidance"):
                return {
                    "label": "avoidance",
                    "should_postpone": True,
                    "reason": f"Matches custom avoidance rule '{rule.get('rule_id')}': {rule.get('reason', 'no reason provided')}",
                }
            elif label in ("suspicious", "suspicious_task"):
                return {
                    "label": "suspicious",
                    "should_postpone": False,
                    "reason": f"Matches custom suspicious rule '{rule.get('rule_id')}': {rule.get('reason', 'no reason provided')}",
                }

    # 3. Dynamic Semantic Matching against built-in category groups
    for cat_name, patterns in _FOCUS_GUARD_SEMANTIC_AVOIDANCE_GROUPS.items():
        for pat in patterns:
            try:
                if re.search(pat, text, re.IGNORECASE):
                    return {
                        "label": "avoidance",
                        "should_postpone": True,
                        "reason": f"Likely avoidance task ({cat_name.replace('_', ' ')}): matches semantic pattern '{pat}' dodging the actual priority.",
                    }
            except Exception:
                pass

    for cat_name, patterns in _FOCUS_GUARD_SEMANTIC_SUSPICIOUS_GROUPS.items():
        for pat in patterns:
            try:
                if re.search(pat, text, re.IGNORECASE):
                    return {
                        "label": "suspicious",
                        "should_postpone": False,
                        "reason": f"Possibly useful support work ({cat_name.replace('_', ' ')}): matches semantic pattern '{pat}' as a substitute for priority work.",
                    }
            except Exception:
                pass

    # 4. Fallback to original exact substring matching
    if any(term in text for term in _FOCUS_GUARD_AVOIDANCE_TERMS):
        return {
            "label": "avoidance",
            "should_postpone": True,
            "reason": "Likely avoidance task: it looks like system-optimizing or research that dodges the actual hard thing.",
        }

    if any(term in text for term in _FOCUS_GUARD_SUSPICIOUS_TERMS):
        return {
            "label": "suspicious",
            "should_postpone": False,
            "reason": "Possibly useful support work, but it may be a softer substitute for the real priority.",
        }

    return None


def _focus_guard_state_payload(*, tasks: List[Dict[str, Any]], status: str) -> Dict[str, Any]:
    suspicious_tasks = []
    for task in tasks:
        classification = _focus_guard_classify_task(task)
        if classification:
            suspicious_tasks.append({"task": task, "classification": classification})

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "task_count": len(tasks),
        "most_important_task": _focus_guard_pick_most_important_task(tasks),
        "suspicious_tasks": suspicious_tasks,
    }


def _focus_guard_read_state(path: Optional[Path] = None) -> Dict[str, Any]:
    data = _read_json(path or FOCUS_GUARD_STATE_PATH, {})
    if not isinstance(data, dict):
        return {}
    return data


def _focus_guard_write_state(payload: Dict[str, Any], path: Optional[Path] = None) -> None:
    _write_json(path or FOCUS_GUARD_STATE_PATH, payload)


def _focus_guard_append_event(event_type: str, data: Dict[str, Any], path: Optional[Path] = None) -> None:
    resolved_path = path or FOCUS_GUARD_EVENT_LOG_PATH
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {"ts": _now(), "type": event_type, **data}
    with resolved_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _focus_guard_read_todoist_tasks(*, filter: Optional[str] = None) -> List[Dict[str, Any]]:
    params: Dict[str, Any] = {}
    if filter:
        params["filter"] = filter
    with _http_client() as client:
        resp = client.get(f"{TODOIST_BASE}/tasks", headers=_todoist_headers(), params=params)
        resp.raise_for_status()
        tasks = (resp.json() or {}).get("results") or []

        filter_str = str(filter or "").strip().lower()
        if filter_str:
            from datetime import datetime, timedelta
            today_str = _operator_local_date()
            try:
                today_dt = datetime.fromisoformat(today_str)
                tomorrow_str = (today_dt + timedelta(days=1)).date().isoformat()
            except Exception:
                tomorrow_str = ""

            filtered_tasks = []
            for t in tasks:
                labels = [str(l).lower() for l in t.get("labels") or []]
                excluded_labels = {
                    "exclude_workload", "reference", "hermes_hidden", "checklist_item", "duplicate",
                    "someday", "maybe", "someday_maybe", "someday-maybe", "someday/maybe"
                }
                if any(l in excluded_labels for l in labels):
                    continue

                due = t.get("due")
                if isinstance(due, dict) and due.get("date"):
                    date_part = str(due["date"]).split("T")[0]
                    is_recurring = due.get("is_recurring") is True

                    # Skip overdue recurring routines to avoid past routine carryover clutter
                    if is_recurring and date_part < today_str:
                        continue

                    if "today" in filter_str and "overdue" in filter_str:
                        if date_part <= today_str:
                            filtered_tasks.append(t)
                    elif "today" in filter_str:
                        if date_part == today_str:
                            filtered_tasks.append(t)
                    elif "overdue" in filter_str:
                        if date_part < today_str:
                            filtered_tasks.append(t)
                    elif "tomorrow" in filter_str:
                        if tomorrow_str and date_part == tomorrow_str:
                            filtered_tasks.append(t)
                    else:
                        filtered_tasks.append(t)
                else:
                    if not any(k in filter_str for k in ["today", "overdue", "tomorrow"]):
                        filtered_tasks.append(t)
            tasks = filtered_tasks

        return tasks


def _adaptive_companion_default_state() -> Dict[str, Any]:
    return {
        "mode": "idle",
        "last_pressure_style": None,
        "last_pattern_label": None,
        "last_intervention_family": None,
        "last_intervention_at": None,
        "pattern_memory": {},
        "style_effectiveness": {},
        "recent_interventions": [],
        "style_history": [],
        "response_history": [],
        "combination_effectiveness": {},
        "intervention_family_history": [],
        "intervention_family_effectiveness": {},
        "pattern_history": [],
        "stale_families": [],
        "completion_history": [],
        "insight_lenses": {},
    }


def _adaptive_companion_read_state(path: Optional[Path] = None) -> Dict[str, Any]:
    resolved_path = path or ADAPTIVE_COMPANION_STATE_PATH
    data = _read_json(resolved_path, _adaptive_companion_default_state())
    if not isinstance(data, dict):
        return _adaptive_companion_default_state()
    state = _adaptive_companion_default_state()
    state.update(data)
    return state


def _adaptive_companion_detect_trigger(*, user_text: str, focus_state: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
    del state
    text = str(user_text or "").strip().lower()
    top_task = focus_state.get("most_important_task") or {}
    task_label = str((top_task.get("content") or "")).strip() or None
    task_id = str(top_task.get("id") or "").strip() or None
    base = {"task_label": task_label, "task_id": task_id, "source": "Todoist"}
    if any(term in text for term in _ADAPTIVE_COMPANION_META_DEFLECTION_TERMS):
        return {**base, "kind": "meta_deflection", "evidence": "meta bait"}
    suspicious_tasks = list(focus_state.get("suspicious_tasks") or [])
    if suspicious_tasks:
        first = suspicious_tasks[0]
        suspect_task = first.get("task") or {}
        suspect = str(suspect_task.get("content") or "side quest").strip()
        return {
            **base,
            "kind": "suspicious_task",
            "evidence": suspect,
            "side_task_label": suspect,
            "side_task_id": str(suspect_task.get("id") or "").strip() or None,
        }
    if any(term in text for term in _ADAPTIVE_COMPANION_SUSPICIOUS_TERMS):
        return {**base, "kind": "productive_procrastination", "evidence": text}
    if focus_state.get("status") == "needs_focus" and task_label:
        return {**base, "kind": "focus_drift", "evidence": "most important task still open"}
    return {**base, "kind": "none", "evidence": None}


def _adaptive_companion_select_style(*, trigger: Dict[str, Any], state: Dict[str, Any], now_hour: int) -> str:
    kind = str(trigger.get("kind") or "none")
    recent_styles = list(state.get("style_history") or [])[-2:]
    preferred = {
        "meta_deflection": ["evidence_check", "task_repair", "low_pressure_redirect"],
        "productive_procrastination": ["pattern_mirror", "task_repair", "low_pressure_redirect"],
        "suspicious_task": ["evidence_check", "pattern_mirror", "low_pressure_redirect"],
        "focus_drift": ["low_pressure_redirect" if now_hour < 12 else "pattern_mirror", "task_repair", "evidence_check"],
    }.get(kind, ["grounded_empathy"])

    style_effectiveness = dict(state.get("style_effectiveness") or {})

    # With no effectiveness data, use the policy-safe default order. Older
    # pressure/personality styles are deliberately not explored anymore.
    if not style_effectiveness:
        for style in preferred:
            if style not in recent_styles:
                return style
        return preferred[0]

    # 1. Filter out recent styles to avoid consecutive repetition
    candidates = [style for style in preferred if style not in recent_styles]
    if not candidates:
        candidates = preferred

    # 2. Epsilon-greedy exploration vs exploitation
    epsilon = 0.20
    if len(candidates) > 1 and random.random() < epsilon:
        return random.choice(candidates)

    def get_success_score(style: str) -> float:
        # Get completion success count
        completed_count = int(dict(style_effectiveness.get(style) or {}).get("completed_after_nudge") or 0)
        return float(completed_count)

    # Use preferred list order to tie-break deterministically
    best_style = max(candidates, key=lambda s: (get_success_score(s), -preferred.index(s)))
    return best_style


def _adaptive_companion_infer_user_state(*, trigger: Dict[str, Any], now_hour: int) -> str:
    kind = str(trigger.get("kind") or "none")
    if kind == "meta_deflection":
        return "meta_deflecting"
    if kind == "suspicious_task":
        return "avoiding"
    if kind == "focus_drift" and now_hour >= 21:
        return "late_night_fragile"
    if kind == "focus_drift":
        return "drifting"
    return "engaged"


def _adaptive_companion_classify_pattern(
    *,
    trigger: Dict[str, Any],
    inferred_state: str,
    state: Dict[str, Any],
) -> Dict[str, Any]:
    del state
    kind = str(trigger.get("kind") or "none")
    evidence = str(trigger.get("evidence") or "").strip().lower()

    if inferred_state == "meta_deflecting" or kind == "meta_deflection":
        return {
            "label": "meta_deflection",
            "explanation": "You are trying to turn the work into a meta conversation so you do not have to face the work itself.",
        }
    if kind == "suspicious_task" and any(term in evidence for term in _ADAPTIVE_COMPANION_FALSE_PREP_TERMS):
        return {
            "label": "false_prep",
            "explanation": "You are trying to feel ready instead of becoming exposed by starting the real task.",
        }
    if kind == "suspicious_task":
        return {
            "label": "smart_detour",
            "explanation": "You are leaning into respectable side movement instead of the task that actually carries consequence.",
        }
    if any(term in evidence for term in _ADAPTIVE_COMPANION_COMFORT_TERMS):
        return {
            "label": "comfort_escape",
            "explanation": "You are reaching for the easier version of the day so you can stay comfortable.",
        }
    if kind == "productive_procrastination":
        return {
            "label": "smart_detour",
            "explanation": "You are using respectable side movement so you can feel active without doing the thing that matters.",
        }
    if inferred_state == "drifting" or kind == "focus_drift":
        return {
            "label": "friction_avoidance",
            "explanation": "The task has friction, so you are circling it instead of starting it.",
        }
    if inferred_state == "late_night_fragile":
        return {
            "label": "overloaded_for_real",
            "explanation": "This looks more like depletion than theater, so the task needs reduction instead of pure pressure.",
        }
    return {
        "label": "momentum_present",
        "explanation": "You are engaged enough that Hermes should reinforce momentum instead of forcing a correction.",
    }


def _adaptive_companion_select_response_strategy(
    *,
    trigger: Dict[str, Any],
    inferred_state: str,
    state: Dict[str, Any],
    now_hour: int,
) -> Dict[str, str]:
    insight_lenses = dict(state.get("insight_lenses") or {})
    mood = dict((state.get("mood_router") or {}).get("last_mood") or {})
    mood_label = str(mood.get("label") or "")
    mood_confidence = float(mood.get("confidence") or 0)
    anti_narrative = bool((insight_lenses.get("anti_narrative_mode") or {}).get("active"))
    recovery = dict(insight_lenses.get("recovery_intelligence") or {})
    threshold = dict(insight_lenses.get("threshold_detection") or {})
    recent_count = len(list(state.get("recent_interventions") or []))
    if anti_narrative:
        return {
            "pressure": "steady",
            "language": "plain",
            "length": "one_line",
            "energy": "calm",
        }
    if str(recovery.get("mode") or "") == "stabilize":
        return {
            "pressure": "warm",
            "language": "plain",
            "length": "short",
            "energy": "calm",
        }
    if mood_confidence >= 0.65 and mood_label in {"low_energy", "frustrated", "confused"}:
        return {
            "pressure": "warm",
            "language": "explanatory" if mood_label in {"frustrated", "confused"} else "plain",
            "length": "short",
            "energy": "calm",
        }
    if inferred_state == "meta_deflecting":
        count = int(((state.get("pattern_memory") or {}).get("meta_deflection") or {}).get("count") or 0)
        return {
            "pressure": "steady",
            "language": "plain" if count < 2 else "explanatory",
            "length": "short" if count < 3 else "medium",
            "energy": "calm",
        }
    if inferred_state == "drifting":
        threshold_level = str(threshold.get("level") or "low")
        return {
            "pressure": "steady",
            "language": "plain",
            "length": "short" if threshold_level == "high" or now_hour >= 12 else "one_line",
            "energy": "calm",
        }
    if str(trigger.get("kind") or "") == "suspicious_task" and trigger.get("side_task_label") and recent_count % 2 == 0:
        return {
            "pressure": "warm",
            "language": "explanatory",
            "length": "detailed",
            "energy": "calm",
        }
    if str(trigger.get("kind") or "") == "focus_drift" and recent_count % 3 == 0:
        return {
            "pressure": "warm",
            "language": "explanatory",
            "length": "detailed",
            "energy": "calm",
        }
    return {
        "pressure": "warm",
        "language": "conversational",
        "length": "short",
        "energy": "calm",
    }


def _adaptive_companion_select_intervention_family(
    *,
    pattern: Dict[str, Any],
    strategy: Dict[str, str],
    state: Dict[str, Any],
) -> str:
    del strategy
    label = str(pattern.get("label") or "friction_avoidance")
    insight_lenses = dict(state.get("insight_lenses") or {})
    recovery = dict(insight_lenses.get("recovery_intelligence") or {})
    threshold = dict(insight_lenses.get("threshold_detection") or {})
    recent_families = list(state.get("intervention_family_history") or [])[-2:]
    if str(recovery.get("mode") or "") == "stabilize":
        preferred = ["grounded_reset", "earned_respect"]
    elif str(recovery.get("mode") or "") == "interrupt":
        preferred = ["binary_frame", "pattern_mirror", "hierarchy_enforcement"]
    elif str(threshold.get("level") or "") == "high" and label in {"smart_detour", "friction_avoidance", "false_prep"}:
        preferred = ["binary_frame", "pattern_mirror", "hierarchy_enforcement"]
    else:
        preferred = {
            "meta_deflection": ["enemy_naming", "pattern_mirror", "binary_frame"],
            "false_prep": ["hierarchy_enforcement", "pattern_mirror", "comfort_callout"],
            "smart_detour": ["hierarchy_enforcement", "pattern_mirror", "comfort_callout"],
            "comfort_escape": ["binary_frame", "comfort_callout", "pattern_mirror"],
            "friction_avoidance": ["pattern_mirror", "binary_frame", "hierarchy_enforcement"],
            "overloaded_for_real": ["grounded_reset", "earned_respect"],
            "momentum_present": ["earned_respect"],
        }.get(label, ["pattern_mirror"])

    family_effectiveness = dict(state.get("intervention_family_effectiveness") or {})

    # Legacy fallback check: if there is no effectiveness data, behave identically to legacy code
    if not family_effectiveness:
        for family in preferred:
            if family not in recent_families:
                return family
        return preferred[-1]

    # 1. Filter out recent families to avoid consecutive repetition
    candidates = [fam for fam in preferred if fam not in recent_families]
    if not candidates:
        candidates = preferred

    # 2. Epsilon-greedy exploration vs exploitation
    epsilon = 0.20
    if len(candidates) > 1 and random.random() < epsilon:
        return random.choice(candidates)

    def get_success_score(fam: str) -> float:
        completed_count = int(dict(family_effectiveness.get(fam) or {}).get("completed_after_nudge") or 0)
        return float(completed_count)

    # Use preferred list order to tie-break deterministically
    best_family = max(candidates, key=lambda f: (get_success_score(f), -preferred.index(f)))
    return best_family


def _adaptive_companion_variant_index(*, family: str, state: Dict[str, Any], options_count: int) -> int:
    if options_count <= 1:
        return 0
    recent = list(state.get("intervention_family_history") or [])
    if recent and recent[-1] == family:
        return 1 % options_count
    return 0


def _adaptive_companion_event_is_fresh(event: Dict[str, Any], *, now: Optional[datetime] = None) -> bool:
    ts_raw = str(event.get("ts") or "").strip()
    if not ts_raw:
        return False
    try:
        event_ts = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
    except Exception:
        return False
    if event_ts.tzinfo is None:
        event_ts = event_ts.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    age = now - event_ts
    return timedelta(seconds=0) <= age <= timedelta(minutes=ADAPTIVE_COMPANION_REASON_ANCHOR_TTL_MINUTES)


def _adaptive_companion_reason_anchor(*, trigger: Dict[str, Any], state: Dict[str, Any]) -> Optional[str]:
    del state
    event_state = _runtime_read_event_state()
    last_event = dict(event_state.get("last_event") or {})
    event_type = str(last_event.get("event_type") or "").strip()
    if _adaptive_companion_event_is_fresh(last_event):
        if event_type == "wake":
            return "Because I received a recent desktop start signal, "
    return None


def _adaptive_companion_apply_reason_anchor(*, message: str, trigger: Dict[str, Any], state: Dict[str, Any], strategy: Dict[str, str]) -> str:
    if str(strategy.get("length") or "") == "one_line":
        return message
    anchor = _adaptive_companion_reason_anchor(trigger=trigger, state=state)
    if not anchor:
        return message
    if message[:1].isalpha():
        message = message[:1].lower() + message[1:]
    return anchor + message


def _adaptive_companion_task_context(trigger: Dict[str, Any]) -> str:
    task_label = str(trigger.get("task_label") or "your main objective").strip()
    side_task = str(trigger.get("side_task_label") or "").strip()
    if side_task:
        return f'I noticed you\'re spending some time on "{side_task}", but your main focus right now is "{task_label}".'
    return f'Checking in on your focus: your main priority is "{task_label}".'


def _adaptive_companion_examples_for_task(task_label: str) -> List[str]:
    text = task_label.lower()
    if "outing" in text:
        return [
            "choose one place or route",
            "message one person or set one time",
            "put the first concrete step on the calendar or in Todoist",
        ]
    if "family" in text or "handoff" in text:
        return [
            "confirm the next handoff detail",
            "prepare one simple thing to make starting feel easier later",
            "send the one message that makes the next step clear",
        ]
    if "call" in text or "contact" in text or "follow up" in text:
        return [
            "open the contact thread",
            "write the first plain sentence",
            "send it or schedule exactly when it will be sent",
        ]
    return [
        "open the task",
        "do the first ten minutes",
        "write down what you'd like to do next before taking a break",
    ]


def _adaptive_companion_detailed_message(*, trigger: Dict[str, Any], state: Dict[str, Any]) -> str:
    context = _adaptive_companion_task_context(trigger)
    task_label = str(trigger.get("task_label") or "the top task").strip()
    side_task = str(trigger.get("side_task_label") or "").strip()
    examples = _adaptive_companion_examples_for_task(task_label)
    variant = len(list(state.get("recent_interventions") or [])) % 3
    if variant == 0:
        lines = [
            context,
            f"Let's focus on your main priority, '{task_label}', to build some great momentum.",
            "A great next move to get started is simply to:",
            f"- {examples[0]}",
            f"- {examples[1]}",
            f"- {examples[2]}",
        ]
    elif variant == 1:
        lines = [
            context,
            "Starting a big task is much easier when you focus strictly on a tiny, 2-minute step.",
            f"Instead of over-planning '{task_label}', let's do something immediate and visible, like: {examples[0]}.",
            f"Once that's done, you can easily: {examples[1]}.",
        ]
    else:
        lines = [
            context,
            "Here is a simple micro-plan to start:",
            f"1. {examples[0].capitalize()}.",
            f"2. {examples[1].capitalize()}.",
            f"3. {examples[2].capitalize()}.",
            "Give this a shot first, then see how you feel!",
        ]
    if side_task:
        lines.append(f"Let's temporarily pause on \"{side_task}\" while we get this first step done.")
    return "\n".join(lines)



def _adaptive_companion_render_message(
    *,
    trigger: Dict[str, Any],
    strategy: Dict[str, str],
    pattern: Optional[Dict[str, Any]] = None,
    family: Optional[str] = None,
    state: Dict[str, Any],
) -> str:
    task_label = str(trigger.get("task_label") or "the task").strip()
    context = _adaptive_companion_task_context(trigger)
    evidence = str(trigger.get("evidence") or "").strip()
    language = str(strategy.get("language") or "")
    length = str(strategy.get("length") or "")
    insight_lenses = dict(state.get("insight_lenses") or {})
    recovery = dict(insight_lenses.get("recovery_intelligence") or {})
    threshold = dict(insight_lenses.get("threshold_detection") or {})
    respect = dict(insight_lenses.get("respect_engine") or {})
    pattern = dict(pattern or {})
    family = str(family or "")
    pattern_label = str(pattern.get("label") or ("meta_deflection" if trigger.get("kind") == "meta_deflection" else "friction_avoidance"))

    if length == "detailed":
        return _adaptive_companion_apply_reason_anchor(
            message=_adaptive_companion_detailed_message(trigger=trigger, state=state),
            trigger=trigger,
            state=state,
            strategy=strategy,
        )

    if family == "stairs_not_elevator":
        options = (
            [f"{context} The smaller side task can wait. Let's do just one tiny step on '{task_label}' first.",
             f"{context} Let's keep this simple: one small, visible step on '{task_label}', then reassess."]
            if language == "plain"
            else [f"{context} The easier task might be a detour. Start with one visible step on '{task_label}' first.",
                  f"{context} Let's choose the smallest first step on '{task_label}' before worrying about other tasks."]
        )
        return options[_adaptive_companion_variant_index(family=family, state=state, options_count=len(options))]

    if family == "comfort_callout":
        return f"{context} Let's focus on your main priority first to get a clean win, before diving into the easier tasks."

    if family == "enemy_naming":
        return f"{context} Sometimes we fall into the trap of overthinking or planning too much instead of just taking one simple, physical action to start. Let's make the first step easy and just do that."

    if family == "binary_frame":
        options = [
            f"{context} You have two wonderful, pressure-free options: take just one tiny step forward today, or reschedule it with zero guilt so it's not hanging over you.",
            f"{context} Let's keep it beautifully simple: just one quick first step, and then you can decide what to do next.",
        ]
        return options[_adaptive_companion_variant_index(family=family, state=state, options_count=len(options))]

    if family == "hierarchy_enforcement":
        options = [
            f"{context} Let's temporarily pause on '{side_task}' and get one small priority step done on '{task_label}' first." if trigger.get("side_task_label") else f"{context} Let's get one small priority step done first.",
            f"{context} Let's handle your main priority first, and save the support tasks as a satisfying reward for later.",
        ]
        return options[_adaptive_companion_variant_index(family=family, state=state, options_count=len(options))]

    if family == "identity_challenge":
        if pattern_label == "meta_deflection":
            return f"{context} Planning is wonderful, but sometimes it becomes a way of delaying the work. Let's pick one small, physical step and start there."
        return f"{context} You've got this. Let's keep the next step beautifully simple and concrete: just one small action, then see how you feel."

    if family == "grounded_reset":
        suggestion = str(recovery.get("suggestion") or "").strip()
        if suggestion:
            return suggestion.replace("the real task", task_label)
        return f"Take a deep breath—you are doing great, but you might just have a lot on your plate today. Let's shrink '{task_label}' down to the absolute easiest first step and do just that, pressure-free."

    if family == "earned_respect":
        note = str(respect.get("note") or "").strip()
        if note:
            return f"{note} Let's stay focused on '{task_label}'."
        return f"You're showing incredible consistency with '{task_label}'. Let's keep that beautiful momentum going!"

    if family == "pattern_mirror":
        if pattern_label == "false_prep":
            options = [
                f"{context} It's easy to get caught up in getting ready to get ready. Let's skip the extra setup and take just one tiny, direct step on your top task instead!",
                f"{context} You don't need more setup to start '{task_label}'. Let's just make one tiny, simple point of contact with it today.",
            ]
            return options[_adaptive_companion_variant_index(family=family, state=state, options_count=len(options))]
        if pattern_label == "meta_deflection":
            options = [
                f"{context} Sometimes we overthink things when they feel heavy. Let's make it easy: just pick one tiny, physical step and start there!",
                f"{context} You've done all the planning you need. The absolute best move right now is just one simple, concrete next action.",
            ]
            return options[_adaptive_companion_variant_index(family=family, state=state, options_count=len(options))]
        if pattern_label == "smart_detour":
            options = [
                f"{context} Let's start with just one quick, tiny step on '{task_label}' first to build momentum.",
                f"{context} Just a gentle nudge because '{side_task}' might feel a bit more comfortable, but '{task_label}' is still your main priority." if trigger.get("side_task_label") else f"{context} Just a gentle check-in because '{task_label}' is still waiting for its first step.",
            ]
            return options[_adaptive_companion_variant_index(family=family, state=state, options_count=len(options))]
        if evidence:
            if trigger.get("kind") == "focus_drift" or evidence == "most important task still open":
                return f"{context} Your top task '{task_label}' might feel a bit heavy or intimidating right now. That's completely okay! Let's put everything else on pause until you take just one tiny, comfortable step on it."
            return f"{context} It's completely normal to want to do '{evidence}' first because '{task_label}' feels a bit heavy. Let's put '{evidence}' on hold until you take just one single, easy step on '{task_label}' first."
        return f"{context} If '{task_label}' feels a bit daunting, let's take all the pressure off and shrink it down to a tiny 2-minute step."


    if language == "plain" and length == "one_line":
        if str(threshold.get("level") or "") == "high":
            return f"{context} Let's do just one tiny step now."
        if pattern_label == "friction_avoidance":
            return f"{context} Let's take one quick step on '{task_label}'."
        return f"{context} Let's make '{task_label}' our next gentle focus."

    if length in {"long", "medium"} and pattern_label == "meta_deflection":
        message = (
            f"{context} Sometimes we overthink things when a task feels a bit heavy. "
            f"There's absolutely no pressure here; it's just a natural signal that it might feel daunting to start. "
            f"The best move is to pick the absolute easiest, smallest action on '{task_label}', do just that, then decide what's next."
        )

        return _adaptive_companion_apply_reason_anchor(message=message, trigger=trigger, state=state, strategy=strategy)

    if language == "conversational":
        message = f"{context} Take just one small step now, and see how you feel."
        return _adaptive_companion_apply_reason_anchor(message=message, trigger=trigger, state=state, strategy=strategy)

    message = f"{context} Let's take just one tiny step to begin."
    return _adaptive_companion_apply_reason_anchor(message=message, trigger=trigger, state=state, strategy=strategy)


def _adaptive_companion_strategy_key(strategy: Dict[str, str]) -> str:
    return "|".join(
        [
            str(strategy.get("pressure") or ""),
            str(strategy.get("language") or ""),
            str(strategy.get("length") or ""),
            str(strategy.get("energy") or ""),
        ]
    )


def _adaptive_companion_should_suppress(
    *,
    state: Dict[str, Any],
    trigger: Dict[str, Any],
    pattern: Dict[str, Any],
    now: datetime,
) -> Optional[Dict[str, Any]]:
    task_label = str(trigger.get("task_label") or "").strip().lower()
    pattern_label = str(pattern.get("label") or "").strip().lower()
    if not task_label or not pattern_label:
        return None

    recent = list(state.get("recent_interventions") or [])
    if not recent:
        return None

    latest = recent[-1]
    latest_task_label = str(latest.get("task_label") or "").strip().lower()

    # 0. SAME OBSERVATION SUPPRESSION (Grounded task state-aware suppression)
    # If the top task and the side task are identical, and no tasks have been completed,
    # deleted, or added since the last intervention, suppress the repeat nudge.
    latest_task_id = str(latest.get("task_id") or "").strip()
    current_task_id = str(trigger.get("task_id") or "").strip()
    latest_side_task_id = str(latest.get("side_task_id") or "").strip()
    current_side_task_id = str(trigger.get("side_task_id") or "").strip()

    if latest_task_id == current_task_id and latest_side_task_id == current_side_task_id and (latest_task_id or latest_side_task_id):
        latest_active_ids = latest.get("active_task_ids") or []
        if latest_active_ids:
            try:
                current_tasks = _focus_guard_read_todoist_tasks()
                current_active_ids = [str(t.get("id")) for t in current_tasks if t.get("id")]
                if set(current_active_ids) == set(latest_active_ids):
                    return {
                        "reason": "same_task_no_state_change",
                        "scope": "same_task",
                    }
            except Exception:
                pass

    sent_at_raw = str(latest.get("sent_at") or latest.get("created_at") or "").strip()
    if sent_at_raw:
        try:
            sent_at = datetime.fromisoformat(sent_at_raw.replace("Z", "+00:00"))
        except Exception:
            sent_at = None
        if sent_at is not None:
            if sent_at.tzinfo is None:
                sent_at = sent_at.replace(tzinfo=timezone.utc)
            elapsed = now - sent_at

            # 1. Same task cooldown check (increased to 180 mins to avoid repeated briefs on same task)
            if latest_task_label == task_label:
                same_task_cooldown = timedelta(minutes=ADAPTIVE_COMPANION_SAME_TASK_COOLDOWN_MINUTES)
                if elapsed < same_task_cooldown:
                    remaining = max(int((same_task_cooldown - elapsed).total_seconds() // 60), 0)
                    return {
                        "reason": "cooldown",
                        "cooldown_minutes": ADAPTIVE_COMPANION_SAME_TASK_COOLDOWN_MINUTES,
                        "minutes_remaining": remaining,
                        "scope": "same_task",
                    }

            # 2. General spacing cooldown (90 mins to ensure briefs are spaced out generally)
            general_cooldown = timedelta(minutes=ADAPTIVE_COMPANION_REPEAT_COOLDOWN_MINUTES)
            if elapsed < general_cooldown:
                remaining = max(int((general_cooldown - elapsed).total_seconds() // 60), 0)
                return {
                    "reason": "cooldown",
                    "cooldown_minutes": ADAPTIVE_COMPANION_REPEAT_COOLDOWN_MINUTES,
                    "minutes_remaining": remaining,
                    "scope": "general",
                }

    local_tz = timezone.utc
    if ZoneInfo is not None:
        try:
            local_tz = ZoneInfo(HERMES_LOCAL_TIMEZONE)
        except Exception:
            local_tz = timezone.utc
    today = now.astimezone(local_tz).date()
    task_count_today = 0
    pattern_count_today = 0
    for item in recent:
        item_task = str(item.get("task_label") or "").strip().lower()
        if item_task != task_label:
            continue
        item_sent_raw = str(item.get("sent_at") or item.get("created_at") or "").strip()
        if not item_sent_raw:
            continue
        try:
            item_sent = datetime.fromisoformat(item_sent_raw.replace("Z", "+00:00"))
        except Exception:
            continue
        if item_sent.tzinfo is None:
            item_sent = item_sent.replace(tzinfo=timezone.utc)
        if item_sent.astimezone(local_tz).date() != today:
            continue
        task_count_today += 1
        item_pattern = str(((item.get("pattern") or {}).get("label") or "")).strip().lower()
        if item_pattern == pattern_label:
            pattern_count_today += 1
    if pattern_count_today >= ADAPTIVE_COMPANION_DAILY_TASK_PATTERN_LIMIT:
        return {
            "reason": "pressure_limit",
            "limit": ADAPTIVE_COMPANION_DAILY_TASK_PATTERN_LIMIT,
            "scope": "same_task_and_pattern",
        }
    if task_count_today >= ADAPTIVE_COMPANION_DAILY_TASK_LIMIT:
        return {
            "reason": "pressure_limit",
            "limit": ADAPTIVE_COMPANION_DAILY_TASK_LIMIT,
            "scope": "same_task",
        }
    return None


def _adaptive_companion_update_response_learning(
    *,
    state: Dict[str, Any],
    trigger_kind: str,
    strategy: Dict[str, str],
    outcome: str,
) -> Dict[str, Any]:
    next_state = dict(state)
    combinations = dict(next_state.get("combination_effectiveness") or {})
    key = _adaptive_companion_strategy_key(strategy)
    row = dict(combinations.get(key) or {})
    row[outcome] = int(row.get(outcome) or 0) + 1
    combinations[key] = row
    next_state["combination_effectiveness"] = combinations

    history = list(next_state.get("response_history") or [])
    history.append({"trigger": trigger_kind, "strategy": dict(strategy), "outcome": outcome})
    next_state["response_history"] = history[-12:]
    return next_state


def _adaptive_companion_update_family_learning(
    *,
    state: Dict[str, Any],
    pattern_label: str,
    family: str,
    outcome: str,
) -> Dict[str, Any]:
    next_state = dict(state)
    effectiveness = dict(next_state.get("intervention_family_effectiveness") or {})
    family_row = dict(effectiveness.get(family) or {})
    family_row[outcome] = int(family_row.get(outcome) or 0) + 1
    effectiveness[family] = family_row
    next_state["intervention_family_effectiveness"] = effectiveness

    history = list(next_state.get("intervention_family_history") or [])
    history.append(family)
    next_state["intervention_family_history"] = history[-8:]

    pattern_history = list(next_state.get("pattern_history") or [])
    pattern_history.append({"pattern": pattern_label, "family": family, "outcome": outcome})
    next_state["pattern_history"] = pattern_history[-12:]
    return next_state


def _adaptive_companion_build_message(*, trigger: Dict[str, Any], style: str, state: Dict[str, Any]) -> str:
    del state
    task_label = str(trigger.get("task_label") or "the task").strip()
    evidence = str(trigger.get("evidence") or "").strip()
    if style in {"ego_puncture", "evidence_check"}:
        return f"Todoist check: {task_label} still has friction. Pick one visible step or reschedule it honestly."
    if style in {"amused_contempt", "task_repair"}:
        if evidence:
            return f"Todoist check: '{evidence}' may be a side task. Do one visible step on {task_label}, or repair the task if it is unclear."
        return f"Todoist check: {task_label} may need a smaller next action."
    if style in {"hard_confrontation", "low_pressure_redirect"}:
        return f"Todoist check: focus on one concrete step for {task_label}. If that is not realistic, mark the blocker."
    if style == "pattern_mirror":
        return f"Todoist check: {task_label} has friction. Shrink it to one visible step instead of circling it."
    if style == "calm_command":
        return f"Todoist check: the useful move is one visible step on {task_label}."
    return f"Todoist check: shrink {task_label} to the first real piece, or reschedule it honestly."


def _adaptive_companion_recent_user_text() -> str:
    return ""


def _adaptive_companion_write_state(state: Dict[str, Any], path: Optional[Path] = None) -> None:
    _write_json(path or ADAPTIVE_COMPANION_STATE_PATH, state)


def _adaptive_companion_update_learning(*, state: Dict[str, Any], trigger_kind: str, style: str, outcome: str) -> Dict[str, Any]:
    next_state = dict(state)
    styles = dict(next_state.get("style_effectiveness") or {})
    style_row = dict(styles.get(style) or {})
    style_row[outcome] = int(style_row.get(outcome) or 0) + 1
    styles[style] = style_row
    next_state["style_effectiveness"] = styles

    memory = dict(next_state.get("pattern_memory") or {})
    pattern = dict(memory.get(trigger_kind) or {})
    if outcome == "corrected":
        pattern["last_success_style"] = style
    pattern["last_outcome"] = outcome
    memory[trigger_kind] = pattern
    next_state["pattern_memory"] = memory
    history = list(next_state.get("style_history") or [])
    history.append(style)
    next_state["style_history"] = history[-8:]
    return next_state


def _adaptive_companion_record_task_completion(
    *,
    state: Dict[str, Any],
    task_id: str,
    completed_at: str,
) -> Dict[str, Any]:
    next_state = dict(state)
    recent = list(next_state.get("recent_interventions") or [])
    if not recent:
        return next_state

    task_id = str(task_id or "").strip()
    completed_at = str(completed_at or "").strip()
    if not task_id or not completed_at:
        return next_state

    updated = False
    for index in range(len(recent) - 1, -1, -1):
        item = dict(recent[index] or {})
        if str(item.get("task_id") or "").strip() != task_id:
            continue
        if str(item.get("completion_recorded_at") or "").strip():
            break

        style = str(item.get("style") or "").strip()
        family = str(item.get("intervention_family") or "").strip()
        pattern_label = str(((item.get("pattern") or {}).get("label") or "")).strip()
        trigger_kind = str(item.get("trigger") or "none").strip()
        strategy = dict(item.get("strategy") or {})
        outcome = "completed_after_nudge"

        if style:
            styles = dict(next_state.get("style_effectiveness") or {})
            style_row = dict(styles.get(style) or {})
            style_row[outcome] = int(style_row.get(outcome) or 0) + 1
            styles[style] = style_row
            next_state["style_effectiveness"] = styles

        if strategy:
            combinations = dict(next_state.get("combination_effectiveness") or {})
            key = _adaptive_companion_strategy_key(strategy)
            row = dict(combinations.get(key) or {})
            row[outcome] = int(row.get(outcome) or 0) + 1
            combinations[key] = row
            next_state["combination_effectiveness"] = combinations

        if family:
            effectiveness = dict(next_state.get("intervention_family_effectiveness") or {})
            family_row = dict(effectiveness.get(family) or {})
            family_row[outcome] = int(family_row.get(outcome) or 0) + 1
            effectiveness[family] = family_row
            next_state["intervention_family_effectiveness"] = effectiveness

        if trigger_kind:
            memory = dict(next_state.get("pattern_memory") or {})
            pattern = dict(memory.get(trigger_kind) or {})
            if style:
                pattern["last_completion_style"] = style
            pattern["last_outcome"] = outcome
            memory[trigger_kind] = pattern
            next_state["pattern_memory"] = memory

        item["completion_recorded_at"] = completed_at
        recent[index] = item
        next_state["recent_interventions"] = recent

        completion_history = list(next_state.get("completion_history") or [])
        completion_history.append(
            {
                "task_id": task_id,
                "task_label": item.get("task_label"),
                "style": style,
                "family": family,
                "pattern": pattern_label,
                "completed_at": completed_at,
                "outcome": outcome,
            }
        )
        next_state["completion_history"] = completion_history[-12:]
        updated = True
        break

    if not updated:
        return next_state
    return next_state


def _adaptive_companion_counterfactual(*, task_label: str, pattern_label: str) -> str:
    if pattern_label == "smart_detour":
        return f"If you keep choosing respectable drift over {task_label}, you will become a planner of life instead of a liver of it."
    if pattern_label == "false_prep":
        return f"If you keep preparing instead of starting {task_label}, readiness will become your favorite way to never be seen."
    if pattern_label == "comfort_escape":
        return f"If you keep picking comfort over {task_label}, your days will look cleaner and mean less."
    if pattern_label == "meta_deflection":
        return f"If you keep narrating around {task_label}, language will keep eating action."
    return f"If you keep postponing {task_label}, the pattern will harden into identity."


def _adaptive_companion_false_self_detector(*, trigger: Dict[str, Any], pattern_label: str) -> Dict[str, Any]:
    evidence = str(trigger.get("evidence") or "").strip().lower()
    if "identity" in evidence or "life os" in evidence:
        return {"label": "systems-self", "confidence": "high", "note": "You are performing the organized version of yourself instead of risking contact with the real task."}
    if pattern_label == "meta_deflection":
        return {"label": "clever-self", "confidence": "high", "note": "You are performing intelligence to avoid exposure."}
    if pattern_label == "false_prep":
        return {"label": "about-to-begin-self", "confidence": "medium", "note": "You are acting like the person who is nearly ready instead of the person who started."}
    return {"label": "none", "confidence": "low", "note": "No strong false-self performance detected."}


def _adaptive_companion_pattern_market(*, pattern_label: str, trigger: Dict[str, Any]) -> List[Dict[str, Any]]:
    evidence = str(trigger.get("evidence") or "").strip().lower()
    market = {
        "comfort": 1 if pattern_label in {"comfort_escape", "overloaded_for_real"} else 0,
        "avoidance": 2 if pattern_label in {"smart_detour", "false_prep", "friction_avoidance", "meta_deflection"} else 0,
        "pride": 1 if "identity" in evidence or "system" in evidence else 0,
        "fear": 1 if pattern_label in {"false_prep", "meta_deflection"} else 0,
        "momentum": 1 if pattern_label == "momentum_present" else 0,
        "curiosity": 1 if "research" in evidence or "explore" in evidence else 0,
    }
    return [
        {"voice": voice, "score": score}
        for voice, score in sorted(market.items(), key=lambda item: (-item[1], item[0]))
        if score > 0
    ]


def _adaptive_companion_recovery_intelligence(*, now_hour: int, pattern_label: str, state: Dict[str, Any]) -> Dict[str, Any]:
    recent_patterns = [str((item or {}).get("pattern") or "") for item in list(state.get("pattern_history") or [])[-4:]]
    repeated = len([item for item in recent_patterns if item == pattern_label])
    if now_hour >= 22:
        return {"mode": "reduce", "suggestion": "Protect the floor. One small real step, then stop negotiating with the night."}
    if repeated >= 2 and pattern_label in {"smart_detour", "false_prep"}:
        return {"mode": "interrupt", "suggestion": "Change state, not theory: stand up, move, then do the smallest visible piece."}
    if pattern_label == "overloaded_for_real":
        return {"mode": "stabilize", "suggestion": "You need reduction, food, water, or sleep more than rhetoric right now."}
    return {"mode": "pressure", "suggestion": "Stay with the real task long enough to break first contact friction."}


def _adaptive_companion_threshold_detection(*, state: Dict[str, Any], pattern_label: str) -> Dict[str, Any]:
    recent_patterns = [str((item or {}).get("pattern") or "") for item in list(state.get("pattern_history") or [])[-5:]]
    suspicious_run = len([item for item in recent_patterns if item in {"smart_detour", "false_prep", "meta_deflection"}])
    if pattern_label in {"smart_detour", "false_prep"} and suspicious_run >= 3:
        return {"level": "high", "signal": "You are in the last clean minutes before drift becomes the whole day."}
    if suspicious_run >= 2:
        return {"level": "medium", "signal": "Avoidance is clustering. Catch it now while the day is still recoverable."}
    return {"level": "low", "signal": "No acute threshold signal detected."}


def _adaptive_companion_drift_signature_map(*, state: Dict[str, Any]) -> Dict[str, Any]:
    history = list(state.get("pattern_history") or [])[-8:]
    labels = [str((item or {}).get("pattern") or "") for item in history if str((item or {}).get("pattern") or "").strip()]
    counts: Dict[str, int] = {}
    for label in labels:
        counts[label] = counts.get(label, 0) + 1
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return {
        "top_patterns": [{"pattern": pattern, "count": count} for pattern, count in ordered[:3]],
        "sequence": labels[-5:],
    }


def _adaptive_companion_respect_engine(*, state: Dict[str, Any]) -> Dict[str, Any]:
    completions = list(state.get("completion_history") or [])
    if not completions:
        return {"last_completion": None, "respect_level": "unearned", "note": "No costly completion has been recorded yet."}
    latest = dict(completions[-1] or {})
    label = str(latest.get("task_label") or "").strip()
    pattern = str(latest.get("pattern") or "").strip()
    respect_level = "high" if pattern in {"smart_detour", "false_prep", "meta_deflection"} else "medium"
    return {
        "last_completion": label or None,
        "respect_level": respect_level,
        "note": f"Last earned respect came from finishing {label} after resistance." if label else "Last earned respect came from finishing a resisted task.",
    }


def _adaptive_companion_identity_compression(*, state: Dict[str, Any], pattern_label: str) -> List[str]:
    respect = _adaptive_companion_respect_engine(state=state)
    lines = [
        "You respect visible contact with reality more than elegant preparation.",
        "You do not want a cleaner story. You want a life that withstands contact.",
    ]
    if pattern_label in {"smart_detour", "false_prep", "meta_deflection"}:
        lines.append("Your real standard is exposure over sophistication.")
    elif respect.get("respect_level") == "high":
        lines.append("You trust yourself most after costly action, not after tidy planning.")
    else:
        lines.append("You are still teaching yourself what counts as real work.")
    return lines


def _adaptive_companion_world_pressure(*, focus_state: Dict[str, Any], now_hour: int) -> Dict[str, Any]:
    task_count = int(focus_state.get("task_count") or 0)
    suspicious_count = len(list(focus_state.get("suspicious_tasks") or []))
    if task_count >= 20 and suspicious_count >= 3:
        return {"level": "high", "signal": "This is not just one task. The whole day shape is trying to slide sideways."}
    if now_hour >= 22 and task_count > 0:
        return {"level": "medium", "signal": "The clock is now part of the pressure, not just the task."}
    return {"level": "low", "signal": "Pressure is currently local, not system-wide."}


def _adaptive_companion_silent_interventions(*, pattern_label: str, trigger: Dict[str, Any]) -> List[str]:
    task_label = str(trigger.get("task_label") or "the task").strip()
    actions = [f"Pin {task_label} as the only task worth seeing for the next cycle."]
    if pattern_label in {"smart_detour", "false_prep"}:
        actions.append("Suppress side-quest language in the status layer and surface only the real target.")
    if pattern_label == "comfort_escape":
        actions.append("Reduce dashboard noise and remove optional summaries until first contact is made.")
    if pattern_label == "meta_deflection":
        actions.append("Switch to anti-narrative mode: one command, one checkpoint, no essay.")
    return actions[:3]


def _adaptive_companion_surface_policy(*, state: Dict[str, Any], focus_state: Dict[str, Any]) -> Dict[str, Any]:
    del focus_state
    lenses = dict(state.get("insight_lenses") or {})
    threshold = dict(lenses.get("threshold_detection") or {})
    recovery = dict(lenses.get("recovery_intelligence") or {})
    anti_narrative = bool((lenses.get("anti_narrative_mode") or {}).get("active"))
    silent = list(lenses.get("silent_interventions") or [])
    threshold_level = str(threshold.get("level") or "low").strip().lower()
    recovery_mode = str(recovery.get("mode") or "pressure").strip().lower()

    compact = anti_narrative or threshold_level == "high"
    reduce_noise = threshold_level in {"medium", "high"} or recovery_mode == "stabilize"
    target_only = compact or any("only task worth seeing" in str(item).lower() for item in silent)
    return {
        "mode": "narrow_focus" if target_only else "full_context",
        "compact_status": compact,
        "target_only": target_only,
        "hide_side_quests": threshold_level in {"medium", "high"},
        "suppress_optional_summaries": reduce_noise,
        "primary_target_label": str(((state.get("recent_interventions") or [{}])[-1] or {}).get("task_label") or "").strip() or None,
        "silent_move": silent[0] if silent else None,
    }


def _adaptive_companion_existential_mode(*, state: Dict[str, Any], task_label: str) -> Dict[str, Any]:
    completions = len(list(state.get("completion_history") or []))
    if completions == 0:
        question = f"What are you protecting by keeping {task_label} in thought instead of in life?"
    else:
        question = f"Which current obligation still matters, and which ones are only surviving because they are familiar?"
    return {"question": question}


def _adaptive_companion_refresh_insight_lenses(
    *,
    state: Dict[str, Any],
    trigger: Dict[str, Any],
    pattern: Dict[str, Any],
    focus_state: Dict[str, Any],
    now_hour: int,
) -> Dict[str, Any]:
    next_state = dict(state)
    task_label = str(trigger.get("task_label") or "the task").strip()
    pattern_label = str(pattern.get("label") or "unknown").strip()
    false_self = _adaptive_companion_false_self_detector(trigger=trigger, pattern_label=pattern_label)
    anti_narrative_active = pattern_label == "meta_deflection" or false_self.get("label") == "clever-self"
    next_state["insight_lenses"] = {
        "counterfactual": _adaptive_companion_counterfactual(task_label=task_label, pattern_label=pattern_label),
        "drift_signature_map": _adaptive_companion_drift_signature_map(state=next_state),
        "false_self_detector": false_self,
        "recovery_intelligence": _adaptive_companion_recovery_intelligence(now_hour=now_hour, pattern_label=pattern_label, state=next_state),
        "threshold_detection": _adaptive_companion_threshold_detection(state=next_state, pattern_label=pattern_label),
        "respect_engine": _adaptive_companion_respect_engine(state=next_state),
        "world_pressure": _adaptive_companion_world_pressure(focus_state=focus_state, now_hour=now_hour),
        "pattern_market": _adaptive_companion_pattern_market(pattern_label=pattern_label, trigger=trigger),
        "identity_compression": _adaptive_companion_identity_compression(state=next_state, pattern_label=pattern_label),
        "silent_interventions": _adaptive_companion_silent_interventions(pattern_label=pattern_label, trigger=trigger),
        "anti_narrative_mode": {
            "active": anti_narrative_active,
            "reason": "Language is currently functioning as cover." if anti_narrative_active else "Normal language range is still useful.",
        },
        "existential_mode": _adaptive_companion_existential_mode(state=next_state, task_label=task_label),
    }
    next_state["insight_lenses"]["surface_policy"] = _adaptive_companion_surface_policy(state=next_state, focus_state=focus_state)
    return next_state


def _adaptive_companion_now_local_hour() -> int:
    now = datetime.now(timezone.utc)
    if ZoneInfo is None:
        return now.astimezone().hour
    try:
        return now.astimezone(ZoneInfo(HERMES_LOCAL_TIMEZONE)).hour
    except Exception:
        return now.astimezone().hour


def _telegram_messages_allowed_now(now_hour: Optional[int] = None) -> bool:
    hour = _adaptive_companion_now_local_hour() if now_hour is None else int(now_hour)
    return QUIET_HOURS_START <= hour < QUIET_HOURS_END


def _adaptive_companion_always_on(args: Optional[Dict[str, Any]] = None) -> bool:
    if args and bool(args.get("always_on")):
        return True
    value = _env("ADAPTIVE_COMPANION_ALWAYS_ON").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _focus_guard_telegram_config() -> tuple[str, str]:
    bot_token = _env("TELEGRAM_BOT_TOKEN")
    chat_id = _env("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id:
        raise ValueError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be configured in ~/.hermes/.env")
    return bot_token, chat_id


def _focus_guard_telegram_post(method: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    bot_token, _ = _focus_guard_telegram_config()
    with _http_client() as client:
        resp = client.post(
            f"https://api.telegram.org/bot{bot_token}/{method}",
            json=payload,
        )
        resp.raise_for_status()
        response = resp.json() or {"ok": True}
    if method == "sendMessage" and isinstance(payload, dict):
        try:
            from plugins.personal_ops.nudge_receipts import log_nudge_receipt
            result = response.get("result") if isinstance(response, dict) else {}
            message_id = result.get("message_id") if isinstance(result, dict) else None
            chat = result.get("chat") if isinstance(result, dict) else {}
            resolved_chat_id = payload.get("chat_id") or (chat.get("id") if isinstance(chat, dict) else None)
            log_nudge_receipt(
                chat_id=resolved_chat_id,
                message_id=message_id,
                text=str(payload.get("text") or ""),
                message_class=str(payload.get("message_class") or "telegram_message"),
                source="temp_personal_ops_tools._focus_guard_telegram_post",
                buttons=payload.get("reply_markup"),
                metadata={"method": method, "disable_notification": payload.get("disable_notification")},
            )
        except Exception as exc:
            logger.warning("Failed to log nudge receipt: %s", exc)
    return response


def _telegram_feedback_callback(label: str) -> str:
    normalized = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(label or "").strip())
    normalized = "_".join(part for part in normalized.split("_") if part)
    return f"hermes_feedback:{normalized or 'unknown'}"


def _telegram_inline_keyboard(buttons: Optional[List[Any]]) -> Optional[Dict[str, Any]]:
    if not buttons:
        return None
    rows = []

    # Check if buttons is already a list of lists (explicit rows)
    if buttons and isinstance(buttons[0], list):
        for row_data in buttons:
            row = []
            for btn in row_data:
                if isinstance(btn, dict):
                    item = {"text": btn.get("text", "")}
                    if "url" in btn:
                        item["url"] = btn["url"]
                    elif "callback_data" in btn:
                        item["callback_data"] = btn["callback_data"]
                    else:
                        item["callback_data"] = _telegram_feedback_callback(btn.get("text", ""))
                    row.append(item)
                else:
                    label = str(btn).strip()
                    if label:
                        row.append({"text": label, "callback_data": _telegram_feedback_callback(label)})
            if row:
                rows.append(row)
        return {"inline_keyboard": rows}

    row = []
    for btn in buttons:
        if isinstance(btn, dict):
            item = {"text": btn.get("text", "")}
            if "url" in btn:
                item["url"] = btn["url"]
            elif "callback_data" in btn:
                item["callback_data"] = btn["callback_data"]
            else:
                item["callback_data"] = _telegram_feedback_callback(btn.get("text", ""))
            row.append(item)
        else:
            label = str(btn).strip()
            if label:
                row.append({"text": label, "callback_data": _telegram_feedback_callback(label)})
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return {"inline_keyboard": rows}


def _build_telegram_reply_markup(buttons: Optional[List[Any]]) -> Optional[Any]:
    if not buttons:
        return None
    try:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    except ImportError:
        return None

    rows = []

    # Check if buttons is already a list of lists (explicit rows)
    if buttons and isinstance(buttons[0], list):
        for row_data in buttons:
            row = []
            for btn in row_data:
                if isinstance(btn, dict):
                    text = btn.get("text", "")
                    if "url" in btn:
                        row.append(InlineKeyboardButton(text=text, url=btn["url"]))
                    elif "callback_data" in btn:
                        row.append(InlineKeyboardButton(text=text, callback_data=btn["callback_data"]))
                    else:
                        row.append(InlineKeyboardButton(text=text, callback_data=_telegram_feedback_callback(text)))
                else:
                    label = str(btn).strip()
                    if label:
                        row.append(InlineKeyboardButton(text=label, callback_data=_telegram_feedback_callback(label)))
            if row:
                rows.append(row)
        return InlineKeyboardMarkup(rows)

    row = []
    for btn in buttons:
        if isinstance(btn, dict):
            text = btn.get("text", "")
            if "url" in btn:
                row.append(InlineKeyboardButton(text=text, url=btn["url"]))
            elif "callback_data" in btn:
                row.append(InlineKeyboardButton(text=text, callback_data=btn["callback_data"]))
            else:
                row.append(InlineKeyboardButton(text=text, callback_data=_telegram_feedback_callback(text)))
        else:
            label = str(btn).strip()
            if label:
                row.append(InlineKeyboardButton(text=label, callback_data=_telegram_feedback_callback(label)))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(rows)


async def _handle_telegram_callback(platform: Any, query: Any, data: str) -> None:
    """Handle Telegram Callback Queries starting with 'po:'."""
    import json
    from datetime import datetime, timezone
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    parts = data.split(":")
    if len(parts) < 2:
        await query.answer()
        return

    action = parts[1]

    if action == "location":
        await query.answer()
        if len(parts) >= 3:
            loc = parts[2]
            _handle_location_update({"location": loc, "source": "telegram-callback"})
            cleanup_res = _run_auto_cleanup_routines()
            logs = cleanup_res.get("logs", [])

            msg = f"📍 <b>Location updated to: {loc}</b>"
            if logs:
                msg += "\n\n🧹 Auto-Cleanup triggered:\n" + "\n".join([f"• {_escape_html(l)}" for l in logs])

            loc_buttons = [
                {"text": "📍 Arrived Home", "callback_data": "po:location:home"},
                {"text": "🏃 Left Home", "callback_data": "po:location:away"}
            ]
            markup = _build_telegram_reply_markup(loc_buttons)
            await query.message.reply_text(msg, parse_mode="HTML", reply_markup=markup)

    elif action == "task_complete":
        if len(parts) >= 3:
            task_id = parts[2]
            try:
                with _http_client() as client:
                    url = f"{TODOIST_BASE}/tasks/{task_id}/close"
                    resp = client.post(url, headers=_todoist_headers())
                    resp.raise_for_status()

                await query.answer(text="✅ Task completed!")
                text = query.message.text or ""
                new_text = text + "\n\n✅ <b>Task Completed!</b>"
                await query.edit_message_text(new_text, parse_mode="HTML", reply_markup=None)
            except Exception as e:
                await query.answer(text=f"❌ Failed to complete task: {e}")

    elif action == "task_defer":
        if len(parts) >= 3:
            task_id = parts[2]
            try:
                # Increment task deferral count in operator state
                try:
                    op_state = _operator_read_state()
                    postpone_counts = op_state.setdefault("task_postpone_counts", {})
                    postpone_counts[task_id] = postpone_counts.get(task_id, 0) + 1
                    _operator_write_state(op_state)
                except Exception:
                    pass

                with _http_client() as client:
                    url = f"{TODOIST_BASE}/tasks/{task_id}"
                    payload = {"due_string": "tomorrow morning"}
                    resp = client.post(url, headers=_todoist_headers(), json=payload)
                    resp.raise_for_status()

                await query.answer(text="📅 Task deferred to tomorrow morning!")
                text = query.message.text or ""
                new_text = text + "\n\n📅 <b>Task Deferred to tomorrow morning!</b>"
                await query.edit_message_text(new_text, parse_mode="HTML", reply_markup=None)
            except Exception as e:
                await query.answer(text=f"❌ Failed to defer task: {e}")

    elif action == "task_someday":
        if len(parts) >= 3:
            task_id = parts[2]
            try:
                with _http_client() as client:
                    # Fetch projects map to find the ID of Someday/Maybe if exists
                    projects_map = _get_projects_map()
                    someday_project_id = None
                    for p_id, p_name in projects_map.items():
                        if "someday" in p_name.lower():
                            someday_project_id = p_id
                            break

                    url = f"{TODOIST_BASE}/tasks/{task_id}"
                    payload = {"due_string": ""}
                    if someday_project_id:
                        payload["project_id"] = someday_project_id

                    resp = client.post(url, headers=_todoist_headers(), json=payload)
                    resp.raise_for_status()

                await query.answer(text="💤 Task parked guilt-free in Someday/Maybe!")
                text = query.message.text or ""
                new_text = text + "\n\n💤 <b>Task parked guilt-free in Someday/Maybe!</b>"
                await query.edit_message_text(new_text, parse_mode="HTML", reply_markup=None)
            except Exception as e:
                await query.answer(text=f"❌ Failed to park task: {e}")

    elif action == "task_shrink":
        if len(parts) >= 3:
            task_id = parts[2]
            try:
                with _http_client() as client:
                    t_url = f"{TODOIST_BASE}/tasks/{task_id}"
                    t_resp = client.get(t_url, headers=_todoist_headers())
                    t_resp.raise_for_status()
                    task_data = t_resp.json() or {}

                    content = task_data.get("content", "").strip()
                    if "[2-Min Micro Step]" not in content:
                        content = f"[2-Min Micro Step] {content}"

                    payload = {
                        "content": content,
                        "due_string": "today"
                    }
                    resp = client.post(t_url, headers=_todoist_headers(), json=payload)
                    resp.raise_for_status()

                await query.answer(text="⚡ Task shrunk to 2-Min Micro Step!")
                text = query.message.text or ""
                new_text = text + "\n\n⚡ <b>Task shrunk to 2-Min Micro Step!</b>"
                await query.edit_message_text(new_text, parse_mode="HTML", reply_markup=None)
            except Exception as e:
                await query.answer(text=f"❌ Failed to shrink task: {e}")

    elif action == "task_delete":
        if len(parts) >= 3:
            task_id = parts[2]
            try:
                with _http_client() as client:
                    url = f"{TODOIST_BASE}/tasks/{task_id}"
                    resp = client.delete(url, headers=_todoist_headers())
                    resp.raise_for_status()

                await query.answer(text="🗑️ Task archived/deleted!")
                text = query.message.text or ""
                new_text = text + "\n\n🗑️ <b>Task Archived/Deleted!</b>"
                await query.edit_message_text(new_text, parse_mode="HTML", reply_markup=None)
            except Exception as e:
                await query.answer(text=f"❌ Failed to delete task: {e}")

    elif action == "show_list":
        await query.answer()
        if len(parts) >= 3:
            list_type = parts[2]
            proj_id = parts[3] if len(parts) >= 4 and parts[3] != "none" else None

            tasks = []
            title = ""
            try:
                if list_type == "inbox":
                    projects_map = _get_projects_map()
                    inbox_proj_id = None
                    for pid, name in projects_map.items():
                        if name.lower() == "inbox":
                            inbox_proj_id = pid
                            break
                    if inbox_proj_id:
                        with _http_client() as client:
                            resp = client.get(f"{TODOIST_BASE}/tasks", headers=_todoist_headers(), params={"project_id": inbox_proj_id})
                            tasks = (resp.json() or {}).get("results") or []
                    title = "📥 <b>Todoist Inbox Tasks</b>"
                elif list_type == "errands":
                    tasks = _focus_guard_read_todoist_tasks(filter="errands | errand")
                    title = "🏃 <b>Errands Tasks</b>"
                elif list_type == "today":
                    tasks = _focus_guard_read_todoist_tasks(filter="today | overdue")
                    title = "📅 <b>Today's View Tasks</b>"
                elif list_type == "work":
                    if proj_id:
                        with _http_client() as client:
                            resp = client.get(f"{TODOIST_BASE}/tasks", headers=_todoist_headers(), params={"project_id": proj_id})
                            tasks = (resp.json() or {}).get("results") or []
                    else:
                        tasks = _focus_guard_read_todoist_tasks(filter="today & #work")
                    title = "💼 <b>Work Projects Tasks</b>"
                elif list_type == "personal":
                    if proj_id:
                        with _http_client() as client:
                            resp = client.get(f"{TODOIST_BASE}/tasks", headers=_todoist_headers(), params={"project_id": proj_id})
                            tasks = (resp.json() or {}).get("results") or []
                    else:
                        tasks = _focus_guard_read_todoist_tasks(filter="today & #personal")
                    title = "🏠 <b>Personal Tasks</b>"
                elif list_type == "project":
                    if proj_id:
                        with _http_client() as client:
                            resp = client.get(f"{TODOIST_BASE}/tasks", headers=_todoist_headers(), params={"project_id": proj_id})
                            tasks = (resp.json() or {}).get("results") or []
                        projects_map = _get_projects_map()
                        proj_name = projects_map.get(proj_id, "Project")
                        title = f"💼 <b>{proj_name} Tasks</b>"
                elif list_type == "low_energy":
                    tasks = _focus_guard_read_todoist_tasks(filter="@low_energy | low_energy")
                    title = "🍵 <b>Low Energy Tasks</b>"
                elif list_type == "deep_work":
                    tasks = _focus_guard_read_todoist_tasks(filter="@deep_work | deep_work")
                    title = "⚡ <b>Deep Work Tasks</b>"

                if not tasks:
                    msg = f"{title}\n\n✅ <b>No active tasks in this view!</b>"
                    await query.message.reply_text(msg, parse_mode="HTML")
                else:
                    lines = [title, ""]
                    buttons = []
                    for idx, t in enumerate(tasks[:5], 1):
                        t_id = t.get("id")
                        content = t.get("content", "").strip()
                        escaped_content = _escape_html(content)
                        lines.append(f"{idx}️⃣ {escaped_content}")
                        if t_id:
                            buttons.append({"text": f"✅ {idx}", "callback_data": f"po:task_complete:{t_id}"})
                            buttons.append({"text": f"📅 {idx}", "callback_data": f"po:task_defer:{t_id}"})

                    markup = _build_telegram_reply_markup(buttons)
                    await query.message.reply_text("\n".join(lines), parse_mode="HTML", reply_markup=markup)
            except Exception as e:
                await query.answer(text=f"❌ Failed to fetch list: {e}")

    elif action == "review_anchors":
        await query.answer()
        try:
            all_tasks = _focus_guard_read_todoist_tasks()
            family_anchors = []
            fitness_anchors = []
            for t in all_tasks:
                role = _classify_task_role(t)
                if role == "family_anchor":
                    family_anchors.append(t)
                elif role == "fitness_anchor" or "fitness_anchor" in [l.lower() for l in t.get("labels") or []]:
                    fitness_anchors.append(t)

            lines = ["⚓ <b>Your Sacred Protected Anchors:</b>", ""]
            if not family_anchors and not fitness_anchors:
                lines.append("No active family or fitness anchors scheduled!")
            else:
                if family_anchors:
                    lines.append("<b>🌸 Family & Life Anchors:</b>")
                    for t in family_anchors:
                        content = _escape_html(t.get("content", ""))
                        t_id = t.get("id")
                        if t_id:
                            lines.append(f"  • <a href=\"https://app.todoist.com/app/task/{t_id}\">{content}</a>")
                        else:
                            lines.append(f"  • {content}")
                    lines.append("")
                if fitness_anchors:
                    lines.append("<b>💪 Fitness & Gym Anchors:</b>")
                    for t in fitness_anchors:
                        content = _escape_html(t.get("content", ""))
                        t_id = t.get("id")
                        if t_id:
                            lines.append(f"  • <a href=\"https://app.todoist.com/app/task/{t_id}\">{content}</a>")
                        else:
                            lines.append(f"  • {content}")

            await query.message.reply_text("\n".join(lines), parse_mode="HTML")
        except Exception as e:
            await query.message.reply_text(f"❌ Failed to fetch anchors: {e}", parse_mode="HTML")

    elif action == "nudge_mute":
        if len(parts) >= 3:
            # Mute for 1 hour (3600 sec)
            now_ts = int(time.time())
            mute_until = now_ts + 3600
            operator_state = _operator_read_state()
            nudge_state = operator_state.setdefault("nudge_fatigue", {})
            nudge_state["mute_until_ts"] = mute_until
            _operator_write_state(operator_state)
            await query.answer(text="🔕 Nudges muted for 1 hour!")
            await query.message.reply_text("🔕 <b>Nudges muted for 1 hour.</b>", parse_mode="HTML")

    elif action == "sprint":
        if len(parts) >= 3 and parts[2] == "start":
            await query.answer(text="⚡ 5-minute sprint started! Focus!")
            now_ts = int(time.time())
            operator_state = _operator_read_state()
            operator_state["active_sprint"] = {"started_at": now_ts, "duration": 300}
            _operator_write_state(operator_state)
            await query.message.reply_text("⚡ <b>5-minute sprint started! Go go go!</b>", parse_mode="HTML")

    elif action == "defer_all_today":
        try:
            cleanup_res = _run_auto_cleanup_routines()
            logs = cleanup_res.get("logs", [])
            msg = "🔄 <b>Deferred today's remaining tasks:</b>\n"
            if logs:
                msg += "\n".join([f"• {_escape_html(l)}" for l in logs])
            else:
                msg += "No remaining tasks required deferral."
            await query.answer(text="🔄 Deferred today's tasks!")
            await query.message.reply_text(msg, parse_mode="HTML")
        except Exception as e:
            await query.answer(text=f"❌ Failed to defer: {e}")

    elif action == "briefing":
        if len(parts) >= 3:
            sub = parts[2]
            if sub == "triage":
                await query.answer()
                all_tasks = _focus_guard_read_todoist_tasks()
                from datetime import date
                tz = _runtime_local_tz()
                today_date = datetime.now(tz).date()
                overdue = []
                for t in all_tasks:
                    due_info = t.get("due") or {}
                    due_date_str = due_info.get("date")
                    if due_date_str:
                        try:
                            date_part = due_date_str.split("T")[0]
                            task_due_date = date.fromisoformat(date_part)
                            if task_due_date <= today_date:
                                overdue.append(t)
                        except Exception:
                            pass
                if not overdue:
                    await query.message.reply_text("<b>🧹 Triage Complete</b>\nYou have no overdue tasks to triage! Sleep well. ✨", parse_mode="HTML")
                else:
                    first = overdue[0]
                    t_id = first.get("id")
                    escaped_content = _escape_html(first.get("content", "").strip())
                    msg = f"<b>🧹 Overdue Triage (1 of {len(overdue)})</b>\n\nTask: <b>{escaped_content}</b>"
                    buttons = [
                        {"text": "✅ Complete", "callback_data": f"po:task_complete:{t_id}"},
                        {"text": "📅 Defer (Tomorrow)", "callback_data": f"po:task_defer:{t_id}"},
                        {"text": "🗑️ Delete", "callback_data": f"po:task_delete:{t_id}"}
                    ]
                    markup = _build_telegram_reply_markup(buttons)
                    await query.message.reply_text(msg, parse_mode="HTML", reply_markup=markup)

            elif sub == "quiet":
                await query.answer(text="Quiet mode activated.")
                await query.edit_message_text(
                    "<b>🌙 Quiet Mode Active</b>\n\nTask previews skipped for tonight. Rest well and protect your nervous system! 💤",
                    parse_mode="HTML",
                    reply_markup=None
                )

            elif sub == "top3":
                await query.answer()
                all_tasks = _focus_guard_read_todoist_tasks()
                from datetime import date
                tz = _runtime_local_tz()
                today_date = datetime.now(tz).date()
                tomorrow_date = today_date + timedelta(days=1)
                tomorrow_tasks = []
                for t in all_tasks:
                    due_info = t.get("due") or {}
                    due_date_str = due_info.get("date")
                    if due_date_str:
                        try:
                            date_part = due_date_str.split("T")[0]
                            task_due_date = date.fromisoformat(date_part)
                            if task_due_date == tomorrow_date:
                                tomorrow_tasks.append(t)
                        except Exception:
                            pass

                focus_tasks = [t for t in tomorrow_tasks if _classify_task_role(t) == "focus"]
                if not focus_tasks:
                    focus_tasks = tomorrow_tasks[:3]
                else:
                    focus_tasks = focus_tasks[:3]

                lines = [
                    "<b>📅 Tomorrow's Top 3 Priorities:</b>",
                    "Here are your protected focus priorities for tomorrow:",
                    ""
                ]
                for t in focus_tasks:
                    t_id = t.get("id")
                    escaped_content = _escape_html(t.get("content", "").strip())
                    if t_id:
                        lines.append(f"  • <a href=\"https://app.todoist.com/app/task/{t_id}\">{escaped_content}</a>")
                    else:
                        lines.append(f"  • {escaped_content}")
                lines.append("\n<i>Nothing else needs sorting tonight. Enjoy a restful evening! 🌟</i>")
                await query.edit_message_text("\n".join(lines), parse_mode="HTML", reply_markup=None, disable_web_page_preview=True)
            else:
                await query.answer()
        else:
            await query.answer()

    elif action == "stuck":
        if len(parts) >= 3:
            sub = parts[2]
            if len(parts) >= 4:
                task_id = parts[3]
                try:
                    if sub == "shrink":
                        all_tasks = _focus_guard_read_todoist_tasks()
                        task_title = "stuck task"
                        for t in all_tasks:
                            if t.get("id") == task_id:
                                task_title = t.get("content", "stuck task")
                                break
                        await query.answer()
                        msg = (
                            f"<b>⚡ Stuck Task Intervention</b>\n\n"
                            f"Let's break down <b>\"{_escape_html(task_title)}\"</b> into a smaller 2-minute step.\n\n"
                            f"<i>Tomorrow morning: write down one tiny, concrete next action (like 'Open document' or 'Draft email introduction') and do strictly that first!</i>"
                        )
                        await query.message.reply_text(msg, parse_mode="HTML")

                    elif sub == "someday":
                        all_tasks = _focus_guard_read_todoist_tasks()
                        target_task = None
                        for t in all_tasks:
                            if t.get("id") == task_id:
                                target_task = t
                                break

                        if target_task:
                            current_labels = target_task.get("labels") or []
                            new_labels = list(set(current_labels + ["someday"]))
                            with _http_client() as client:
                                url = f"{TODOIST_BASE}/tasks/{task_id}"
                                payload = {"due_string": "no date", "labels": new_labels}
                                resp = client.post(url, headers=_todoist_headers(), json=payload)
                                resp.raise_for_status()

                        await query.answer(text="Task moved to Someday/Maybe!")
                        text = query.message.text or ""
                        new_text = text + "\n\n💤 <b>Task moved to Someday/Maybe (due date removed, labeled @someday)</b>"
                        await query.edit_message_text(new_text, parse_mode="HTML", reply_markup=None)

                    elif sub == "delete":
                        with _http_client() as client:
                            url = f"{TODOIST_BASE}/tasks/{task_id}"
                            resp = client.delete(url, headers=_todoist_headers())
                            resp.raise_for_status()

                        await query.answer(text="Task deleted!")
                        text = query.message.text or ""
                        new_text = text + "\n\n🗑️ <b>Task Deleted!</b>"
                        await query.edit_message_text(new_text, parse_mode="HTML", reply_markup=None)
                except Exception as e:
                    await query.answer(text=f"❌ Action failed: {e}")
            else:
                await query.answer()
        else:
            await query.answer()

    else:
        await query.answer()


def _focus_guard_send_telegram_message(
    text: str,
    *,
    chat_id: Optional[str] = None,
    buttons: Optional[List[Any]] = None,
    force: bool = False,
    parse_mode: Optional[str] = None,
) -> Dict[str, Any]:
    message_text = str(text or "").strip()
    if not message_text:
        raise ValueError("text is required")
    if not force and not _telegram_messages_allowed_now():
        return {"ok": True, "suppressed": True, "reason": "quiet_hours"}

    _, default_chat_id = _focus_guard_telegram_config()
    target_chat_id = str(chat_id or default_chat_id).strip()
    payload: Dict[str, Any] = {"chat_id": target_chat_id, "text": message_text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    reply_markup = _telegram_inline_keyboard(buttons)
    if reply_markup:
        payload["reply_markup"] = reply_markup
    return _focus_guard_telegram_post("sendMessage", payload)


def _focus_guard_build_telegram_message(
    *,
    most_important_task: Optional[Dict[str, Any]],
    suspicious_tasks: List[Dict[str, Any]],
) -> str:
    lines: List[str] = []
    if most_important_task:
        lines.append(f"Focus Guard: most important task is '{most_important_task.get('content', '')}'.")
    for item in suspicious_tasks:
        task = item.get("task") or {}
        classification = item.get("classification") or {}
        lines.append(
            f"Suspicious task: '{task.get('content', '')}' ({classification.get('label', 'suspicious')}) - {classification.get('reason', '')}"
        )
    return "\n".join(line for line in lines if line).strip()


def _focus_guard_run_once(*, filter: Optional[str] = None) -> Dict[str, Any]:
    tasks = _focus_guard_read_todoist_tasks(filter=filter)
    status = "needs_focus" if tasks else "idle"
    payload = _focus_guard_state_payload(tasks=tasks, status=status)

    prior_state = _focus_guard_read_state()
    prior_processed_ids = {
        str(task_id).strip()
        for task_id in (prior_state.get("processed_suspicious_task_ids") or [])
        if str(task_id).strip()
    }

    suspicious_tasks = payload.get("suspicious_tasks") or []
    suspicious_task_ids = [
        str((item.get("task") or {}).get("id") or "").strip()
        for item in suspicious_tasks
        if str((item.get("task") or {}).get("id") or "").strip()
    ]
    new_suspicious_tasks = []
    for item in suspicious_tasks:
        task = item.get("task") or {}
        task_id = str(task.get("id") or "").strip()
        if task_id and task_id not in prior_processed_ids:
            new_suspicious_tasks.append(item)

    payload["processed_suspicious_task_ids"] = sorted(prior_processed_ids)

    _focus_guard_write_state(payload)

    notified_suspicious_task_ids = [
        str((item.get("task") or {}).get("id") or "").strip()
        for item in new_suspicious_tasks
        if str((item.get("task") or {}).get("id") or "").strip()
    ]

    if new_suspicious_tasks:
        _focus_guard_send_telegram_message(
            _focus_guard_build_telegram_message(
                most_important_task=payload.get("most_important_task"),
                suspicious_tasks=new_suspicious_tasks,
            )
        )
        payload["processed_suspicious_task_ids"] = sorted(prior_processed_ids.union(suspicious_task_ids))
        _focus_guard_write_state(payload)

    most_important_task = payload.get("most_important_task") or {}
    _focus_guard_append_event(
        "focus_guard_run",
        {
            "status": status,
            "task_count": len(tasks),
            "most_important_task_id": str(most_important_task.get("id") or "").strip() or None,
            "notified_suspicious_task_ids": notified_suspicious_task_ids,
        },
    )
    return _canonical_focus_guard_result(
        {
        "status": status,
        "task_count": len(tasks),
        "most_important_task": payload.get("most_important_task"),
        "suspicious_task_ids": suspicious_task_ids,
        "notified_suspicious_task_ids": notified_suspicious_task_ids,
        "processed_suspicious_task_ids": payload.get("processed_suspicious_task_ids") or [],
        "generated_at": payload.get("generated_at"),
        }
    )


def _canonical_focus_guard_result(result: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(result or {})
    return {
        "status": str(payload.get("status") or "unknown"),
        "task_count": int(payload.get("task_count") or 0),
        "most_important_task": payload.get("most_important_task"),
        "suspicious_tasks": list(payload.get("suspicious_tasks") or []),
        "suspicious_task_ids": list(payload.get("suspicious_task_ids") or []),
        "notified_suspicious_task_ids": list(payload.get("notified_suspicious_task_ids") or []),
        "processed_suspicious_task_ids": list(payload.get("processed_suspicious_task_ids") or []),
        "generated_at": payload.get("generated_at"),
    }


def _summarize_focus_guard_result(result: Dict[str, Any], *, source: str = "run") -> str:
    result = _canonical_focus_guard_result(result)
    task_count = int(result.get("task_count") or 0)
    suspicious_count = len(result.get("suspicious_task_ids") or [])
    most_important_task = result.get("most_important_task") or {}
    most_important_label = str(most_important_task.get("content") or "").strip()

    if source == "status":
        parts = [
            f"Focus Guard saved state shows {task_count} Todoist task(s).",
            f"Status: {result.get('status') or 'unknown'}.",
        ]
    else:
        parts = [
            f"Focus Guard scanned {task_count} Todoist task(s).",
            f"Status: {result.get('status') or 'unknown'}.",
        ]
    if most_important_label:
        parts.append(f"Most important task: {most_important_label}.")
    suspicious_labels = [
        str(((item.get("task") or {}).get("content") or "")).strip()
        for item in list(result.get("suspicious_tasks") or [])[:3]
        if str(((item.get("task") or {}).get("content") or "")).strip()
    ]
    if suspicious_labels:
        parts.append(f"Flagged side task(s): {', '.join(suspicious_labels)}.")
    parts.append(f"Found {suspicious_count} suspicious task(s) needing attention.")
    return " ".join(parts)


def _focus_guard_result_from_state(state: Dict[str, Any]) -> Dict[str, Any]:
    suspicious_task_ids = [
        str((item.get("task") or {}).get("id") or "").strip()
        for item in (state.get("suspicious_tasks") or [])
        if str((item.get("task") or {}).get("id") or "").strip()
    ]
    return _canonical_focus_guard_result({
        "status": str(state.get("status") or "unknown"),
        "task_count": int(state.get("task_count") or 0),
        "most_important_task": state.get("most_important_task"),
        "suspicious_task_ids": suspicious_task_ids,
        "notified_suspicious_task_ids": [],
        "processed_suspicious_task_ids": state.get("processed_suspicious_task_ids") or [],
        "generated_at": state.get("generated_at"),
    })


def _load_approvals() -> Dict[str, Any]:
    data = _read_json(APPROVALS_PATH, {"pending": {}, "history": []})
    if not isinstance(data, dict):
        return {"pending": {}, "history": []}
    data.setdefault("pending", {})
    data.setdefault("history", [])
    return data


def _save_approvals(data: Dict[str, Any]) -> None:
    _write_json(APPROVALS_PATH, data)


def _env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if value:
        return value
    env_path = HERMES_HOME / ".env"
    try:
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            if not raw or raw.lstrip().startswith("#") or "=" not in raw:
                continue
            key, val = raw.split("=", 1)
            if key.strip() == name:
                return val.strip()
    except Exception:
        pass
    return ""


def _env_first(*names: str) -> str:
    for name in names:
        value = _env(name)
        if value:
            return value
    return ""


def _http_client() -> httpx.Client:
    return httpx.Client(timeout=30.0, follow_redirects=True)


def _mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return value[:4] + "..." + value[-4:]


def _read_yaml(path: Path, default: Any) -> Any:
    if yaml is None:
        return default
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _runtime_service_status(service_name: str = RUNTIME_SERVICE_NAME) -> Dict[str, Any]:
    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-active", service_name],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        state = (result.stdout or result.stderr or "").strip() or "unknown"
        return {
            "service": service_name,
            "active": state == "active",
            "state": state,
            "returncode": result.returncode,
            "active_since": _runtime_active_since(service_name),
        }
    except Exception as exc:
        return {
            "service": service_name,
            "active": False,
            "state": "unavailable",
            "error": str(exc),
        }


def _runtime_active_since(service_name: str = RUNTIME_SERVICE_NAME) -> Optional[str]:
    try:
        result = subprocess.run(
            ["systemctl", "--user", "show", service_name, "--property=ActiveEnterTimestamp", "--value"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        value = (result.stdout or result.stderr or "").strip()
        return value or None
    except Exception:
        return None


def _runtime_journal_lines(
    service_name: str = RUNTIME_SERVICE_NAME,
    lines: int = 200,
    since: Optional[str] = None,
) -> List[str]:
    try:
        command = ["journalctl", "--user", "-u", service_name]
        if since:
            command.extend(["--since", since])
        command.extend(["-n", str(lines), "--no-pager"])
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        output = result.stdout if result.stdout else result.stderr
        return [line for line in output.splitlines() if line.strip()]
    except Exception:
        return []


def _runtime_incidents_from_lines(lines: List[str]) -> List[Dict[str, Any]]:
    incidents: List[Dict[str, Any]] = []
    for raw_line in lines:
        line = str(raw_line or "").strip()
        lower = line.lower()
        if not line:
            continue
        if "http 429" in lower or "tokens per minute limit exceeded" in lower:
            incidents.append({"kind": "rate_limit", "summary": "Provider rate limit hit", "raw": line})
        elif "http 413" in lower or "request too large for model" in lower:
            incidents.append({"kind": "request_too_large", "summary": "Fallback request exceeded model limits", "raw": line})
        elif "cannot compress further" in lower:
            incidents.append({"kind": "compression_failed", "summary": "Conversation compaction could not shrink context enough", "raw": line})
        elif "sms_webhook_url is required" in lower:
            incidents.append({"kind": "sms_misconfigured", "summary": "SMS gateway adapter is enabled without webhook configuration", "raw": line})
        elif "failed to detach context" in lower or "opentelemetry.context" in lower:
            incidents.append({"kind": "observability_error", "summary": "Langfuse/OpenTelemetry context error", "raw": line})
    return incidents


def _runtime_recent_incidents(limit: int = 20, service_name: str = RUNTIME_SERVICE_NAME) -> List[Dict[str, Any]]:
    since = _runtime_active_since(service_name)
    lines = _runtime_journal_lines(service_name=service_name, lines=max(limit * 8, 80), since=since)
    incidents = _runtime_incidents_from_lines(lines)
    if len(incidents) <= limit:
        return incidents
    return incidents[-limit:]


def _runtime_provider_chain(path: Path = HERMES_CONFIG_PATH) -> Dict[str, Any]:
    data = _read_yaml(path, {}) or {}
    model_cfg = data.get("model") or {}
    compression_cfg = data.get("compression") or {}
    fallbacks = data.get("fallback_providers") or []
    plugins_cfg = data.get("plugins") or {}
    enabled_plugins = plugins_cfg.get("enabled") or []
    return {
        "primary": {
            "provider": model_cfg.get("provider"),
            "model": model_cfg.get("default"),
        },
        "fallbacks": [
            {"provider": item.get("provider"), "model": item.get("model")}
            for item in fallbacks
            if isinstance(item, dict)
        ],
        "compression": {
            "protect_last_n": compression_cfg.get("protect_last_n"),
            "hygiene_hard_message_limit": compression_cfg.get("hygiene_hard_message_limit"),
        },
        "plugins_enabled": enabled_plugins if isinstance(enabled_plugins, list) else [],
    }


def _runtime_isolation_profile_plan(args: Dict[str, Any]) -> Dict[str, Any]:
    from plugins.personal_ops.orchestration_kernel import profiles_as_dict

    profiles = profiles_as_dict()
    requested = args.get("profile_name") or args.get("profile")
    if requested:
        profile_name = str(requested).strip()
        profiles = {profile_name: profiles[profile_name]} if profile_name in profiles else {}
    return {
        "success": True,
        "action": "isolation_profile_plan",
        "profiles": profiles,
        "summary": "Hermes profiles isolate personal ops, engineering, business, finance, and experiments so tools/context do not bleed across risk domains.",
    }


def _runtime_intention_gate(args: Dict[str, Any]) -> Dict[str, Any]:
    from plugins.personal_ops.orchestration_kernel import evaluate_intention

    intent = str(args.get("intent") or args.get("request") or args.get("title") or "").strip()
    profile_name = str(args.get("profile_name") or args.get("profile") or "personal").strip()
    decision = evaluate_intention(intent, profile_name=profile_name)
    _append_event(
        "intention_gate",
        {
            "profile_name": decision.profile_name,
            "allowed": decision.allowed,
            "approval_required": decision.approval_required,
            "blocked_terms": decision.blocked_terms,
        },
    )
    return {"success": True, "action": "intention_gate", "decision": decision.to_dict()}


def _runtime_orchestration_job(args: Dict[str, Any]) -> Dict[str, Any]:
    from plugins.personal_ops.orchestration_kernel import build_dispatch_plan, job_board_status, record_job

    mode = str(args.get("mode") or "status").strip().lower()
    if mode == "status":
        status = job_board_status(db_path=ORCHESTRATION_JOBS_DB_PATH, limit=int(args.get("limit") or 25))
        return {"success": True, "action": "orchestration_job", "mode": mode, **status}
    if mode == "plan":
        plan = build_dispatch_plan(
            title=str(args.get("title") or "Untitled Hermes job"),
            intent=str(args.get("intent") or ""),
            profile_name=str(args.get("profile_name") or args.get("profile") or "personal"),
        )
        return {"success": True, "action": "orchestration_job", "mode": mode, "dispatch_plan": plan}
    if mode == "create":
        job = record_job(
            db_path=ORCHESTRATION_JOBS_DB_PATH,
            profile_name=str(args.get("profile_name") or args.get("profile") or "personal"),
            title=str(args.get("title") or "Untitled Hermes job"),
            intent=str(args.get("intent") or ""),
            status=str(args.get("status") or "proposed"),
        )
        _append_event(
            "orchestration_job_created",
            {
                "job_id": job.get("job_id"),
                "profile_name": job.get("profile_name"),
                "status": job.get("status"),
                "approval_required": ((job.get("decision") or {}).get("approval_required")),
            },
        )
        return {
            "success": True,
            "action": "orchestration_job",
            "mode": mode,
            "job": job,
            "dispatch_plan": job.get("dispatch_plan"),
        }
    raise ValueError(f"Unsupported orchestration_job mode: {mode}")


def _runtime_summary(service: Dict[str, Any], incidents: List[Dict[str, Any]]) -> str:
    state = service.get("state")
    if not state:
        state = "active" if service.get("active") else "unknown"
    incident_count = len(incidents)
    qualifier = "current" if service.get("active_since") else "recent"
    return f"Hermes gateway is {state}. Found {incident_count} {qualifier} incident(s)."


def _runtime_default_repo_path() -> Path:
    configured = _env("HERMES_AGENT_REPO_PATH")
    if configured:
        return Path(configured).expanduser()
    common = Path("/home/ubuntu/hermes-agent")
    if common.exists():
        return common
    return Path.cwd()


def _runtime_git_output(repo_path: Path, args: List[str], *, timeout: int = 20) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_path), *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
        output = (result.stdout or result.stderr or "").strip()
        return result.returncode == 0, output
    except Exception as exc:
        return False, str(exc)


def _runtime_local_git_status(repo_path: Path) -> Dict[str, Any]:
    repo_path = Path(repo_path)
    fetch_ok, fetch_output = _runtime_git_output(repo_path, ["fetch", "origin"], timeout=45)
    behind_ok, behind_output = _runtime_git_output(repo_path, ["rev-list", "--count", "HEAD..origin/main"])
    head_ok, head_output = _runtime_git_output(repo_path, ["rev-parse", "--short", "HEAD"])
    origin_ok, origin_output = _runtime_git_output(repo_path, ["rev-parse", "--short", "origin/main"])
    behind: Optional[int] = None
    if behind_ok:
        try:
            behind = int(str(behind_output).strip())
        except ValueError:
            behind = None
    return {
        "repo_path": str(repo_path),
        "fetch_ok": fetch_ok,
        "fetch_output": fetch_output if not fetch_ok else "",
        "behind": behind,
        "head": head_output if head_ok else None,
        "origin_main": origin_output if origin_ok else None,
    }


def _runtime_fetch_recent_commits(*, hours: int = 24, repo: str = "NousResearch/hermes-agent") -> List[Dict[str, Any]]:
    since = (datetime.now(timezone.utc) - timedelta(hours=max(int(hours), 1))).isoformat().replace("+00:00", "Z")
    commits: List[Dict[str, Any]] = []
    page = 1
    with _http_client() as client:
        while page <= 10:
            resp = client.get(
                f"https://api.github.com/repos/{repo}/commits",
                headers={"Accept": "application/vnd.github+json", "User-Agent": "Hermes personal runtime watcher"},
                params={"since": since, "per_page": 100, "page": page},
            )
            resp.raise_for_status()
            payload = resp.json() or []
            for item in payload:
                commit = item.get("commit") or {}
                author = commit.get("author") or {}
                message = str(commit.get("message") or "").splitlines()[0].strip()
                commits.append(
                    {
                        "sha": str(item.get("sha") or "")[:12],
                        "message": message,
                        "author": author.get("name"),
                        "date": author.get("date"),
                        "url": item.get("html_url"),
                    }
                )
            link_header = str(resp.headers.get("link") or "")
            if 'rel="next"' not in link_header:
                break
            page += 1
    return commits


def _runtime_upstream_summary(status: Dict[str, Any]) -> str:
    hours = int(status.get("hours") or 24)
    count = int(status.get("recent_commit_count") or 0)
    behind = (status.get("local") or {}).get("behind")
    if count:
        lead = f"Hermes upstream changed: {count} commit(s) in the last {hours}h."
    else:
        lead = f"No Hermes upstream commits in the last {hours}h."
    if behind is None:
        tail = "Local checkout status could not be determined."
    elif int(behind) > 0:
        tail = f"Local checkout is {behind} commit(s) behind origin/main."
    else:
        tail = "Local checkout is current with origin/main."
    commits = list(status.get("recent_commits") or [])
    if commits:
        latest = str((commits[0] or {}).get("message") or "").strip()
        if latest:
            return f"{lead} Latest: {latest}. {tail}"
    return f"{lead} {tail}"


def _runtime_upstream_status(
    *,
    hours: int = 24,
    repo_path: Optional[Path] = None,
    repo: str = "NousResearch/hermes-agent",
) -> Dict[str, Any]:
    resolved_repo_path = Path(repo_path) if repo_path is not None else _runtime_default_repo_path()
    commits = _runtime_fetch_recent_commits(hours=hours, repo=repo)
    local = _runtime_local_git_status(resolved_repo_path)
    status = {
        "repo": repo,
        "hours": int(hours),
        "recent_commit_count": len(commits),
        "recent_commits": commits[:10],
        "local": local,
    }
    status["summary"] = _runtime_upstream_summary(status)
    return status


def _runtime_upstream_telegram_message(status: Dict[str, Any]) -> str:
    lines = ["Hermes Agent - Upstream Watch", str(status.get("summary") or "").strip()]
    for commit in list(status.get("recent_commits") or [])[:5]:
        sha = str(commit.get("sha") or "")[:7]
        message = str(commit.get("message") or "").strip()
        author = str(commit.get("author") or "").strip()
        suffix = f" ({author})" if author else ""
        lines.append(f"- {sha}: {message}{suffix}")
    return "\n".join(line for line in lines if line).strip()


def _runtime_write_event_state(data: Dict[str, Any]) -> None:
    _write_json(EVENT_ROUTER_STATE_PATH, data)


def _runtime_read_event_state() -> Dict[str, Any]:
    data = _read_json(EVENT_ROUTER_STATE_PATH, {"recent_events": [], "last_event": None})
    if not isinstance(data, dict):
        return {"recent_events": [], "last_event": None}
    data.setdefault("recent_events", [])
    data.setdefault("last_event", None)
    return data


def _runtime_local_tz() -> timezone:
    if ZoneInfo is not None:
        try:
            return ZoneInfo(HERMES_LOCAL_TIMEZONE)
        except Exception:
            pass
    return timezone.utc


def _presence_confidence_for_event(event_type: str, source: str) -> tuple[float, str]:
    source_l = source.lower()
    if event_type == "voice_memo_received" and "telegram" in source_l:
        return 0.85, "Telegram activity"
    if event_type == "wake" and "logon" in source_l:
        return 0.45, "Windows logon"
    if event_type == "desktop_unlocked":
        return 0.35, "desktop unlock signal"
    if event_type in {"leaving_house", "outing_request"}:
        return 0.70, "explicit outing request"
    return 0.50, event_type.replace("_", " ")


def _runtime_write_presence_signal(
    *,
    event_type: str,
    source: str,
    ts: datetime,
    override_confidence: Optional[float] = None,
    override_label: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    confidence, label = _presence_confidence_for_event(event_type, source)
    signal = {
        "ts": ts.isoformat(),
        "source": source,
        "event_type": event_type,
        "confidence": float(override_confidence if override_confidence is not None else confidence),
        "label": str(override_label or label),
    }
    if isinstance(extra, dict):
        for key, value in extra.items():
            if key not in {"ts", "source", "event_type"}:
                signal[key] = value
    state = _read_json(PRESENCE_STATE_PATH, {})
    if not isinstance(state, dict):
        state = {}
    state["last_signal"] = signal
    state["recent_signals"] = (list(state.get("recent_signals") or []) + [signal])[-20:]
    _write_json(PRESENCE_STATE_PATH, state)
    return signal


def _activitywatch_base_url() -> str:
    return _env_first("HERMES_ACTIVITYWATCH_BASE_URL", "ACTIVITYWATCH_BASE_URL").rstrip("/")


def _runtime_activitywatch_signal(*, now: Optional[datetime] = None) -> Dict[str, Any]:
    base_url = _activitywatch_base_url()
    if not base_url:
        return {"configured": False, "active": False, "confidence": 0.0}
    checked_at = now or datetime.now(timezone.utc)
    if checked_at.tzinfo is None:
        checked_at = checked_at.replace(tzinfo=timezone.utc)
    try:
        with _http_client() as client:
            afk_resp = client.get(f"{base_url}/api/0/buckets/aw-watcher-afk_/events", params={"limit": 1})
            afk_resp.raise_for_status()
            afk_events = afk_resp.json() or []
            window_resp = client.get(f"{base_url}/api/0/buckets/aw-watcher-window_/events", params={"limit": 1})
            window_resp.raise_for_status()
            window_events = window_resp.json() or []
    except Exception as exc:
        return {"configured": True, "active": False, "confidence": 0.0, "error": str(exc)}

    afk = afk_events[0] if afk_events else {}
    window = window_events[0] if window_events else {}
    afk_ts = _runtime_parse_iso(str(afk.get("timestamp") or ""))
    age_seconds = None
    if afk_ts is not None:
        age_seconds = max(int((checked_at - afk_ts).total_seconds()), 0)
    status = str(((afk.get("data") or {}).get("status")) or "").strip().lower()
    active = status == "not-afk" and (age_seconds is None or age_seconds <= 12 * 60 * 60)
    app_name = str(((window.get("data") or {}).get("app")) or "").strip().lower()
    title = str(((window.get("data") or {}).get("title")) or "").strip()
    category = "unknown"
    if app_name:
        if any(token in app_name for token in ["chrome", "firefox", "edge", "safari", "browser"]):
            category = "browser"
        elif any(token in app_name for token in ["code", "cursor", "pycharm", "idea", "studio"]):
            category = "editor"
        elif "todoist" in app_name or "todoist" in title.lower():
            category = "todoist"
        elif any(token in app_name for token in ["telegram", "discord", "slack", "signal"]):
            category = "messaging"
    confidence = 0.78 if active else 0.2
    if active and category in {"todoist", "editor", "browser"}:
        confidence = 0.82
    return {
        "configured": True,
        "active": active,
        "confidence": confidence,
        "last_activity_age_seconds": age_seconds,
        "active_category": category,
        "title_hint": title[:120] if title else "",
        "source": "activitywatch",
    }


def _runtime_presence_status(*, now: Optional[datetime] = None) -> Dict[str, Any]:
    # Evaluate global and plugin-specific bypass rules
    config_data = _read_yaml(HERMES_CONFIG_PATH, {}) or {}
    personal_ops_cfg = config_data.get("plugins", {}).get("personal_ops", {}) or {}
    bypass_presence = (
        bool(personal_ops_cfg.get("always_nudge_proactively")) or
        bool(personal_ops_cfg.get("proactive_bypass_presence")) or
        bool(personal_ops_cfg.get("always_nudge")) or
        bool(config_data.get("always_nudge_proactively")) or
        bool(config_data.get("proactive_bypass_presence")) or
        bool(config_data.get("always_nudge"))
    )

    rules_data = _read_json(TODOIST_RULES_PATH, {}) or {}
    bypass_presence = bypass_presence or (
        bool(rules_data.get("always_nudge_proactively")) or
        bool(rules_data.get("proactive_bypass_presence")) or
        bool(rules_data.get("always_nudge"))
    )

    state = _read_json(PRESENCE_STATE_PATH, {})
    if not isinstance(state, dict):
        state = {}
    activitywatch = _runtime_activitywatch_signal(now=now)
    signal = dict(state.get("last_signal") or {})
    checked_at = now or datetime.now(timezone.utc)
    if checked_at.tzinfo is None:
        checked_at = checked_at.replace(tzinfo=timezone.utc)
    if not signal:
        aw_confidence = float(activitywatch.get("confidence") or 0.0)
        if activitywatch.get("configured"):
            aw_level = "active_now" if aw_confidence >= PRESENCE_PROACTIVE_CONFIDENCE_MINIMUM else "weak"
            can_proactively = bool(activitywatch.get("active") and aw_confidence >= PRESENCE_PROACTIVE_CONFIDENCE_MINIMUM)
            if bypass_presence:
                can_proactively = True
            return {
                "configured": True,
                "confidence": aw_confidence,
                "raw_confidence": aw_confidence,
                "level": aw_level,
                "can_proactively_message": can_proactively,
                "summary": "Presence derived from ActivityWatch local activity; this indicates recent device activity, not certainty about attention or willingness to be interrupted.",
                "last_signal": None,
                "recent_signals": [],
                "activitywatch": activitywatch,
            }
        return {
            "configured": False,
            "confidence": None,
            "level": "unknown",
            "can_proactively_message": True,
            "summary": "No presence signal has been recorded yet; proactive messages fall back to schedule, Todoist state, and quiet hours.",
            "last_signal": None,
            "activitywatch": activitywatch,
        }
    parsed = _runtime_parse_iso(str(signal.get("ts") or ""))
    age_minutes: Optional[int] = None
    fresh = False
    messaging_fresh = False
    if parsed is not None:
        age_minutes = max(int((checked_at - parsed).total_seconds() // 60), 0)
        source_name = str(signal.get("source") or "")
        freshness_window = 12 * 60 if source_name == "activitywatch-forwarder" else PRESENCE_SIGNAL_TTL_MINUTES
        fresh = age_minutes <= freshness_window
        messaging_fresh = age_minutes <= PRESENCE_SIGNAL_TTL_MINUTES
    raw_confidence = float(signal.get("confidence") or 0)
    confidence = raw_confidence if fresh else 0.0
    level = "strong" if confidence >= PRESENCE_PROACTIVE_CONFIDENCE_MINIMUM else "weak"
    if not fresh:
        level = "stale"
    aw_confidence = float(activitywatch.get("confidence") or 0.0)
    if activitywatch.get("configured") and bool(activitywatch.get("active")) and aw_confidence > confidence:
        confidence = aw_confidence
        level = "active_now" if confidence >= PRESENCE_PROACTIVE_CONFIDENCE_MINIMUM else "weak"
        fresh = True
        messaging_fresh = True
    can_message = bool(messaging_fresh and confidence >= PRESENCE_PROACTIVE_CONFIDENCE_MINIMUM)
    if bypass_presence:
        can_message = True
    label = str(signal.get("label") or signal.get("event_type") or "activity signal")
    source = str(signal.get("source") or "unknown")
    summary = (
        f"Latest presence signal is {label} from {source}; confidence {confidence:.2f}. "
        "This is evidence of recent activity, not proof of exact device state or Telegram device type."
    )
    if not fresh:
        summary = f"Latest presence signal is stale; last useful signal was {label} from {source}."
    if bypass_presence:
        summary += " (Proactive outreach enabled by configuration bypass.)"
    return {
        "configured": True,
        "confidence": confidence,
        "raw_confidence": raw_confidence,
        "level": level,
        "fresh": fresh,
        "age_minutes": age_minutes,
        "can_proactively_message": can_message,
        "summary": summary,
        "last_signal": signal,
        "recent_signals": list(state.get("recent_signals") or []),
        "activitywatch": activitywatch,
    }


def _nudge_budget_local_date(now: datetime) -> str:
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now.astimezone(_runtime_local_tz()).date().isoformat()


def _nudge_budget_read_for_today(now: datetime) -> Dict[str, Any]:
    today = _nudge_budget_local_date(now)
    state = _read_json(NUDGE_BUDGET_STATE_PATH, {})
    if not isinstance(state, dict) or state.get("date") != today:
        state = {"date": today, "sent_counts": {"pressure": 0, "total": 0}, "events": []}
    state.setdefault("sent_counts", {"pressure": 0, "total": 0})
    state.setdefault("events", [])
    return state


def _nudge_budget_check(*, category: str, now: datetime) -> Optional[Dict[str, Any]]:
    state = _nudge_budget_read_for_today(now)
    counts = dict(state.get("sent_counts") or {})
    if int(counts.get(category, 0)) >= NUDGE_BUDGET_DAILY_PRESSURE_LIMIT:
        return {
            "reason": "nudge_budget_exhausted",
            "category": category,
            "limit": NUDGE_BUDGET_DAILY_PRESSURE_LIMIT,
            "sent_today": int(counts.get(category, 0)),
        }
    return None


def _nudge_budget_record_sent(*, category: str, now: datetime, task_label: Optional[str], message: str) -> Dict[str, Any]:
    state = _nudge_budget_read_for_today(now)
    counts = dict(state.get("sent_counts") or {})
    counts[category] = int(counts.get(category, 0)) + 1
    counts["total"] = int(counts.get("total", 0)) + 1
    state["sent_counts"] = counts
    state["events"] = (
        list(state.get("events") or [])
        + [{"ts": now.isoformat(), "category": category, "task_label": task_label, "message_preview": message[:160]}]
    )[-50:]
    _write_json(NUDGE_BUDGET_STATE_PATH, state)
    return state


def _mood_router_text_scores(text: str) -> Dict[str, float]:
    lowered = text.lower()
    lexicon = {
        "frustrated": ("frustrated", "annoyed", "angry", "mad", "nonsense", "broken", "mess", "irritated"),
        "confused": ("confused", "lost", "unclear", "gibberish", "don't understand", "doesn't make sense"),
        "low_energy": ("tired", "overwhelmed", "exhausted", "stuck", "drained", "low energy", "burned out"),
        "rushed": ("busy", "rushed", "quick", "no time", "hurry", "asap"),
        "engaged": ("good", "great", "go ahead", "continue", "approved", "yes"),
    }
    scores: Dict[str, float] = {}
    for label, terms in lexicon.items():
        hits = sum(1 for term in terms if term in lowered)
        if hits:
            scores[label] = min(0.35 + (hits * 0.18), 0.92)
    if not scores and text.strip():
        scores["neutral"] = 0.55
    return scores


def _mood_router_voice_scores(audio_emotions: Any) -> Dict[str, float]:
    if not isinstance(audio_emotions, dict):
        return {}
    mapping = {
        "angry": "frustrated",
        "anger": "frustrated",
        "annoyed": "frustrated",
        "sad": "low_energy",
        "sadness": "low_energy",
        "fear": "low_energy",
        "fearful": "low_energy",
        "tired": "low_energy",
        "neutral": "neutral",
        "happy": "engaged",
        "joy": "engaged",
        "surprise": "engaged",
    }
    scores: Dict[str, float] = {}
    for raw_label, raw_score in audio_emotions.items():
        try:
            score = float(raw_score)
        except Exception:
            continue
        label = mapping.get(str(raw_label).strip().lower())
        if not label:
            continue
        scores[label] = max(scores.get(label, 0.0), max(0.0, min(score, 1.0)))
    return scores


def _mood_router_style_policy(label: str) -> Dict[str, str]:
    policies = {
        "frustrated": {"tone": "warm", "pace": "steady", "detail": "explain_reason", "next_step_size": "small"},
        "confused": {"tone": "patient", "pace": "slow", "detail": "context_first", "next_step_size": "small"},
        "low_energy": {"tone": "encouraging", "pace": "slow", "detail": "minimal", "next_step_size": "tiny"},
        "rushed": {"tone": "concise", "pace": "fast", "detail": "action_only", "next_step_size": "small"},
        "engaged": {"tone": "direct", "pace": "normal", "detail": "normal", "next_step_size": "normal"},
        "neutral": {"tone": "direct", "pace": "normal", "detail": "normal", "next_step_size": "normal"},
    }
    return dict(policies.get(label, policies["neutral"]))


def _mood_router_fuse(*, text_scores: Dict[str, float], voice_scores: Dict[str, float]) -> Dict[str, Any]:
    combined: Dict[str, float] = {}
    for label, score in text_scores.items():
        combined[label] = max(combined.get(label, 0.0), float(score) * 0.92)
    for label, score in voice_scores.items():
        combined[label] = max(combined.get(label, 0.0), float(score))
    if text_scores.get("low_energy", 0) >= 0.5 and voice_scores.get("low_energy", 0) >= 0.5:
        combined["low_energy"] = min(max(combined.get("low_energy", 0), 0.78), 0.95)
    if text_scores.get("frustrated", 0) >= 0.5 and text_scores.get("confused", 0) >= 0.5:
        combined["frustrated"] = max(combined.get("frustrated", 0), 0.76)
    if not combined:
        combined["unknown"] = 0.0
    priority = {"frustrated": 5, "low_energy": 4, "confused": 3, "rushed": 2, "engaged": 1, "neutral": 0, "unknown": -1}
    label, confidence = max(combined.items(), key=lambda item: (item[1], priority.get(item[0], 0)))
    return {"label": label, "confidence": round(float(confidence), 3), "scores": {k: round(float(v), 3) for k, v in combined.items()}}


def _mood_router_model_status() -> Dict[str, Any]:
    providers = {
        "whisper": False,
        "goemotions": False,
        "emotion2vec": False,
    }
    try:
        import whisper  # type: ignore  # noqa: F401
        providers["whisper"] = True
    except Exception:
        pass
    try:
        import transformers  # type: ignore  # noqa: F401
        providers["goemotions"] = True
    except Exception:
        pass
    try:
        import funasr  # type: ignore  # noqa: F401
        providers["emotion2vec"] = True
    except Exception:
        pass
    return {
        "providers": providers,
        "intended_stack": ["Whisper", "GoEmotions", "emotion2vec"],
        "fallback": "lexicon_router",
    }


def _mood_router_status() -> Dict[str, Any]:
    state = _read_json(MOOD_ROUTER_STATE_PATH, {})
    if not isinstance(state, dict):
        state = {}
    return {
        "configured": bool(state.get("last_mood")),
        "last_mood": state.get("last_mood"),
        "recent_moods": list(state.get("recent_moods") or []),
        "model_status": _mood_router_model_status(),
    }


def _mood_router_route(args: Dict[str, Any], *, now: Optional[datetime] = None) -> Dict[str, Any]:
    text = str(args.get("text") or args.get("transcript") or "").strip()
    audio_emotions = args.get("audio_emotions") or args.get("voice_emotions")
    text_scores = _mood_router_text_scores(text)
    voice_scores = _mood_router_voice_scores(audio_emotions)
    fused = _mood_router_fuse(text_scores=text_scores, voice_scores=voice_scores)
    modalities = []
    if text_scores:
        modalities.append("text")
    if voice_scores:
        modalities.append("voice")
    label = str(fused["label"])
    mood = {
        "ts": (now or datetime.now(timezone.utc)).isoformat(),
        "source": str(args.get("source") or "unknown").strip(),
        "label": label,
        "confidence": fused["confidence"],
        "scores": fused["scores"],
        "modalities": modalities,
        "style_policy": _mood_router_style_policy(label),
        "evidence_summary": "text+voice mood signal" if set(modalities) == {"text", "voice"} else (f"{modalities[0]} mood signal" if modalities else "no mood signal"),
    }
    state = _read_json(MOOD_ROUTER_STATE_PATH, {})
    if not isinstance(state, dict):
        state = {}
    state["last_mood"] = mood
    state["recent_moods"] = (list(state.get("recent_moods") or []) + [mood])[-30:]
    state["model_status"] = _mood_router_model_status()
    _write_json(MOOD_ROUTER_STATE_PATH, state)
    return mood


def _runtime_calendar_proposal(*, title: str, window: str, duration_minutes: int, notes: Optional[List[str]] = None) -> Dict[str, Any]:
    return {
        "title": title,
        "window": window,
        "duration_minutes": int(duration_minutes),
        "notes": list(notes or []),
        "status": "proposal_only",
    }


def _calendar_provider() -> str:
    return str(_env_first("HERMES_CALENDAR_PROVIDER", "CALENDAR_PROVIDER") or "").strip().lower()


def _calendar_browser_url() -> str:
    return str(_env_first("HERMES_GOOGLE_CALENDAR_URL", "GOOGLE_CALENDAR_URL") or "https://calendar.google.com/calendar/u/0/r").strip()


def _calendar_read_state() -> Dict[str, Any]:
    data = _read_json(CALENDAR_STATE_PATH, {"drafts": [], "commits": []})
    if not isinstance(data, dict):
        return {"drafts": [], "commits": []}
    drafts = list(data.get("drafts") or [])
    commits = list(data.get("commits") or [])
    return {"drafts": [item for item in drafts if isinstance(item, dict)], "commits": [item for item in commits if isinstance(item, dict)]}


def _calendar_write_state(data: Dict[str, Any]) -> None:
    _write_json(CALENDAR_STATE_PATH, data)


def _calendar_compact_timestamp(value: str) -> str:
    dt = _runtime_parse_iso(value)
    if dt is None:
        return ""
    return dt.astimezone(_runtime_local_tz()).strftime("%Y%m%dT%H%M%S")


def _calendar_prefill_url(*, title: str, start: str, end: str, description: str = "") -> str:
    from urllib.parse import urlencode
    params = {
        "action": "TEMPLATE",
        "text": title,
        "dates": f"{_calendar_compact_timestamp(start)}/{_calendar_compact_timestamp(end)}",
        "details": description,
        "ctz": HERMES_LOCAL_TIMEZONE,
    }
    return f"{_calendar_browser_url()}?{urlencode(params)}"


def _runtime_calendar_status(args: Dict[str, Any]) -> Dict[str, Any]:
    del args
    provider = _calendar_provider()
    state = _calendar_read_state()
    configured = provider == "browser_google_calendar" and bool(_calendar_browser_url())
    return {
        "success": True,
        "action": "calendar_status",
        "provider": provider or "unconfigured",
        "configured": configured,
        "mode": "browser_handoff" if provider == "browser_google_calendar" else "unconfigured",
        "approval_policy": "commit_requires_approval",
        "draft_count": len(state.get("drafts") or []),
        "commit_count": len(state.get("commits") or []),
        "browser_url": _calendar_browser_url() if configured else "",
    }


def _runtime_calendar_event(args: Dict[str, Any]) -> Dict[str, Any]:
    mode = str(args.get("mode") or "draft").strip().lower()
    provider = _calendar_provider()
    if provider != "browser_google_calendar":
        raise ValueError("calendar provider is not configured for browser_google_calendar")
    state = _calendar_read_state()
    drafts = list(state.get("drafts") or [])
    commits = list(state.get("commits") or [])
    if mode == "draft":
        title = str(args.get("title") or "").strip()
        start = str(args.get("start") or "").strip()
        end = str(args.get("end") or "").strip()
        description = str(args.get("description") or "").strip()
        if not title or not start or not end:
            raise ValueError("title, start, and end are required")
        draft = {
            "draft_id": f"calendar_draft_{uuid.uuid4().hex[:10]}",
            "provider": provider,
            "title": title,
            "start": start,
            "end": end,
            "description": description,
            "prefill_url": _calendar_prefill_url(title=title, start=start, end=end, description=description),
            "status": "draft_ready",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        drafts.append(draft)
        state["drafts"] = drafts[-100:]
        state["commits"] = commits[-100:]
        _calendar_write_state(state)
        return {"success": True, "action": "calendar_event", "mode": mode, "provider": provider, "draft": draft}
    if mode == "commit":
        draft_id = str(args.get("draft_id") or "").strip()
        draft = next((item for item in reversed(drafts) if str(item.get("draft_id") or "") == draft_id), None)
        if draft is None:
            raise ValueError("draft_id was not found")
        response = json.loads(_create_approval(
            tool_name="personal_runtime",
            action="calendar_event_commit",
            summary=f"Approve calendar event handoff for {draft.get('title')}",
            reason="Calendar writes should be explicit and approval-gated even in browser-backed mode.",
            benefit="Hermes prepares the event and you keep control over the final browser-backed calendar handoff.",
            payload={"action": "calendar_event_commit", "draft": draft},
        ))
        response["draft"] = draft
        return response
    raise ValueError(f"Unsupported calendar_event mode: {mode}")


def _runtime_create_todoist_task_direct(*, content: str, description: str = "", priority: int = 1, labels: Optional[List[str]] = None) -> Dict[str, Any]:
    payload = {
        "action": "add_task",
        "content": content,
        "description": description,
        "priority": priority,
        "labels": list(labels or []),
    }
    return _execute_todoist(payload)


def _runtime_event_window_label(now: Optional[datetime] = None) -> str:
    local = (now or datetime.now(timezone.utc)).astimezone(_runtime_local_tz())
    hour = local.hour
    if 5 <= hour < 11:
        return "morning"
    if 11 <= hour < 17:
        return "midday"
    if 17 <= hour < 22:
        return "evening"
    return "quiet_hours"


def _runtime_operator_event_brief(*, event_type: str, focus_state: Dict[str, Any], now: Optional[datetime] = None) -> Dict[str, Any]:
    window = _runtime_event_window_label(now)
    operator = None
    try:
        operator = _operator_brief({
            "filter": "today | overdue",
            "limit": 8,
            "allow_message": False,
            "send_telegram": False,
        })
    except Exception as exc:
        operator = {"success": False, "error": str(exc)}
    target = str(((focus_state.get("most_important_task") or {}).get("content") or "")).strip()
    top_task = operator.get("top_task") if isinstance(operator, dict) else None
    if isinstance(top_task, dict) and top_task.get("title"):
        target = str(top_task["title"])
    target = target or "No clear top task"
    return {
        "window": window,
        "operator": operator,
        "target": target,
        "risk": (operator or {}).get("risk") if isinstance(operator, dict) else None,
        "friction": (operator or {}).get("primary_friction") if isinstance(operator, dict) else None,
        "next_action": (operator or {}).get("recommended_next_action") if isinstance(operator, dict) else None,
    }


def _runtime_source_friendly(source: str) -> str:
    return {
        "windows-logon-trigger": "Windows logon",
        "windows-unlock-trigger": "desktop unlock",
        "desktop_unlocked": "desktop unlock",
        "manual": "manual command",
    }.get(source, source or "unknown")


def _runtime_task_link(title: str, task_id: Optional[str]) -> str:
    escaped = _escape_html(title)
    if task_id:
        return f'<b><a href="https://app.todoist.com/app/task/{task_id}">{escaped}</a></b>'
    return f'"{escaped}"'


def _runtime_purpose_preserving_next_action(raw: str, task_title: str) -> str:
    text = str(raw or "").strip()
    lowered = task_title.lower()
    if "laundry" in lowered:
        return "Minimum useful move: start, switch, fold one small piece, or mark no laundry needed."
    if not text:
        return "Pick one small action that still makes sense in this time window."
    return text.replace("finish it, split it, or reschedule it honestly", "do the smallest useful version or reschedule it honestly")


def _runtime_render_policy_event_briefing(
    *,
    event_type: str,
    focus_state: Dict[str, Any],
    detail: Dict[str, Any],
    now: datetime,
    source: str,
) -> str:
    local = now.astimezone(_runtime_local_tz())
    time_str = local.strftime('%I:%M %p').lstrip('0')
    source_friendly = _runtime_source_friendly(source)
    target = str(detail.get("target") or ((focus_state.get("most_important_task") or {}).get("content") or "") or "No clear top task").strip()
    mit = focus_state.get("most_important_task") or {}
    task_link = _runtime_task_link(target, mit.get("id")) if target and target != "No clear top task" else ""
    window = str(detail.get("window") or _runtime_event_window_label(now))
    is_late_evening = window == "evening" and local.hour >= 21

    signal_name = source_friendly
    lines = [
        f"I received a {signal_name} signal at {time_str}, so I'm treating this as possible activity, not guaranteed availability.",
        "",
    ]

    if window == "quiet_hours":
        lines.append("This is outside normal message hours, so this should stay quiet unless you asked for it.")
        if task_link:
            lines.append(f"Queued context: {task_link}.")
    elif is_late_evening:
        lines.append("Since it's late, I'm not going to push deep work, reference reading, or broad planning.")
        if task_link:
            lines.append(f"The one task that still makes sense tonight is {task_link}.")
    else:
        lines.append("Priority anchor:")
        if task_link:
            lines.append(task_link)
        else:
            lines.append("No clear top task is defined, so the useful move is to pick one small anchor before doing support work.")

    operator = detail.get("operator") if isinstance(detail.get("operator"), dict) else {}
    evidence = (operator.get("evidence") or {}) if isinstance(operator, dict) else {}
    todoist_evidence = (evidence.get("todoist_mcp") or {}) if isinstance(evidence, dict) else {}
    if todoist_evidence and not is_late_evening:
        active = todoist_evidence.get("active_count", 0)
        completed = todoist_evidence.get("completed_recently", 0)
        stats_parts = []
        if active:
            stats_parts.append(f"{active} active task{'s' if active != 1 else ''}")
        if completed:
            stats_parts.append(f"{completed} completed recently")
        if stats_parts:
            lines.append(f"Quick snapshot: {', '.join(stats_parts)}.")

    suspicious = list(focus_state.get("suspicious_tasks") or [])
    if suspicious:
        first_task = suspicious[0].get("task") or {}
        first = str(first_task.get("content") or "").strip()
        if first:
            first_link = _runtime_task_link(first, first_task.get("id"))
            if is_late_evening:
                lines.append(f"\nI would ignore {first_link} tonight unless you are intentionally doing review work. It looks more like reference/setup than execution.")
            else:
                lines.append(f"\nPotential distractions: {first_link} looks more like reference/setup or support work than the main action.")

    next_act = _runtime_purpose_preserving_next_action(str(detail.get("next_action") or ""), target)
    lines.append(f"\n\U0001f449 For the next 5\u201315 minutes: {next_act}")
    if is_late_evening:
        lines.append("If that is not realistic right now, tap it later mentally and let tonight be a clean reschedule, not a catch-up spiral.")
    else:
        lines.append("If that is not realistic, reschedule it honestly or write the blocker.")
    lines.append(f"\n\U0001f552 {time_str} \u00b7 triggered via {source_friendly}")
    return "\n".join(lines)


def _runtime_build_wake_briefing(*, focus_state: Dict[str, Any], now: Optional[datetime] = None, source: str = "") -> str:
    detail = _runtime_operator_event_brief(event_type="wake", focus_state=focus_state, now=now)
    local = (now or datetime.now(timezone.utc)).astimezone(_runtime_local_tz())
    return _runtime_render_policy_event_briefing(
        event_type="wake",
        focus_state=focus_state,
        detail=detail,
        now=local,
        source=source,
    )


def _runtime_build_unlock_briefing(*, focus_state: Dict[str, Any], now: Optional[datetime] = None, source: str = "") -> str:
    detail = _runtime_operator_event_brief(event_type="desktop_unlocked", focus_state=focus_state, now=now)
    local = (now or datetime.now(timezone.utc)).astimezone(_runtime_local_tz())
    return _runtime_render_policy_event_briefing(
        event_type="desktop_unlocked",
        focus_state=focus_state,
        detail=detail,
        now=local,
        source=source,
    )


def _runtime_outing_options(*, now: datetime, budget: str, time_window: str, energy: str) -> List[Dict[str, Any]]:
    local = now.astimezone()
    weekday = local.strftime("%A")
    options = [
        {
            "title": "Coffee and one short walk",
            "why": "Low setup, easy exit, good for rebuilding the habit of leaving.",
            "effort": "low",
            "budget": "low",
            "duration_minutes": 60,
            "window": time_window,
        },
        {
            "title": "Errand plus one pleasant stop",
            "why": "Turns a practical trip into a real outing without demanding too much novelty.",
            "effort": "medium",
            "budget": "low",
            "duration_minutes": 90,
            "window": time_window,
        },
        {
            "title": f"{weekday} anchor outing",
            "why": "A slightly more deliberate plan so the week has one memorable outside moment.",
            "effort": "medium" if energy != "low" else "low",
            "budget": budget,
            "duration_minutes": 120,
            "window": time_window,
        },
    ]
    if energy == "low":
        return options[:2]
    return options


def _runtime_handle_outing_event(args: Dict[str, Any]) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    budget = str(args.get("budget") or "low").strip().lower()
    time_window = str(args.get("time_window") or "today").strip()
    energy = str(args.get("energy") or "medium").strip().lower()
    options = _runtime_outing_options(now=now, budget=budget, time_window=time_window, energy=energy)
    top = options[0]
    todoist_result = None
    if bool(args.get("auto_create_todoist", True)):
        description = "Options:\n" + "\n".join(f"- {item['title']}: {item['why']}" for item in options)
        todoist_result = _runtime_create_todoist_task_direct(
            content=f"Pick and do one outing: {top['title']}",
            description=description,
            priority=3,
            labels=["outing", "hermes"],
        )
    proposal = _runtime_calendar_proposal(
        title=top["title"],
        window=top["window"],
        duration_minutes=int(top["duration_minutes"]),
        notes=[item["title"] for item in options],
    )
    return {
        "handled": True,
        "event_type": "outing_request",
        "options": options,
        "selected_default": top,
        "todoist": todoist_result,
        "calendar_proposal": proposal,
        "summary": f"Built {len(options)} outing options and defaulted to '{top['title']}'.",
    }


VOICE_CLI_WHITELIST = {
    "restart dashboard": ["systemctl", "--user", "restart", "hermes-dashboard"],
    "status dashboard": ["systemctl", "--user", "status", "hermes-dashboard"],
    "restart gateway": ["systemctl", "--user", "restart", "hermes-gateway"],
    "status gateway": ["systemctl", "--user", "status", "hermes-gateway"],
    "status webhook": ["systemctl", "--user", "status", "hermes-event-webhook"],
    "check disk": ["df", "-h"],
    "check memory": ["free", "-m"],
    "backup configuration": ["tar", "-czf", "/home/ubuntu/.hermes/backup_config.tar.gz", "-C", "/home/ubuntu/.hermes", "config.yaml", ".env"],
}

def _voice_core_apply_corrections(text: str) -> str:
    corrections = {
        r"\bcatty\s*file\b": "Caddyfile",
        r"\bcaddy\s*file\b": "Caddyfile",
        r"\bto\s*do\s*list\b": "Todoist",
        r"\bactivity\s*watch\b": "ActivityWatch",
        r"\bweb\s*hook\b": "webhook",
        r"\bfast\s*api\b": "FastAPI",
        r"\bsystem\s*d\b": "systemd",
        r"\bherms\b": "Hermes",
    }
    cleaned = text
    for pat, rep in corrections.items():
        cleaned = re.sub(pat, rep, cleaned, flags=re.IGNORECASE)
    return cleaned

def _voice_core_assemble_context() -> Dict[str, Any]:
    context = {}
    context["current_time"] = datetime.now(timezone.utc).isoformat()
    presence = _read_json(PRESENCE_STATE_PATH, {})
    context["current_presence"] = {
        "location": presence.get("location", "unknown"),
        "last_update": presence.get("last_location_update"),
        "source": presence.get("source")
    }
    aw_signal = _runtime_activitywatch_signal()
    if aw_signal.get("configured") and aw_signal.get("active"):
        context["active_window"] = {
            "app": aw_signal.get("active_category"),
            "title": aw_signal.get("title_hint")
        }
    try:
        tasks = _focus_guard_read_todoist_tasks()
        context["active_tasks"] = [
            {"id": t["id"], "content": t["content"], "priority": t["priority"], "labels": t.get("labels", [])}
            for t in tasks[:20]
        ]
    except Exception:
        context["active_tasks"] = []
    try:
        memos = _read_jsonl_recent(VOICE_CAPTURE_LOG_PATH, limit=5)
        context["recent_memos"] = [
            {"ts": m.get("ts"), "transcript": m.get("transcript"), "classification": m.get("kind")}
            for m in memos
        ]
    except Exception:
        context["recent_memos"] = []
    return context

def _get_todoist_projects() -> Dict[str, str]:
    projects_map = {}
    try:
        with _http_client() as client:
            resp = client.get(f"{TODOIST_BASE}/projects", headers=_todoist_headers())
            if resp.status_code == 200:
                results = resp.json().get("results") or []
                for p in results:
                    projects_map[p["name"].lower().strip()] = p["id"]
    except Exception:
        pass
    return projects_map

def _get_project_id_by_name(name: str) -> Optional[str]:
    if not name:
        return None
    p_map = _get_todoist_projects()
    name_lower = name.lower().strip()
    for key, val in p_map.items():
        if name_lower == key or name_lower in key or key in name_lower:
            return val
    return None

def _voice_core_answer_query(query: str, context: Dict[str, Any]) -> str:
    from agent.auxiliary_client import call_llm
    system_prompt = (
        "You are Hermes, a helpful personal assistant OS. Answer the user's spoken question based on the provided context state.\n"
        "Keep your answer extremely concise, professional, and conversational (max 3 sentences) since it will be sent to the user via Telegram.\n\n"
        "CONTEXT:\n"
        f"- Current Time: {context.get('current_time')}\n"
        f"- Presence: {context.get('current_presence')}\n"
        f"- Active Desktop Window: {context.get('active_window')}\n"
        f"- Active Todoist Tasks: {context.get('active_tasks')}\n"
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"User question: {query}"}
    ]
    try:
        response = call_llm(
            task="title_generation",
            messages=messages,
            max_tokens=200,
            temperature=0.7,
            timeout=10.0,
        )
        return (response.choices[0].message.content or "").strip()
    except Exception as e:
        return f"Unable to answer query: {e}"

def _find_and_complete_todoist_task(query_str: str) -> Optional[Dict[str, Any]]:
    if not query_str:
        return None
    try:
        tasks = _focus_guard_read_todoist_tasks()
        query_lower = query_str.lower().strip()
        for task in tasks:
            title_lower = task.get("content", "").lower()
            if query_lower in title_lower or any(word in title_lower for word in query_lower.split() if len(word) > 3):
                res = _execute_todoist({"action": "close_task", "task_id": task["id"]})
                return task
    except Exception:
        pass
    return None

def _run_whitelist_system_command(command_key: str) -> str:
    if command_key not in VOICE_CLI_WHITELIST:
        return f"Execution rejected: Command key '{command_key}' is not whitelisted."
    cmd = VOICE_CLI_WHITELIST[command_key]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        output = (res.stdout or "") + (res.stderr or "")
        return f"Executed whitelisted command '{command_key}':\n{output[:500]}"
    except Exception as e:
        return f"Failed to run command '{command_key}': {e}"

def _voice_core_fallback(text: str) -> Dict[str, Any]:
    lowered = text.lower()
    intent = "note_capture"
    details = {}
    if any(term in lowered for term in ["worked on", "spent", "hours", "today i did", "i was working on"]):
        intent = "WORK_PROGRESS"
        details = {"activity": text, "duration_hours": 0.0}
    elif any(term in lowered for term in ["remind me", "need to", "follow up", "todo", "to do", "i should"]):
        intent = "ACTION_TASK"
        details = {"title": text, "due_date": None, "priority": 2}
    elif any(term in lowered for term in ["idea", "what if", "i'm thinking", "could build", "maybe build"]):
        intent = "REFLECTION_JOURNAL"
        details = {"content": text, "mood": "neutral"}
    return {
        "corrected_transcript": text,
        "segments": [
            {
                "intent": intent,
                "reason": "fallback parser",
                "details": details
            }
        ]
    }

def _runtime_classify_voice_capture(text: str, context: Dict[str, Any]) -> Dict[str, Any]:
    from agent.auxiliary_client import call_llm
    whitelist_keys = list(VOICE_CLI_WHITELIST.keys())
    system_prompt = (
        "You are the Cognitive Vocal Core for Hermes, a personal agent OS.\n"
        "Analyze the user's spoken transcript, segment it into one or more distinct intents, "
        "and return a single JSON object in the exact format specified below.\n\n"
        "CONTEXT STATE:\n"
        f"- Current Time: {context.get('current_time')}\n"
        f"- Location/Presence: {context.get('current_presence')}\n"
        f"- Active Desktop Window: {context.get('active_window')}\n"
        f"- Recent Active Tasks: {context.get('active_tasks')}\n"
        f"- Recent Memos (Conversational Context): {context.get('recent_memos')}\n\n"
        "INTENT TYPES & DETAILS:\n"
        "1. ACTION_TASK: Something the user needs to do.\n"
        "   - title: Clean, concise title of the task (strip conversational junk like 'remind me to').\n"
        "   - due_date: Human relative date/time (e.g. 'tomorrow 3 PM', 'next Monday', or null).\n"
        "   - priority: Urgency level (4 for high/asap, 2 for normal, 1 for low).\n"
        "   - project: Suggested project name or null.\n"
        "2. WORK_PROGRESS: Update on work done/time spent.\n"
        "   - activity: Description of what was completed/worked on.\n"
        "   - duration_hours: Decimal hours spent (e.g. 1.5, 0.5) or 0 if not mentioned.\n"
        "   - associated_task_query: A string to search for in active tasks to auto-complete (or null).\n"
        "3. COMMAND_QUERY: A direct question about state, logs, or codebase config.\n"
        "   - query: Question text to search/resolve.\n"
        "4. EXECUTE_SYSTEM_COMMAND: Spoken request to run a whitelisted administrative shell command.\n"
        "   - command_key: MUST be exactly one of: " + ", ".join(whitelist_keys) + " (or null if no match).\n"
        "5. REFLECTION_JOURNAL: Personal reflections, journal inputs, mood indicators.\n"
        "   - content: Clean text of the reflection.\n"
        "   - mood: Guess the mood based on tone/content (productive, tired, stressed, happy, neutral).\n"
        "6. NOISE_FILLER: Conversational fill, hesitation, or non-actionable chatter.\n\n"
        "JSON SCHEMA:\n"
        "Respond ONLY with a JSON object in this format (no markdown, no backticks, no comments):\n"
        "{\n"
        "  \"corrected_transcript\": \"<the transcript corrected for typos and technical terms>\",\n"
        "  \"segments\": [\n"
        "    {\n"
        "      \"intent\": \"ACTION_TASK | WORK_PROGRESS | COMMAND_QUERY | EXECUTE_SYSTEM_COMMAND | REFLECTION_JOURNAL | NOISE_FILLER\",\n"
        "      \"reason\": \"<short explanation>\",\n"
        "      \"details\": { ... matching structure above ... }\n"
        "    }\n"
        "  ]\n"
        "}"
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Spoken Transcript: {text}"},
    ]
    response = call_llm(
        task="title_generation",
        messages=messages,
        max_tokens=800,
        temperature=0.0,
        timeout=45.0,
    )
    content = (response.choices[0].message.content or "").strip()
    if content.startswith("```"):
        lines = content.splitlines()
        if len(lines) >= 3 and lines[-1].startswith("```"):
            content = "\n".join(lines[1:-1]).strip()
        if content.startswith("json"):
            content = content[4:].strip()
    return json.loads(content)

def _runtime_handle_voice_capture(args: Dict[str, Any]) -> Dict[str, Any]:
    todoist_result = None
    raw_transcript = str(args.get("transcript") or args.get("text") or "").strip()
    if not raw_transcript:
        raise ValueError("transcript or text is required for voice capture")
    corrected_transcript = _voice_core_apply_corrections(raw_transcript)
    context = _voice_core_assemble_context()
    try:
        parsed = _runtime_classify_voice_capture(corrected_transcript, context)
    except Exception:
        parsed = _voice_core_fallback(corrected_transcript)
    corrected = parsed.get("corrected_transcript") or corrected_transcript
    segments = parsed.get("segments") or []
    summary_lines = []
    actions_taken = []
    for seg in segments:
        intent = seg.get("intent", "note_capture").upper()
        details = seg.get("details") or {}
        if intent == "ACTION_TASK":
            title = details.get("title") or corrected
            due_date = details.get("due_date")
            priority = int(details.get("priority") or 2)
            project = details.get("project")
            project_id = _get_project_id_by_name(project)
            todoist_payload = {
                "action": "add_task",
                "content": title,
                "description": f"Voice Capture: {raw_transcript}",
                "priority": priority,
            }
            if due_date:
                todoist_payload["due_string"] = due_date
            if project_id:
                todoist_payload["project_id"] = project_id
            todoist_payload["labels"] = ["voice-capture", "hermes"]
            res = _execute_todoist(todoist_payload)
            todoist_result = res
            if res.get("success"):
                summary_lines.append(f"???? **Created Task**: '{title}'" + (f" (Due: {due_date})" if due_date else ""))
                actions_taken.append(res)
            else:
                summary_lines.append(f"?????? **Failed to create task**: '{title}'")
        elif intent == "WORK_PROGRESS":
            activity = details.get("activity") or corrected
            duration = float(details.get("duration_hours") or 0.0)
            task_query = details.get("associated_task_query")
            work_entry = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "activity": activity,
                "duration_hours": duration,
                "transcript_source": raw_transcript,
            }
            _append_jsonl(WORK_LOG_PATH, work_entry)
            summary_lines.append(f"?????? **Logged Work**: '{activity}' ({duration} hrs)")
            if task_query:
                completed_task = _find_and_complete_todoist_task(task_query)
                if completed_task:
                    summary_lines.append(f"??? **Auto-Completed Task**: '{completed_task.get('content')}'")
                    actions_taken.append({"completed_task": completed_task})
        elif intent == "COMMAND_QUERY":
            query = details.get("query") or corrected
            answer = _voice_core_answer_query(query, context)
            summary_lines.append(f"???? **Query**: '{query}'\n???? *{answer}*")
            actions_taken.append({"query": query, "answer": answer})
        elif intent == "EXECUTE_SYSTEM_COMMAND":
            cmd_key = details.get("command_key")
            if cmd_key:
                exec_summary = _run_whitelist_system_command(cmd_key)
                summary_lines.append(f"??????? **Executed Command**: {cmd_key}\n```{exec_summary}```")
                actions_taken.append({"system_command": cmd_key, "output": exec_summary})
            else:
                summary_lines.append("?????? **Command Rejected**: Invalid/unauthorized command requested.")
        elif intent == "REFLECTION_JOURNAL":
            content = details.get("content") or corrected
            mood = details.get("mood") or "neutral"
            journal_file = HERMES_HOME / "daily_journal.md"
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            try:
                journal_file.parent.mkdir(parents=True, exist_ok=True)
                with journal_file.open("a", encoding="utf-8") as f:
                    f.write(f"\n## {date_str} (Mood: {mood})\n")
                    f.write(f"- {content}\n")
                summary_lines.append(f"???? **Journaled Reflection** (Mood: {mood})")
            except Exception as e:
                summary_lines.append(f"?????? **Failed to save journal**: {e}")
            actions_taken.append({"journal": content, "mood": mood})
    vault_entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "source": str(args.get("source") or "unknown").strip(),
        "raw_transcript": raw_transcript,
        "corrected_transcript": corrected,
        "segments": segments,
        "actions_taken": actions_taken,
    }
    VOICE_VAULT_LOG_PATH = HERMES_HOME / "voice_vault" / "vault_log.jsonl"
    _append_jsonl(VOICE_VAULT_LOG_PATH, vault_entry)
    legacy_entry = {
        "ts": vault_entry["ts"],
        "source": vault_entry["source"],
        "kind": segments[0].get("intent", "note_capture").lower() if segments else "note_capture",
        "reason": segments[0].get("reason", "") if segments else "",
        "transcript": raw_transcript,
    }
    _append_jsonl(VOICE_CAPTURE_LOG_PATH, legacy_entry)
    if summary_lines:
        telegram_message = "??????? **Voice Memo Processed**:\n" + "\n".join(summary_lines)
    else:
        telegram_message = "??????? **Voice Memo Received**: Logged reflection/note."
    # Ensure legacy compatibility for testing & tracking
    primary_intent = segments[0].get("intent", "note_capture").upper() if segments else "NOTE_CAPTURE"
    kind_map = {
        "ACTION_TASK": "task_capture",
        "WORK_PROGRESS": "work_log",
        "REFLECTION_JOURNAL": "note_capture",
        "COMMAND_QUERY": "note_capture",
        "EXECUTE_SYSTEM_COMMAND": "note_capture",
        "NOISE_FILLER": "note_capture"
    }
    legacy_kind = kind_map.get(primary_intent, "note_capture")
    legacy_reason = segments[0].get("reason", "") if segments else ""
    classification = {"kind": legacy_kind, "reason": legacy_reason}

    # Route mood updates
    mood = _mood_router_route(args, now=datetime.now(timezone.utc))

    _safe_send_telegram_message(telegram_message, force=True)
    return {
        "handled": True,
        "event_type": "voice_memo_received",
        "raw_transcript": raw_transcript,
        "corrected_transcript": corrected,
        "segments": segments,
        "summary": "Processed voice memo and executed actions.",
        "classification": classification,
        "mood": mood,
        "todoist": todoist_result,
        "logged_to": str(VOICE_CAPTURE_LOG_PATH),
    }



def _runtime_handle_activitywatch_heartbeat(args: Dict[str, Any]) -> Dict[str, Any]:
    signal = dict(args.get("presence_signal") or {})
    confidence = float(signal.get("confidence") or 0.0)
    label = str(signal.get("label") or "ActivityWatch heartbeat").strip()
    active = bool(signal.get("active"))

    # Read current location from presence state
    state = _read_json(PRESENCE_STATE_PATH, {})
    current_location = state.get("location", "").strip().lower()

    if active:
        if current_location != "desk":
            _handle_location_update({"location": "desk", "source": "activitywatch-forwarder"})
    else:
        if current_location == "desk":
            _handle_location_update({"location": "home", "source": "activitywatch-forwarder"})

    return {
        "handled": True,
        "event_type": "activitywatch_heartbeat",
        "presence_signal": {
            "confidence": confidence,
            "label": label,
            "active": active,
            "active_category": str(signal.get("active_category") or "").strip(),
            "last_activity_age_seconds": signal.get("last_activity_age_seconds"),
        },
        "summary": "Recorded ActivityWatch heartbeat from the user's computer.",
    }


def _runtime_handle_gym_event(args: Dict[str, Any]) -> Dict[str, Any]:
    event_type = str(args.get("event_type") or "").strip().lower()
    if not event_type:
        event_type = "gym.arrived"
    event = event_type.split(".", 1)[-1]
    note = str(args.get("note") or args.get("message") or "").strip()
    source = str(args.get("source") or "gym-webhook").strip()
    when_raw = args.get("when")
    when: Optional[datetime] = None
    if isinstance(when_raw, str) and when_raw.strip():
        try:
            when = datetime.fromisoformat(when_raw.replace("Z", "+00:00"))
        except Exception:
            when = None

    if event == "arrived" and _gym_record_arrival is not None:
        message = _gym_record_arrival(source=source, note=note, when=when)
        try:
            _safe_send_telegram_message(message, force=True)
        except Exception:
            pass
    elif event == "left" and _gym_record_departure is not None:
        message = _gym_record_departure(source=source, note=note, when=when)
        if _gym_workout_task_for_day is not None:
            task = _gym_workout_task_for_day(when)
            if task:
                try:
                    name, url = task
                    task_id = url
                    if "id=" in url:
                        task_id = url.split("id=")[-1]
                    elif "/" in url:
                        task_id = url.rstrip("/").split("/")[-1]
                    close_res = _execute_todoist({"action": "close_task", "task_id": task_id})
                    if close_res.get("success"):
                        message += f"\nAutomatically completed Todoist task: {name}."
                except Exception as e:
                    message += f"\n(Failed to auto-complete Todoist task: {e})"
        try:
            _safe_send_telegram_message(message, force=True)
        except Exception:
            pass
    elif event == "report" and _gym_monthly_report is not None:
        year = args.get("year")
        month = args.get("month")
        try:
            message = _gym_monthly_report(
                year=int(year) if year is not None and str(year).strip() else None,
                month=int(month) if month is not None and str(month).strip() else None,
            )
        except Exception:
            message = _gym_monthly_report()
    else:
        raise ValueError(f"Unsupported gym event: {event_type}")

    payload = {
        "gym_event": event,
        "source": source,
        "note": note,
    }
    if _gym_workout_task_for_day is not None:
        task = _gym_workout_task_for_day(when)
        if task:
            name, url = task
            task_id = url.split("id=")[-1] if "id=" in url else url
            payload["workout_task"] = {
                "name": name,
                "url": url,
                "app_url": f"todoist://task?id={task_id}"
            }
    if event == "arrived":
        payload["location"] = "gym"
    elif event == "left":
        payload["location"] = "away"
    return {
        "handled": True,
        "event_type": event_type,
        "summary": message.splitlines()[0] if message else f"Logged gym {event}.",
        "message": message,
        "presence_signal": {
            "confidence": 1.0,
            "label": f"Gym {event}",
            "active": event == "arrived",
            "active_category": "gym",
            "location": payload.get("location", "gym" if event == "arrived" else "away"),
        },
        "payload": payload,
    }


def _update_operator_state_from_event(event_type: str, source: str, payload: Dict[str, Any], now_dt: datetime) -> None:
    now_ts = int(now_dt.timestamp())
    presence_state = _read_json(PRESENCE_STATE_PATH, {})
    if not isinstance(presence_state, dict):
        presence_state = {}
    operator_state = _operator_read_state()

    # Track sensor heartbeats
    heartbeats = operator_state.setdefault("last_sensor_heartbeats", {})
    heartbeats[source] = now_ts

    # Extract info
    category = payload.get("category") or payload.get("active_category") or "unknown"
    duration = int(payload.get("duration_sec") or 0)

    # 1. Desktop Sentinel events
    if event_type == "desktop.active":
        presence_state["state"] = "desk"
        presence_state["confidence"] = 1.0
        presence_state["last_seen_ts"] = now_ts
        presence_state["afk"] = False
    elif event_type == "desktop.idle":
        if presence_state.get("state") == "desk":
            presence_state["state"] = presence_state.get("location", "home")
        presence_state["confidence"] = 1.0
        presence_state["last_seen_ts"] = now_ts
        presence_state["afk"] = True
    elif event_type in {"desktop.heartbeat", "desktop.category_changed"}:
        payload_state = payload.get("presence_state")
        if payload_state == "active_now":
            presence_state["state"] = "desk"
            presence_state["afk"] = False
        elif payload_state == "idle":
            if presence_state.get("state") == "desk":
                presence_state["state"] = presence_state.get("location", "home")
            presence_state["afk"] = True
        presence_state["confidence"] = 1.0
        presence_state["last_seen_ts"] = now_ts

        att = operator_state.setdefault("attention", {})
        if category and category != "unknown":
            att["category"] = category
            att["last_updated_at"] = now_ts
    elif event_type == "desktop.category_ended":
        att = operator_state.setdefault("attention", {})
        att["category"] = "unknown"
        att["last_updated_at"] = now_ts

    # 2. iOS Focus & Sleep Events
    elif event_type == "ios.sleep_focus_on":
        presence_state["state"] = "sleep"
        presence_state["confidence"] = 1.0
        presence_state["last_seen_ts"] = now_ts
        operator_state["day_phase"] = "quiet_hours"
    elif event_type == "ios.sleep_focus_off":
        presence_state["state"] = "home"
        presence_state["confidence"] = 0.8
        presence_state["last_seen_ts"] = now_ts
        operator_state["day_phase"] = "morning_horizon"
        operator_state["wake_candidate_ts"] = now_ts
    elif event_type == "ios.work_focus_on":
        operator_state["day_phase"] = "work_window"
    elif event_type == "ios.work_focus_off":
        operator_state["day_phase"] = "evening"

    # 3. Location events
    elif event_type == "location_update":
        loc = payload.get("location") or payload.get("value") or "home"
        presence_state["location"] = loc
        presence_state["state"] = loc
        presence_state["confidence"] = 1.0
        presence_state["last_seen_ts"] = now_ts

    # 4. Decay and sensor watchdog freshness
    sentinel_last = heartbeats.get("desktop_sentinel")
    if sentinel_last and (now_ts - sentinel_last > 600):
        # Stale desktop sentinel -> decay confidence
        if presence_state.get("state") == "desk":
            presence_state["state"] = presence_state.get("location", "home")
        presence_state["confidence"] = max(0.0, presence_state.get("confidence", 1.0) - 0.5)

    _write_json(PRESENCE_STATE_PATH, presence_state)
    _operator_write_state(operator_state)


def _is_nudge_allowed_and_wise(now_dt: datetime, operator_state: Dict[str, Any]) -> tuple[bool, str]:
    now_hour = now_dt.hour
    now_ts = int(now_dt.timestamp())

    if not _telegram_messages_allowed_now(now_hour):
        return False, "outside_allowed_hours"

    day_phase = operator_state.get("day_phase")
    if day_phase == "quiet_hours":
        return False, "sleep_or_quiet_hours"

    nudge_state = operator_state.setdefault("nudge_fatigue", {})

    # Check mute_until lock
    mute_until = int(nudge_state.get("mute_until_ts") or 0)
    if mute_until > 0 and now_ts < mute_until:
        return False, "muted"

    last_nudge = int(nudge_state.get("last_nudge_ts") or 0)
    cooldown = int(nudge_state.get("cooldown_duration") or 3600)

    if last_nudge > 0 and (now_ts - last_nudge < cooldown):
        return False, "cooldown_active"

    return True, "ok"


def _record_nudge_sent(now_dt: datetime, cooldown: int = 3600) -> None:
    operator_state = _operator_read_state()
    nudge_state = operator_state.setdefault("nudge_fatigue", {})
    nudge_state["last_nudge_ts"] = int(now_dt.timestamp())
    nudge_state["cooldown_duration"] = cooldown
    _operator_write_state(operator_state)


def _build_distraction_nudge_message(duration_sec: int, category: str, salvage: Dict[str, Any]) -> str:
    dur_min = duration_sec // 60
    cat_name = category.replace("distraction_", "").capitalize()

    lines = [
        "<b>Focus check</b>",
        f"I received a desktop signal that looks like {cat_name.lower()} for about {dur_min} minutes. I am treating that as context, not proof of intent or availability.",
        ""
    ]

    if salvage.get("expired"):
        lines.append("<b>Expired as written:</b>")
        for t in salvage["expired"][:3]:
            lines.append(f"• <s>{_escape_html(t)}</s>")
        lines.append("")

    if salvage.get("closed"):
        lines.append("<b>Closed by time/window:</b>")
        for t in salvage["closed"][:3]:
            lines.append(f"• {t} (draft, schedule, or move to tomorrow)")
        lines.append("")

    if salvage.get("still_useful"):
        lines.append("<b>Still useful now:</b>")
        for t in salvage["still_useful"][:3]:
            lines.append(f"• {_escape_html(t)}")
        lines.append("")

    best_move = salvage.get("still_useful")[0] if salvage.get("still_useful") else "Draft tomorrow's items"
    lines.append("<b>Best recovery:</b>")
    lines.append(f"Spend 5 minutes on: {_escape_html(str(best_move))}. If that is wrong, mute or defer instead.")

    return "\n".join(lines)


def _handle_distraction_event(event_type: str, payload: Dict[str, Any], now_dt: datetime) -> Dict[str, Any]:
    operator_state = _operator_read_state()
    allowed, reason = _is_nudge_allowed_and_wise(now_dt, operator_state)
    if not allowed:
        return {"handled": True, "event_type": event_type, "nudge_sent": False, "reason": reason}

    try:
        intel = _todoist_intelligence({"filter": "today | overdue", "limit": 20})
        tasks = list(((intel.get("active_tasks") or {}).get("tasks")) or [])
    except Exception:
        tasks = []

    analysis = _common_sense_analyze_tasks(tasks, now=now_dt)
    salvage = analysis.get("late_day_salvage") or {}

    duration_sec = int(payload.get("duration_sec") or 0)
    category = str(payload.get("category") or "unknown")

    msg = _build_distraction_nudge_message(duration_sec, category, salvage)

    buttons = [
        {"text": "⚡ 5-Min Sprint", "callback_data": "po:sprint:start"},
        {"text": "☕ Take Break", "callback_data": "po:nudge_mute:1h"},
        {"text": "🔄 Defer Remaining", "callback_data": "po:defer_all_today"}
    ]

    _safe_send_telegram_message(msg, parse_mode="HTML", buttons=buttons)
    _record_nudge_sent(now_dt, cooldown=3600)

    return {"handled": True, "event_type": event_type, "nudge_sent": True, "message": msg, "summary": f"Sent distraction nudge for {category}."}


def _classify_task_role(task: Dict[str, Any]) -> str:
    content = str(task.get("content") or "").lower()
    labels = [str(l).lower() for l in task.get("labels") or []]
    due_info = task.get("due") or {}
    is_recurring = bool(due_info.get("is_recurring"))

    # 1. Check explicit classification labels first
    if "family_anchor" in labels:
        return "family_anchor"
    if "fitness_anchor" in labels:
        return "fitness_anchor"
    if "routine" in labels:
        return "routine"
    if "reference" in labels:
        return "reference"
    if "checklist_item" in labels:
        return "checklist_item"
    if "task_debt" in labels:
        return "task_debt"
    if "exclude_workload" in labels:
        return "exclude_workload"
    if "hermes_hidden" in labels:
        return "hermes_hidden"

    # 2. Fallbacks
    # Family & Life Anchors
    family_words = {"family", "son", "wife", "outing", "playtime", "parent"}
    if any(w in content for w in family_words) or "family_anchor" in labels:
        return "family_anchor"

    # Fitness / Gym / Workout
    fitness_words = {"workout", "gym", "fitness", "upper", "lower", "recovery day", "cardio", "nutrition"}
    if any(w in content for w in fitness_words) or "fitness_anchor" in labels or task.get("project_id") == "6ghFPf6XX9Hv3h6p":
        return "fitness_anchor"

    # Routines & Habits
    routine_words = {"routine", "daily", "habit", "checklist", "shut down", "morning launch", "reset"}
    routine_labels = {"routine", "daily", "habit", "health"}
    if is_recurring or any(w in content for w in routine_words) or any(l in routine_labels for l in labels):
        return "routine"

    # Focus Work
    priority = int(task.get("priority") or 1)
    if priority >= 3:
        return "focus"

    return "admin"


def _classify_task_type(task: Dict[str, Any]) -> str:
    return _classify_task_role(task)


def _classify_task_decision_load(task: Dict[str, Any], is_debt: bool = False) -> str:
    if is_debt:
        return "debt"

    role = _classify_task_role(task)
    if role in ("family_anchor", "routine"):
        return "routine"

    content = str(task.get("content") or "").lower()
    labels = [str(l).lower() for l in task.get("labels") or []]

    decision_words = {
        "plan", "choice", "choose", "communication", "review", "write", "decide",
        "call", "email", "meeting", "discuss", "strategy", "someday", "maybe",
        "triage", "cleanup", "clean up"
    }
    has_decision_word = any(w in content for w in decision_words)
    has_decision_label = any(l in ("deep_work", "focus", "decision") for l in labels)
    priority = int(task.get("priority") or 1)

    if role == "focus" or priority >= 3 or has_decision_word or has_decision_label:
        return "decision_heavy"

    return "execution_only"


def _operator_evaluate_yesterday_predictions(operator_state: Dict[str, Any], current_tasks: List[Dict[str, Any]]) -> None:
    briefing_predictions = operator_state.setdefault("briefing_predictions", {})
    current_ids = {t.get("id") for t in current_tasks if t.get("id")}

    analytics = operator_state.setdefault("behavioral_analytics", {
        "completions_count": 0,
        "ignores_count": 0,
        "history": []
    })

    recent_completions = []
    try:
        recent_completions = _get_recent_completions()
    except Exception:
        pass
    completed_task_ids = {str(c.get("task_id")) for c in recent_completions if c.get("task_id")}

    today_str = datetime.now(_runtime_local_tz()).date().isoformat()

    for date_str, pred in list(briefing_predictions.items()):
        if date_str == today_str or pred.get("completed"):
            continue

        predicted_ids = pred.get("predicted_top_tasks") or []
        if not predicted_ids:
            pred["completed"] = True
            continue

        completed_ids = []
        ignored_ids = []
        for pid in predicted_ids:
            if pid in completed_task_ids or pid not in current_ids:
                completed_ids.append(pid)
            else:
                ignored_ids.append(pid)

        pred["completed"] = True
        pred["completed_tasks"] = completed_ids
        pred["ignored_tasks"] = ignored_ids

        analytics["completions_count"] += len(completed_ids)
        analytics["ignores_count"] += len(ignored_ids)
        analytics["history"].append({
            "date": date_str,
            "completed_count": len(completed_ids),
            "ignored_count": len(ignored_ids)
        })


def _run_scheduler_checks(now_dt: datetime) -> None:
    now_ts = int(now_dt.timestamp())
    operator_state = _operator_read_state()
    state_changed = False

    # 1. Active Sprint check
    sprint = operator_state.get("active_sprint")
    if sprint:
        started_at = int(sprint.get("started_at", 0))
        duration = int(sprint.get("duration", 300))
        if now_ts >= started_at + duration:
            operator_state.pop("active_sprint", None)
            state_changed = True
            msg = "<b>🎉 Sprint Complete!</b>\nGreat job! You focused for 5 minutes. Would you like to start another, or take a clean 5-minute break?"
            buttons = [
                {"text": "⚡ Start Another Sprint", "callback_data": "po:sprint:start"},
                {"text": "☕ Take a Break", "callback_data": "po:nudge_mute:1h"}
            ]
            _safe_send_telegram_message(msg, parse_mode="HTML", buttons=buttons)

    # 2. Daily boundary checks / transitions
    tz = _runtime_local_tz()
    local_now = now_dt.astimezone(tz)
    local_hour = local_now.hour
    local_min = local_now.minute

    current_phase = "quiet_hours"
    if 9 <= local_hour < 18:
        current_phase = "work_window"
    elif 18 <= local_hour < 22:
        current_phase = "evening"
    else:
        current_phase = "quiet_hours"

    last_phase = operator_state.get("day_phase")
    if last_phase != current_phase:
        operator_state["day_phase"] = current_phase
        state_changed = True
        if last_phase is not None:
            if current_phase == "work_window":
                # Morning Repair Loop (7-Minute Clean)
                had_debt = operator_state.get("last_briefing_had_debt")
                if had_debt:
                    operator_state["last_briefing_had_debt"] = False

                    try:
                        all_tasks = _focus_guard_read_todoist_tasks()
                        from datetime import date
                        today_date = local_now.date()

                        overdue = []
                        for t in all_tasks:
                            # Skip reference, hidden, duplicate, and checklist items from workload calculation
                            lbls = [str(l).lower() for l in t.get("labels") or []]
                            if any(l in {"exclude_workload", "reference", "hermes_hidden", "checklist_item", "duplicate"} for l in lbls):
                                continue

                            due_info = t.get("due") or {}
                            due_date_str = due_info.get("date")
                            if due_date_str:
                                try:
                                    date_part = due_date_str.split("T")[0]
                                    task_due_date = date.fromisoformat(date_part)
                                    if task_due_date < today_date:
                                        overdue.append(t)
                                except Exception:
                                    pass

                        shown_counts = operator_state.get("shown_task_counts", {})
                        critical_overdue = []
                        for t in overdue:
                            priority = int(t.get("priority") or 1)
                            t_id = t.get("id")
                            is_stuck = t_id and shown_counts.get(t_id, 0) >= 5
                            if priority >= 3 or is_stuck:
                                critical_overdue.append(t)

                        if not critical_overdue:
                            critical_overdue = overdue

                        lines = [
                            "<b>☀️ Morning Repair Loop (7-Minute Clean)</b>",
                            "Before starting work, let’s spend 7 minutes cleaning task debt. I’ll show only overdue items that are either high-priority, repeated, or stuck.",
                            ""
                        ]

                        to_show = critical_overdue[:3]
                        for t in to_show:
                            escaped_content = _escape_html(t.get("content", "").strip())
                            lines.append(f"  • <b>{escaped_content}</b>")

                        lines.append("\n<i>Tap one of the quick actions below to process these, or reply to clear the deck!</i>")

                        buttons = [
                            {"text": "🧹 Triage Backlog", "callback_data": "po:briefing:triage"},
                            {"text": "🔄 Defer All Today", "callback_data": "po:defer_all_today"}
                        ]
                        _safe_send_telegram_message("\n".join(lines), parse_mode="HTML", buttons=buttons)
                    except Exception:
                        _safe_send_telegram_message("<b>☀️ Work Window Started</b>\nLet's get focus mode going. Open your first task to start.", parse_mode="HTML")
                else:
                    _safe_send_telegram_message("<b>☀️ Work Window Started</b>\nLet's get focus mode going. Open your first task to start.", parse_mode="HTML")

            elif current_phase == "quiet_hours":
                cleanup_res = _run_auto_cleanup_routines()
                logs = cleanup_res.get("logs", [])
                msg = "<b>🌙 Quiet Hours Started</b>\nRemaining tasks deferred to keep evening clear.\n"
                if logs:
                    msg += "\n".join([f"• {_escape_html(l)}" for l in logs])
                _safe_send_telegram_message(msg, parse_mode="HTML")

    # 3. Evening Briefing check (9:45 PM tomorrow preview)
    if local_hour == 21 and local_min >= 45:
        today_str = local_now.date().isoformat()
        last_brief = operator_state.get("last_evening_briefing_date")
        if last_brief != today_str:
            # Mark as sent immediately to prevent concurrent triggers
            operator_state["last_evening_briefing_date"] = today_str
            state_changed = True

            try:
                from datetime import date
                # Fetch all tasks programmatically to separate tomorrow, missed today, and overdue
                all_tasks = _focus_guard_read_todoist_tasks()

                # Rule 1: Prediction vs reality loop - Evaluate yesterday's predictions
                _operator_evaluate_yesterday_predictions(operator_state, all_tasks)

                today_date = local_now.date()
                tomorrow_date = today_date + timedelta(days=1)

                tomorrow_tasks = []
                overdue_tasks = []
                missed_today_tasks = []

                for t in all_tasks:
                    # Skip reference, hidden, duplicate, and checklist items from workload calculation
                    lbls = [str(l).lower() for l in t.get("labels") or []]
                    if any(l in {"exclude_workload", "reference", "hermes_hidden", "checklist_item", "duplicate"} for l in lbls):
                        continue

                    due_info = t.get("due") or {}
                    due_date_str = due_info.get("date")
                    if not due_date_str:
                        continue
                    try:
                        date_part = due_date_str.split("T")[0]
                        task_due_date = date.fromisoformat(date_part)
                    except Exception:
                        continue

                    if task_due_date == tomorrow_date:
                        tomorrow_tasks.append(t)
                    elif task_due_date == today_date:
                        missed_today_tasks.append(t)
                    elif task_due_date < today_date:
                        overdue_tasks.append(t)

                # Rule 3 & 4: Stale-task decay and quarantining
                active_overdue_tasks = []
                stale_backlog_tasks = []
                for t in overdue_tasks:
                    due_info = t.get("due") or {}
                    due_date_str = due_info.get("date")
                    is_stale = False
                    if due_date_str:
                        try:
                            date_part = due_date_str.split("T")[0]
                            task_due_date = date.fromisoformat(date_part)
                            overdue_days = (today_date - task_due_date).days
                            priority = int(t.get("priority") or 1)
                            if overdue_days >= 7 and priority < 4:
                                is_stale = True
                        except Exception:
                            pass
                    if is_stale:
                        stale_backlog_tasks.append(t)
                    else:
                        active_overdue_tasks.append(t)

                # Increment shown counts for all tasks evaluated (Rule 2: Task survivorship)
                shown_counts = operator_state.setdefault("shown_task_counts", {})
                for t in tomorrow_tasks + active_overdue_tasks:
                    t_id = t.get("id")
                    if t_id:
                        shown_counts[t_id] = shown_counts.get(t_id, 0) + 1

                # Separate stuck tasks
                stuck_tasks = []
                unstuck_tomorrow_tasks = []
                for t in tomorrow_tasks:
                    t_id = t.get("id")
                    if t_id and shown_counts.get(t_id, 0) >= 5:
                        stuck_tasks.append(t)
                    else:
                        unstuck_tomorrow_tasks.append(t)

                unstuck_overdue_tasks = []
                for t in active_overdue_tasks:
                    t_id = t.get("id")
                    if t_id and shown_counts.get(t_id, 0) >= 5:
                        stuck_tasks.append(t)
                    else:
                        unstuck_overdue_tasks.append(t)

                display_tomorrow_count = len(tomorrow_tasks)
                display_debt_count = len(unstuck_overdue_tasks) + len(missed_today_tasks)
                stale_count = len(stale_backlog_tasks)

                # Save whether this briefing had heavy debt for morning repair loop check
                operator_state["last_briefing_had_debt"] = (display_debt_count >= 10)

                # Rule 4: Protective Omission policy is explicit
                evening_briefing_should_not_show_full_backlog = True

                # Classify tomorrow's tasks for scoring decision load (Rule 2)
                family_anchors = []
                fitness_anchors = []
                focus_tasks = []
                routines = []
                admins = []

                decision_heavy_tasks = []
                execution_only_tasks = []

                for t in unstuck_tomorrow_tasks:
                    role = _classify_task_role(t)
                    if role == "family_anchor":
                        family_anchors.append(t)
                    elif role == "fitness_anchor" or "fitness_anchor" in [l.lower() for l in t.get("labels") or []]:
                        fitness_anchors.append(t)
                    elif role == "routine":
                        routines.append(t)
                    else:
                        load_cat = _classify_task_decision_load(t, is_debt=False)
                        if load_cat == "decision_heavy":
                            decision_heavy_tasks.append(t)
                        else:
                            execution_only_tasks.append(t)

                        if role == "focus":
                            focus_tasks.append(t)
                        else:
                            admins.append(t)

                # Filter tomorrow workload tasks: exclude family/fitness anchors
                tomorrow_workload_tasks = focus_tasks + admins + routines
                display_tomorrow_count = len(tomorrow_workload_tasks)
                display_debt_count = len(unstuck_overdue_tasks) + len(missed_today_tasks)
                stale_count = len(stale_backlog_tasks)

                # Save whether this briefing had heavy debt for morning repair loop check
                operator_state["last_briefing_had_debt"] = (display_debt_count >= 10)

                # Rule 4: Protective Omission policy is explicit
                evening_briefing_should_not_show_full_backlog = True

                triage_mode = (display_debt_count >= 10)

                # Briefing Memory Introductory copy (Rule 7)
                last_mode = operator_state.get("last_evening_briefing_mode")
                operator_state["last_evening_briefing_mode"] = "task_debt_triage" if triage_mode else "standard"

                lines = []

                # Done Enough celebratory header (Rule 8)
                completed_today = 0
                try:
                    recent_comps = _get_recent_completions()
                    for c in recent_comps:
                        completed_at_str = c.get("completed_at")
                        if completed_at_str:
                            comp_date = datetime.fromisoformat(completed_at_str.replace("Z", "+00:00")).astimezone(tz).date()
                            if comp_date == today_date:
                                completed_today += 1
                except Exception:
                    pass

                if completed_today >= 3:
                    lines.append("<b>🎉 You moved the important pieces today. Tomorrow has some cleanup, but nothing needs solving tonight.</b>\n")

                if triage_mode:
                    lines.append("<b>📅 Tomorrow's Preview: Sleep-Safe Triage</b>")
                    if last_mode == "task_debt_triage":
                        lines.append("<i>Same situation as last night: tomorrow itself is manageable, but the overdue queue still needs a cleanup pass.</i>\n")
                    else:
                        lines.append(f"Tomorrow's scheduled workload is manageable ({display_tomorrow_count} scheduled workload item{'s' if display_tomorrow_count != 1 else ''}).\n")
                else:
                    lines.append("<b>📅 Tomorrow's Todoist Preview</b>")

                # Workload / Decision Load statement (Rule 2)
                lines.append(f"Tomorrow has {display_tomorrow_count} scheduled workload item{'s' if display_tomorrow_count != 1 else ''}, but only {len(decision_heavy_tasks)} require{'s' if len(decision_heavy_tasks) == 1 else ''} real decisions.")
                lines.append("")

                # Carryover debt quarantine
                if display_debt_count > 0:
                    lines.append(f"There is also a backlog of {display_debt_count} overdue or carryover item{'s' if display_debt_count != 1 else ''} in quarantine. None of these need to be decided tonight—they need cleanup, not panic.")
                    lines.append("")

                # Rule 3: Stale task decay message
                if stale_count > 0:
                    lines.append(f"<i>{stale_count} overdue item{'s' if stale_count != 1 else ''} look stale rather than urgent. I’ll keep them out of tomorrow’s workload unless you promote them.</i>")
                    lines.append("")

                # Rule 4 & 5: Protective omission limit - Hard max of 3 focus items shown
                to_show = (focus_tasks + admins)[:3]
                if to_show:
                    lines.append("<b>⭐ Focus Work to Protect:</b>")
                    for t in to_show:
                        t_id = t.get("id")
                        escaped_content = _escape_html(t.get("content", "").strip())
                        due_time = t.get("due", {}).get("datetime")
                        time_str = ""
                        if due_time:
                            try:
                                dt_due = datetime.fromisoformat(due_time.replace("Z", "+00:00")).astimezone(tz)
                                time_str = f" [at {dt_due.strftime('%I:%M %p').lstrip('0')}]"
                            except Exception:
                                pass
                        if t_id:
                            lines.append(f"  • <a href=\"https://app.todoist.com/app/task/{t_id}\">{escaped_content}</a>{time_str}")
                        else:
                            lines.append(f"  • {escaped_content}{time_str}")
                    lines.append("")

                # Rule 6 & 8: Sacred Family & Fitness Anchors
                if family_anchors or fitness_anchors:
                    lines.append("<b>☖ Protected Family & Fitness Anchors:</b>")
                    for t in family_anchors + fitness_anchors:
                        t_id = t.get("id")
                        escaped_content = _escape_html(t.get("content", "").strip())
                        role = _classify_task_role(t)
                        emoji = "🌸" if role == "family_anchor" else "💪"
                        if t_id:
                            lines.append(f"  • {emoji} <a href=\"https://app.todoist.com/app/task/{t_id}\">{escaped_content}</a>")
                        else:
                            lines.append(f"  • {emoji} {escaped_content}")
                    lines.append("<i>Family & fitness anchors are already protected. I’m not counting them as workload.</i>")
                    lines.append("")

                # Stuck task intervention block (Rule 3)
                if stuck_tasks:
                    lines.append("<b>⚠️ Stuck Tasks Needing Intervention:</b>")
                    for t in stuck_tasks[:2]:
                        escaped_content = _escape_html(t.get("content", "").strip())
                        count = shown_counts.get(t.get("id"), 5)
                        lines.append(f"  • <b>{escaped_content}</b> (carried forward {count} times)")
                    lines.append("<i>These tasks keep surviving. Use the options below to shrink, defer, or archive them.</i>")
                    lines.append("")

                # Summarize remaining routine/admin items stress-free
                total_remaining_routines = len(tomorrow_workload_tasks) - len(to_show) - len([st for st in stuck_tasks if st in tomorrow_workload_tasks])
                if total_remaining_routines > 0:
                    lines.append("<b>🔄 Routines & Low-Pressure Backlog:</b>")
                    lines.append(f"Plus {total_remaining_routines} lower-priority routine/admin item{'s' if total_remaining_routines != 1 else ''}, summarized for tomorrow morning. No need to mentally sort them tonight.")
                    lines.append("")

                # Rule 1 & 8: Support and clean exit closure line (no disturb my nervous system)
                closure_options = [
                    "Nothing else needs sorting tonight.",
                    "Tomorrow has a first move. You can leave the rest for morning.",
                    "The list is captured. You do not need to keep it in your head."
                ]
                day_of_month = local_now.day
                closure_line = closure_options[day_of_month % len(closure_options)]
                lines.append(f"<i>{closure_line}</i>")
                lines.append("<i>Tomorrow morning: spend 10 minutes deciding what to reschedule, delete, delegate, or do. Enjoy a restful evening! 🌟</i>")

                # Inline buttons for feedback controls (Rule 5)
                buttons = [
                    {"text": "🧹 Triage Overdue", "callback_data": "po:briefing:triage"},
                    {"text": "🌙 Quiet Mode", "callback_data": "po:briefing:quiet"},
                    {"text": "⭐ Show Top 3 Only", "callback_data": "po:briefing:top3"}
                ]
                if stuck_tasks:
                    fs_id = stuck_tasks[0].get("id")
                    buttons.append({"text": "⚡ Shrink Stuck Task", "callback_data": f"po:stuck:shrink:{fs_id}"})
                    buttons.append({"text": "💤 Move to Someday", "callback_data": f"po:stuck:someday:{fs_id}"})

                # Track predicted top task IDs for learning loop evaluation tomorrow
                predicted_top_ids = [t.get("id") for t in to_show if t.get("id")]
                briefing_predictions = operator_state.setdefault("briefing_predictions", {})
                briefing_predictions[today_str] = {
                    "predicted_top_tasks": predicted_top_ids,
                    "completed": False
                }

                _safe_send_telegram_message("\n".join(lines), force=True, parse_mode="HTML", buttons=buttons)
            except Exception:
                pass

    # 4. Periodic past due task nudge checks
    # Only run the check every 15 minutes to avoid rate-limiting or heavy resources
    last_past_due_check = int(operator_state.get("last_past_due_check_ts") or 0)
    if 7 <= local_hour < 22 and (now_ts - last_past_due_check >= 900):
        operator_state["last_past_due_check_ts"] = now_ts
        state_changed = True

        try:
            from datetime import date

            # Fetch active tasks due today or overdue
            tasks = _focus_guard_read_todoist_tasks(filter="today | overdue")
            reminded_task_ids = operator_state.setdefault("past_due_reminders_sent", [])
            postpone_counts = operator_state.get("task_postpone_counts", {})

            # Load presence state
            presence_s = _read_json(PRESENCE_STATE_PATH, {})
            location = str(presence_s.get("location", "home")).strip().lower()
            state = str(presence_s.get("state", "")).strip().lower()
            active_cat = str(presence_s.get("active_category", "")).strip().lower()

            overdue_to_remind = []

            for t in tasks:
                t_id = t.get("id")
                if not t_id:
                    continue

                due = t.get("due") or {}
                due_date_str = due.get("date")
                if not due_date_str:
                    continue

                # Check category of the task
                task_content = t.get("content", "").strip()
                labels = [str(l).lower() for l in t.get("labels") or []]
                is_gym = "fitness_anchor" in labels or "workout" in task_content.lower() or "gym" in task_content.lower()
                is_family = "family_anchor" in labels or any(w in task_content.lower() for w in ["wife", "son", "playtime", "outing"])
                is_business = "business_owner" in labels or "deep_work" in labels or "owner" in task_content.lower() or "ceo" in task_content.lower()

                # 1. Focus Protection Rule
                if is_business and state == "desk" and active_cat == "editor":
                    # Deep Work Active -> Suppress work nudges to protect flow
                    continue

                # 2. Location & Boundary Rules
                if is_gym and location == "gym":
                    # Already at the gym -> suppress gym nudge
                    continue
                if is_business and location == "home":
                    # Work-to-Home boundary lock -> mute work nudges at home
                    continue

                is_past_due = False
                reason = ""
                milestone = ""

                # If there's a specific time component in due_date_str
                if "T" in due_date_str:
                    try:
                        dt_due = _parse_todoist_datetime(due_date_str)
                        if dt_due.tzinfo is None:
                            dt_due = dt_due.replace(tzinfo=tz)

                        elapsed_minutes = (local_now - dt_due).total_seconds() / 60

                        # Milestones:
                        if is_gym and location == "home" and -15 <= elapsed_minutes < 0:
                            # 15 minutes before gym time and still at home -> transition prep
                            milestone = "gym_transition"
                            is_past_due = True
                            reason = "gym_prep"
                        elif 0 <= elapsed_minutes <= 5:
                            # 0 to 5 minutes past (Due time)
                            milestone = "due_time"
                            is_past_due = True
                            reason = "past_due_time"
                        elif 15 <= elapsed_minutes <= 25:
                            # 20 minutes past (Short delay)
                            milestone = "short_delay"
                            is_past_due = True
                            reason = "past_due_time"
                        elif 55 <= elapsed_minutes <= 65:
                            # 60 minutes past (Long delay)
                            milestone = "long_delay"
                            is_past_due = True
                            reason = "past_due_time"
                    except Exception:
                        pass
                else:
                    # All-day task (e.g. '2026-05-25')
                    try:
                        date_part = due_date_str.split("T")[0]
                        task_due_date = date.fromisoformat(date_part)
                        if task_due_date < local_now.date():
                            milestone = "overdue_backlog"
                            is_past_due = True
                            reason = "past_due_date"
                    except Exception:
                        pass

                if is_past_due and milestone:
                    reminder_key = f"{t_id}:{due_date_str}:{milestone}"
                    if reminder_key not in reminded_task_ids:
                        overdue_to_remind.append((t, reminder_key, reason, milestone))

            if overdue_to_remind:
                # Limit to 1 task reminder per scan (highest priority first)
                overdue_to_remind.sort(key=lambda item: int(item[0].get("priority", 1)), reverse=True)

                target_task, reminder_key, reason, milestone = overdue_to_remind[0]
                task_content = target_task.get("content", "").strip()
                t_id = target_task.get("id")

                escaped_content = _escape_html(task_content)
                due_info = target_task.get("due") or {}
                time_str = ""
                if "T" in due_info.get("date", ""):
                    try:
                        dt_due = _parse_todoist_datetime(due_info["date"]).astimezone(tz)
                        time_str = f" scheduled for {dt_due.strftime('%I:%M %p').lstrip('0')}"
                    except Exception:
                        pass

                labels = [str(l).lower() for l in target_task.get("labels") or []]
                is_gym = "fitness_anchor" in labels or "workout" in task_content.lower() or "gym" in task_content.lower()
                is_family = "family_anchor" in labels or any(w in task_content.lower() for w in ["wife", "son", "playtime", "outing"])
                is_business = "business_owner" in labels or "deep_work" in labels or "owner" in task_content.lower() or "ceo" in task_content.lower()

                # Check Deferral Fatigue (postponed >= 3 times)
                deferral_count = postpone_counts.get(t_id, 0)

                if deferral_count >= 3:
                    # Deferral fatigue intervention message
                    msg = f"<b>⚠️ Deferral fatigue detected: {escaped_content}</b>\n\nMikail, we've deferred this priority {deferral_count} times today. Rather than pushing against friction, let's play it smart. We can either park it guilt-free in Someday/Maybe to clear your headspace, or resize it to a tiny 2-minute micro-step to build momentum. What's your play? 🌸"
                    buttons = [
                        {"text": "💤 Park in Someday", "callback_data": f"po:task_someday:{t_id}"},
                        {"text": "⚡ Shrink to 2-Min", "callback_data": f"po:task_shrink:{t_id}"},
                        {"text": "📅 Defer Tomorrow", "callback_data": f"po:task_defer:{t_id}"}
                    ]
                else:
                    # Specialized messaging based on category & milestone
                    if is_gym:
                        if reason == "gym_prep":
                            msg = f"<b>🏋️‍♂️ Transition Prep: Lower A Workout</b>\n\nHey Mikail, checking in. Your workout starts in 15 minutes. Let's pack your bag, put down the screen, and transition cleanly to gym mode! Your V-Taper habit starts with this one transition. 💪"
                        else:
                            msg = f"<b>💪 Fitness Nudge: {escaped_content}</b>\n\nHey Mikail! Just a gentle, supportive check-in. This workout{time_str} is past its scheduled time. Let's get this in, move some weight, and stick to your V-Taper habit today. You'll feel incredible once it's done! 🏋️‍♂️"
                    elif is_family:
                        msg = f"<b>☖ Family Focus: {escaped_content}</b>\n\nHi Mikail, checking in. This family connection anchor{time_str} is past its time. Let's make sure we put down the screen, step away from work, and give your full, loving attention to your family. They are the core of it all! 🌸"
                    elif is_business:
                        msg = f"<b>🎯 High-Priority Business Focus: {escaped_content}</b>\n\nHey Mikail! Quick check-in on this business focus item{time_str}. If possible, let's get this one main priority step done now so you can close the loop and protect your evening boundary. You've got this! 🚀"
                    else:
                        if reason == "past_due_time":
                            if milestone == "short_delay":
                                msg = f"<b>🌸 Gentle Reminder: {escaped_content}</b>\n\nHey Mikail! Just noticing this task is past its due time. If you can, let's get this minor piece done now and clear it off your list! ✨"
                            elif milestone == "long_delay":
                                msg = f"<b>⏳ Final Check-In: {escaped_content}</b>\n\nMikail, this task is an hour past due. Let's either get it done in a quick sprint now, or reschedule it honestly to keep your list clean! 🧹"
                            else:
                                msg = f"<b>🌸 Gentle Check-In: {escaped_content}</b>\n\nHey Mikail! Just noticing this task{time_str} is past its scheduled due time today. If it's realistic, let's jump in and get it done now so you can keep the day's momentum going! ✨"
                        else:
                            msg = f"<b>✨ Backlog Check-In: {escaped_content}</b>\n\nHi Mikail! A friendly nudge about this overdue task from your backlog. Let's take just 5 to 10 minutes to tackle it today and keep your system clear and light! 🧹"

                    buttons = [
                        {"text": "✅ Done", "callback_data": f"po:task_complete:{t_id}"},
                        {"text": "📅 Tomorrow", "callback_data": f"po:task_defer:{t_id}"},
                        {"text": "🗑️ Archive", "callback_data": f"po:task_delete:{t_id}"}
                    ]

                _safe_send_telegram_message(msg, parse_mode="HTML", buttons=buttons)

                reminded_task_ids.append(reminder_key)
                if len(reminded_task_ids) > 200:
                    operator_state["past_due_reminders_sent"] = reminded_task_ids[-200:]
        except Exception as e:
            print(f"Error in past due task nudger: {e}")

    if state_changed:
        _operator_write_state(operator_state)


def _runtime_event_ingest(args: Dict[str, Any]) -> Dict[str, Any]:
    event_type = str(args.get("event_type") or "").strip().lower()
    if not event_type:
        raise ValueError("event_type is required")
    now = datetime.now(timezone.utc)

    # Parse payload if present (or flat payload fallback)
    payload = args.get("payload")
    if not isinstance(payload, dict):
        payload = {k: v for k, v in args.items() if k not in {"event_type", "source", "dedupe_key"}}

    # 1. Event Bus Log and Deduplication
    source = str(args.get("source") or "manual").strip()
    dedupe_key = args.get("dedupe_key")
    dedupe_key_s = str(dedupe_key or "").strip()
    event_state_for_dedupe = _runtime_read_event_state()
    recent_dedupe_keys = [
        str(item).strip()
        for item in list(event_state_for_dedupe.get("recent_dedupe_keys") or [])
        if str(item).strip()
    ]
    if dedupe_key_s and dedupe_key_s in recent_dedupe_keys:
        return {"handled": True, "duplicate": True, "event_type": event_type, "summary": "Duplicate event ignored."}
    try:
        from .event_bus import log_event
        bus_res = log_event(source, event_type, payload, dedupe_key=dedupe_key)
        if bus_res.get("duplicate"):
            return {"handled": True, "duplicate": True, "event_type": event_type, "summary": "Duplicate event ignored."}
    except Exception:
        pass

    # 2. Update state builder
    try:
        _update_operator_state_from_event(event_type, source, payload, now)
    except Exception:
        pass

    # 3. Run scheduler checks
    try:
        _run_scheduler_checks(now)
    except Exception:
        pass

    # 4. Handle events
    focus_state = _focus_guard_read_state()
    send_telegram = bool(args.get("send_telegram", False))
    force_send = bool(args.get("force_send", False))
    now_hour = now.astimezone(_runtime_local_tz()).hour
    can_send_now = _telegram_messages_allowed_now(now_hour) or force_send
    result: Dict[str, Any]

    if event_type == "location_update":
        _handle_location_update(args)
        result = {"handled": True, "event_type": event_type, "summary": "Updated location state."}
        cleanup_res = _run_auto_cleanup_routines()
        result["cleanup_logs"] = cleanup_res.get("logs", [])
    elif event_type == "wake":
        if not focus_state:
            focus_state = _focus_guard_run_once(filter="today | overdue")
        message = _runtime_build_wake_briefing(focus_state=focus_state, now=now, source=source)
        sent = False
        suppressed_reason = None
        if send_telegram and can_send_now:
            presence_s = _read_json(PRESENCE_STATE_PATH, {})
            location = presence_s.get("location", "home")
            dock_buttons = _build_hermes_dock(location, now)
            try:
                tasks = _focus_guard_read_todoist_tasks(filter="today | overdue")
                top_tasks = _get_top_high_priority_tasks(tasks, 3)
                for t in top_tasks:
                    dock_buttons.append({
                        "text": f"✅ {t.get('content')[:20]}...",
                        "callback_data": f"po:task_complete:{t.get('id')}"
                    })
            except Exception:
                pass
            _safe_send_telegram_message(message, parse_mode="HTML", buttons=dock_buttons)
            sent = True
        elif send_telegram:
            suppressed_reason = "outside_hours"
        result = {"handled": True, "event_type": event_type, "message": message, "sent": sent, "suppressed_reason": suppressed_reason, "summary": "Built detailed wake briefing."}
    elif event_type == "desktop_unlocked":
        fresh = _canonical_focus_guard_result(_focus_guard_run_once(filter=str(args.get("filter") or "today | overdue")))
        message = _runtime_build_unlock_briefing(focus_state=fresh, now=now, source=source)
        sent = False
        suppressed_reason = None
        if send_telegram and can_send_now:
            presence_s = _read_json(PRESENCE_STATE_PATH, {})
            location = presence_s.get("location", "home")
            dock_buttons = _build_hermes_dock(location, now)
            try:
                tasks = _focus_guard_read_todoist_tasks(filter="today | overdue")
                top_tasks = _get_top_high_priority_tasks(tasks, 3)
                for t in top_tasks:
                    dock_buttons.append({
                        "text": f"✅ {t.get('content')[:20]}...",
                        "callback_data": f"po:task_complete:{t.get('id')}"
                    })
            except Exception:
                pass
            _safe_send_telegram_message(message, parse_mode="HTML", buttons=dock_buttons)
            sent = True
        elif send_telegram:
            suppressed_reason = "outside_hours"
        result = {"handled": True, "event_type": event_type, "message": message, "sent": sent, "suppressed_reason": suppressed_reason, "focus_guard": fresh, "summary": "Built detailed unlock briefing."}
    elif event_type in {"leaving_house", "outing_request"}:
        result = _runtime_handle_outing_event(args)
    elif event_type == "voice_memo_received":
        result = _runtime_handle_voice_capture(args)
    elif event_type == "activitywatch_heartbeat":
        result = _runtime_handle_activitywatch_heartbeat(args)
    elif event_type.startswith("gym."):
        result = _runtime_handle_gym_event(args)
    elif event_type == "telegram_feedback":
        result = _operator_record_feedback(args, now=now)
    elif event_type.startswith("desktop.distraction_"):
        result = _handle_distraction_event(event_type, payload, now)
    elif event_type.startswith("desktop.") or event_type.startswith("ios."):
        result = {"handled": True, "event_type": event_type, "summary": f"Processed event {event_type}."}
    else:
        raise ValueError(f"Unsupported event_type: {event_type}")

    state = _runtime_read_event_state()
    record = {
        "ts": now.isoformat(),
        "event_type": event_type,
        "source": source,
        "result_summary": result.get("summary") or result.get("result_summary"),
    }
    explicit_signal = dict(result.get("presence_signal") or {})
    presence_signal = _runtime_write_presence_signal(
        event_type=event_type,
        source=record["source"],
        ts=now,
        override_confidence=(float(explicit_signal.get("confidence")) if explicit_signal.get("confidence") is not None else None),
        override_label=(str(explicit_signal.get("label")) if explicit_signal.get("label") else None),
        extra=explicit_signal,
    )
    state["last_event"] = record
    state["recent_events"] = (list(state.get("recent_events") or []) + [record])[-10:]
    if dedupe_key_s:
        state["recent_dedupe_keys"] = (recent_dedupe_keys + [dedupe_key_s])[-200:]
    _runtime_write_event_state(state)
    _append_event("runtime_event_ingested", {"event_type": event_type, "source": record["source"], "summary": result.get("summary", "")})
    return {**result, "record": record, "event_state": state, "presence_signal": presence_signal}



def _runtime_live_watch_run(*, filter: Optional[str] = None, always_on: bool = False) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    # Run scheduler checks (day-phase transitions, sprint timers)
    try:
        _run_scheduler_checks(now)
    except Exception:
        pass
    # Run auto-cleanup routines on every live watch loop
    _run_auto_cleanup_routines()
    focus_guard = _canonical_focus_guard_result(_focus_guard_run_once(filter=filter))
    companion = json.loads(handle_adaptive_companion({"action": "run", "always_on": always_on}))
    companion_state = dict(companion.get("state") or {})
    if not companion_state:
        companion_state = _adaptive_companion_read_state()
        if companion_state:
            companion["state"] = companion_state
    surface_policy = dict((companion_state.get("insight_lenses") or {}).get("surface_policy") or {})
    success = bool(companion.get("success"))
    payload = {
        "ran_at": now.isoformat(),
        "filter": filter,
        "always_on": always_on,
        "focus_guard": focus_guard,
        "adaptive_companion": companion,
        "surface_policy": surface_policy,
    }
    try:
        payload["operator_brief"] = _operator_brief({
            "filter": filter or "today | overdue",
            "limit": 12,
            "allow_message": always_on,
            "send_telegram": False,
        })
    except Exception as exc:
        payload["operator_brief_error"] = str(exc)
    try:
        payload["agi_operator_cycle"] = _agi_operator_cycle({
            "filter": filter or "today | overdue",
            "limit": 12,
            "allow_message": always_on,
            "send_telegram": False,
        })
    except Exception as exc:
        payload["agi_operator_cycle_error"] = str(exc)
    status_message = None
    status_message_error = None
    try:
        status_message = _runtime_live_watch_update_status_message(payload)
    except Exception as exc:
        status_message_error = str(exc)
    if status_message:
        payload["status_message"] = status_message
    if status_message_error:
        payload["status_message_error"] = status_message_error
    _write_json(LIVE_WATCH_STATE_PATH, payload)
    _append_event(
        "live_watch_run",
        {
            "filter": filter,
            "focus_status": focus_guard.get("status"),
            "focus_task_count": focus_guard.get("task_count"),
            "always_on": always_on,
            "companion_sent": companion.get("sent"),
            "companion_reason": companion.get("reason"),
            "companion_success": success,
            "surface_mode": surface_policy.get("mode"),
            "status_message_updated": bool(status_message),
            "status_message_error": status_message_error,
            "agi_decision": ((payload.get("agi_operator_cycle") or {}).get("decision") or {}).get("best_move"),
        },
    )
    return {
        "success": success,
        "ran_at": payload["ran_at"],
        "filter": filter,
        "always_on": always_on,
        "focus_guard": focus_guard,
        "adaptive_companion": companion,
        "surface_policy": surface_policy,
        "status_message": status_message,
        "status_message_error": status_message_error,
        "operator_brief": payload.get("operator_brief"),
        "operator_brief_error": payload.get("operator_brief_error"),
        "agi_operator_cycle": payload.get("agi_operator_cycle"),
        "agi_operator_cycle_error": payload.get("agi_operator_cycle_error"),
    }


def _runtime_parse_iso(ts: Optional[str]) -> Optional[datetime]:
    raw = str(ts or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _runtime_read_cron_jobs() -> Dict[str, Any]:
    data = _read_json(CRON_JOBS_PATH, {"jobs": []})
    if not isinstance(data, dict):
        return {"jobs": []}
    data.setdefault("jobs", [])
    return data


def _runtime_write_cron_jobs(data: Dict[str, Any]) -> None:
    _write_json(CRON_JOBS_PATH, data)


def _runtime_ensure_job_enabled(*, data: Dict[str, Any], job_id: str, expected_script: str, expected_expr: str) -> bool:
    jobs = list(data.get("jobs") or [])
    changed = False
    for job in jobs:
        if job.get("id") != job_id:
            continue
        if job.get("script") != expected_script:
            job["script"] = expected_script
            changed = True
        schedule = dict(job.get("schedule") or {})
        if schedule.get("expr") != expected_expr:
            job["schedule"] = {"kind": "cron", "expr": expected_expr, "display": expected_expr}
            job["schedule_display"] = expected_expr
            changed = True
        if not bool(job.get("enabled")):
            job["enabled"] = True
            changed = True
        if job.get("state") != "scheduled":
            job["state"] = "scheduled"
            changed = True
        break
    return changed


def _runtime_restart_user_service(service_name: str) -> Dict[str, Any]:
    result = subprocess.run(
        ["systemctl", "--user", "restart", service_name],
        capture_output=True,
        text=True,
        check=False,
        timeout=20,
    )
    return {
        "service": service_name,
        "ok": result.returncode == 0,
        "output": (result.stdout or result.stderr or "").strip(),
    }


def _runtime_detect_candidate_skills(*, companion_state: Dict[str, Any], runtime_events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    candidates: List[Dict[str, Any]] = []

    event_counts: Dict[tuple[str, str], int] = {}
    for item in runtime_events:
        if str(item.get("type") or "") != "runtime_event_ingested":
            continue
        event_type = str(item.get("event_type") or "").strip()
        source = str(item.get("source") or "").strip() or "unknown"
        if not event_type:
            continue
        key = (event_type, source)
        event_counts[key] = event_counts.get(key, 0) + 1

    for (event_type, source), count in sorted(event_counts.items(), key=lambda pair: (-pair[1], pair[0][0], pair[0][1])):
        if count < 3:
            continue
        candidates.append(
            {
                "id": f"workflow:{event_type}:{source}",
                "kind": "workflow",
                "title": f"Stabilize {event_type} workflow from {source}",
                "evidence": f"{count} recent '{event_type}' events came from {source}.",
                "why_it_matters": "This looks like a recurring transition Hermes can support with a more explicit method.",
                "next_step": f"Capture the best-response checklist for the {event_type} event and keep it reusable.",
            }
        )

    completion_history = list(companion_state.get("completion_history") or [])
    family_counts: Dict[tuple[str, str], int] = {}
    for item in completion_history:
        family = str(item.get("intervention_family") or item.get("family") or "").strip()
        pattern = str(item.get("pattern") or "").strip()
        if not family or not pattern:
            continue
        key = (family, pattern)
        family_counts[key] = family_counts.get(key, 0) + 1

    for (family, pattern), count in sorted(family_counts.items(), key=lambda pair: (-pair[1], pair[0][0], pair[0][1])):
        if count < 2:
            continue
        candidates.append(
            {
                "id": f"intervention:{family}:{pattern}",
                "kind": "intervention",
                "title": f"Reuse {family} for {pattern}",
                "evidence": f"{count} completed tasks followed this intervention-family and pattern pairing.",
                "why_it_matters": "Hermes is seeing the same pressure shape work more than once.",
                "next_step": "Promote this into a stable response pattern instead of rediscovering it each time.",
            }
        )

    style_counts: Dict[str, int] = {}
    for item in completion_history:
        style = str(item.get("style") or "").strip()
        if style:
            style_counts[style] = style_counts.get(style, 0) + 1

    for style, count in sorted(style_counts.items(), key=lambda pair: (-pair[1], pair[0])):
        if count < 3:
            continue
        candidates.append(
            {
                "id": f"style:{style}",
                "kind": "style",
                "title": f"Lean on {style} when completion matters",
                "evidence": f"{count} recent completions followed interventions rendered in the {style} style.",
                "why_it_matters": "A reliable delivery style is emerging, not just a one-off lucky message.",
                "next_step": "Preserve the strongest phrasing patterns from this style as a reusable template.",
            }
        )

    return candidates[:6]


def _runtime_self_improve_run() -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    prior_state = _read_json(SELF_IMPROVE_STATE_PATH, {}) if SELF_IMPROVE_STATE_PATH.exists() else {}
    actions: List[Dict[str, Any]] = []
    observations: List[str] = []
    service_memory = dict((prior_state or {}).get("service_memory") or {})
    services = [RUNTIME_SERVICE_NAME, "hermes-event-webhook.service"]
    if _env("TELEGRAM_CAPTURE_BOT_TOKEN"):
        services.append("hermes-capture-bot.service")
    for service_name in services:
        status = _runtime_service_status(service_name)
        if not status.get("active"):
            memory = dict(service_memory.get(service_name) or {})
            seen_failures = int(memory.get("inactive_streak") or 0) + 1
            service_memory[service_name] = {
                "inactive_streak": seen_failures,
                "last_state": status.get("state"),
                "last_checked_at": now.isoformat(),
            }
            if seen_failures >= 2:
                actions.append({"kind": "restart_service", **_runtime_restart_user_service(service_name), "inactive_streak": seen_failures})
                service_memory[service_name]["inactive_streak"] = 0
            else:
                observations.append(f"{service_name} inactive once; waiting for confirmation before restart")
        else:
            observations.append(f"{service_name} active")
            service_memory[service_name] = {
                "inactive_streak": 0,
                "last_state": status.get("state"),
                "last_checked_at": now.isoformat(),
            }

    live_watch = _read_json(LIVE_WATCH_STATE_PATH, {})
    live_watch_ran_at = _runtime_parse_iso((live_watch or {}).get("ran_at"))
    if live_watch_ran_at is None or (now - live_watch_ran_at) > timedelta(minutes=20):
        watch_result = _runtime_live_watch_run(filter="today | overdue", always_on=True)
        actions.append({"kind": "refresh_live_watch", "ok": bool(watch_result.get("success")), "ran_at": watch_result.get("ran_at")})
    else:
        observations.append("live watch current")
        if not (live_watch or {}).get("status_message") and _telegram_messages_allowed_now(now.astimezone().hour):
            payload = dict(live_watch or {})
            try:
                status_message = _runtime_live_watch_update_status_message(payload)
                if status_message:
                    payload["status_message"] = status_message
                    _write_json(LIVE_WATCH_STATE_PATH, payload)
                    actions.append({"kind": "restore_status_message", "ok": True, "message_id": status_message.get("message_id")})
            except Exception as exc:
                actions.append({"kind": "restore_status_message", "ok": False, "error": str(exc)})

    incidents = _runtime_recent_incidents(limit=10)
    if incidents:
        observations.append(f"{len(incidents)} recent incident(s)")
    upstream = _runtime_upstream_status(hours=24)
    behind = int(((upstream.get("local") or {}).get("behind")) or 0)
    if behind > 0:
        observations.append(f"upstream behind by {behind}")

    cron_data = _runtime_read_cron_jobs()
    repaired_jobs: List[str] = []
    if _runtime_ensure_job_enabled(data=cron_data, job_id="hermeslivewatch24x7", expected_script="hermes_live_watch.py", expected_expr="*/15 * * * *"):
        repaired_jobs.append("hermeslivewatch24x7")
    if _runtime_ensure_job_enabled(data=cron_data, job_id="hermesselfimprove24x7", expected_script="hermes_self_improve.py", expected_expr="*/15 * * * *"):
        repaired_jobs.append("hermesselfimprove24x7")
    if repaired_jobs:
        _runtime_write_cron_jobs(cron_data)
        actions.append({"kind": "repair_cron_jobs", "ok": True, "jobs": repaired_jobs})
    else:
        observations.append("cron jobs current")

    companion_state = _read_json(ADAPTIVE_COMPANION_STATE_PATH, {})
    runtime_events = _read_jsonl_recent(EVENTS_PATH, limit=120)
    candidate_skills = _runtime_detect_candidate_skills(
        companion_state=companion_state if isinstance(companion_state, dict) else {},
        runtime_events=runtime_events,
    )
    if candidate_skills:
        observations.append(f"{len(candidate_skills)} candidate skill(s) surfaced")

    state = {
        "ran_at": now.isoformat(),
        "actions": actions,
        "observations": observations,
        "incidents": incidents,
        "service_memory": service_memory,
        "candidate_skills": candidate_skills,
        "upstream": {
            "behind": behind,
            "recent_commit_count": int(upstream.get("recent_commit_count") or 0),
        },
    }
    _write_json(SELF_IMPROVE_STATE_PATH, state)
    _append_event("self_improve_run", {"actions": len(actions), "observations": observations[:5], "behind": behind, "incident_count": len(incidents)})
    return {
        "success": True,
        "ran_at": state["ran_at"],
        "actions": actions,
        "observations": observations,
        "incident_count": len(incidents),
        "upstream_behind": behind,
        "candidate_skills": candidate_skills,
        "summary": f"Self-improve checked {len(services)} service(s), took {len(actions)} action(s), and saw {len(incidents)} incident(s).",
    }


def _runtime_self_improve_report_signature(report: Dict[str, Any]) -> str:
    recommendations = [
        {
            "kind": item.get("kind"),
            "summary": item.get("summary"),
            "requires_approval": item.get("requires_approval"),
        }
        for item in list(report.get("recommendations") or [])
        if item.get("kind") != "no_action"
    ]
    payload = {
        "recommendations": recommendations,
        "upstream": report.get("upstream"),
        "incident_count": report.get("incident_count"),
        "candidate_skill_count": len(report.get("candidate_skills") or []),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _runtime_self_improve_report_message(report: Dict[str, Any], request_id: Optional[str]) -> str:
    recommendations = list(report.get("recommendations") or [])
    actionable = [item for item in recommendations if item.get("kind") != "no_action"]
    lines = [
        "Self-improvement report",
        report.get("summary") or f"Found {len(recommendations)} recommendation(s).",
    ]
    for index, item in enumerate(actionable[:5], start=1):
        approval = "approval needed" if item.get("requires_approval") else "safe maintenance"
        lines.append(f"{index}. {item.get('kind')}: {item.get('summary')} ({approval})")
        if item.get("proposed_action"):
            lines.append(f"   Proposed: {item.get('proposed_action')}")
    if not actionable:
        lines.append("No evidence-backed improvement needs action right now.")
    if request_id:
        lines.extend([
            f"Request ID: {request_id}",
            f"Approve: personal_security(action='approve_request', request_id='{request_id}')",
            f"Deny: personal_security(action='deny_request', request_id='{request_id}')",
        ])
    return "\n".join(lines)


def _runtime_self_improve_report(*, create_approval: bool = True, send_telegram: bool = True, force_send: bool = False) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    services = [RUNTIME_SERVICE_NAME, "hermes-event-webhook.service"]
    if _env("TELEGRAM_CAPTURE_BOT_TOKEN"):
        services.append("hermes-capture-bot.service")
    service_statuses = [_runtime_service_status(service_name) for service_name in services]
    inactive_services = [item for item in service_statuses if not item.get("active")]
    live_watch = _read_json(LIVE_WATCH_STATE_PATH, {})
    live_watch_ran_at = _runtime_parse_iso((live_watch or {}).get("ran_at"))
    live_watch_age_minutes = None
    if live_watch_ran_at:
        live_watch_age_minutes = int((now - live_watch_ran_at).total_seconds() // 60)
    incidents = _runtime_recent_incidents(limit=10)
    upstream = _runtime_upstream_status(hours=24)
    behind = int(((upstream.get("local") or {}).get("behind")) or 0)
    cron_data = _runtime_read_cron_jobs()
    cron_jobs = {str(job.get("id") or ""): job for job in list(cron_data.get("jobs") or []) if isinstance(job, dict)}
    companion_state = _read_json(ADAPTIVE_COMPANION_STATE_PATH, {})
    runtime_events = _read_jsonl_recent(EVENTS_PATH, limit=120)
    candidate_skills = _runtime_detect_candidate_skills(
        companion_state=companion_state if isinstance(companion_state, dict) else {},
        runtime_events=runtime_events,
    )
    recommendations: List[Dict[str, Any]] = []
    for service in inactive_services:
        recommendations.append({
            "kind": "service_health",
            "summary": f"{service.get('service')} is not active.",
            "proposed_action": "Confirm on the next self-improve run and restart only after repeated inactive checks.",
            "risk": "low_internal",
            "requires_approval": False,
            "evidence": service,
        })
    if live_watch_ran_at is None or (live_watch_age_minutes is not None and live_watch_age_minutes > 20):
        recommendations.append({
            "kind": "live_watch_refresh",
            "summary": "Live watch is stale or missing.",
            "proposed_action": "Run a live watch refresh so operator_brief and agi_operator_cycle stay current.",
            "risk": "low_internal",
            "requires_approval": False,
            "evidence": {"ran_at": (live_watch or {}).get("ran_at"), "age_minutes": live_watch_age_minutes},
        })
    if not (live_watch or {}).get("status_message"):
        recommendations.append({
            "kind": "status_message_restore",
            "summary": "Live watch status message is missing.",
            "proposed_action": "Restore the pinned/status message when Telegram quiet-hours allow it.",
            "risk": "low_internal",
            "requires_approval": False,
            "evidence": {"has_status_message": bool((live_watch or {}).get("status_message"))},
        })
    for job_id, expected_script in {"hermeslivewatch24x7": "hermes_live_watch.py", "hermesselfimprove24x7": "hermes_self_improve.py"}.items():
        job = cron_jobs.get(job_id)
        if not job or not job.get("enabled") or job.get("script") != expected_script:
            recommendations.append({
                "kind": "cron_repair",
                "summary": f"{job_id} is missing, disabled, or points at the wrong script.",
                "proposed_action": f"Ensure {job_id} runs {expected_script} every 15 minutes.",
                "risk": "low_internal",
                "requires_approval": False,
                "evidence": job or {"missing": True},
            })
    if behind > 0 or int(upstream.get("recent_commit_count") or 0) > 0:
        recommendations.append({
            "kind": "upstream_review",
            "summary": f"Hermes upstream has changes; local checkout is {behind} commit(s) behind.",
            "proposed_action": "Review upstream changes before applying code updates.",
            "risk": "code_change_requires_review",
            "requires_approval": True,
            "evidence": {"behind": behind, "recent_commit_count": int(upstream.get("recent_commit_count") or 0)},
        })
    if incidents:
        recommendations.append({
            "kind": "incident_review",
            "summary": f"{len(incidents)} recent incident(s) need inspection.",
            "proposed_action": "Inspect incidents and propose targeted fixes instead of guessing.",
            "risk": "diagnostic_only",
            "requires_approval": False,
            "evidence": incidents[:5],
        })
    if candidate_skills:
        recommendations.append({
            "kind": "candidate_skill_review",
            "summary": f"{len(candidate_skills)} candidate improvement pattern(s) surfaced.",
            "proposed_action": "Review candidate skills and approve implementation separately if useful.",
            "risk": "design_change_requires_review",
            "requires_approval": True,
            "evidence": candidate_skills[:5],
        })
    if not recommendations:
        recommendations.append({
            "kind": "no_action",
            "summary": "No useful self-improvement action is currently supported by evidence.",
            "proposed_action": "Stay quiet and check again later.",
            "risk": "none",
            "requires_approval": False,
            "evidence": {"services_checked": len(services), "incidents": 0, "upstream_behind": behind},
        })
    report = {
        "generated_at": now.isoformat(),
        "summary": f"Self-improve report found {len(recommendations)} recommendation(s).",
        "services": service_statuses,
        "live_watch": {
            "ran_at": (live_watch or {}).get("ran_at"),
            "age_minutes": live_watch_age_minutes,
            "has_operator_brief": bool((live_watch or {}).get("operator_brief")),
            "has_agi_operator_cycle": bool((live_watch or {}).get("agi_operator_cycle")),
        },
        "upstream": {"behind": behind, "recent_commit_count": int(upstream.get("recent_commit_count") or 0)},
        "incident_count": len(incidents),
        "candidate_skills": candidate_skills,
        "recommendations": recommendations,
        "approval_policy": "Applying maintenance is approval-gated through personal_security. Code changes, external messages, public posts, financial actions, and destructive edits remain separate approvals.",
    }
    signature = _runtime_self_improve_report_signature(report)
    state = _read_json(SELF_IMPROVE_STATE_PATH, {}) if SELF_IMPROVE_STATE_PATH.exists() else {}
    state = state if isinstance(state, dict) else {}
    report_state = dict((state or {}).get("report_delivery") or {})
    last_sent_at = _runtime_parse_iso(str(report_state.get("last_sent_at") or ""))
    last_signature = str(report_state.get("last_signature") or "")
    recently_sent = bool(last_sent_at and (now - last_sent_at) < timedelta(hours=12) and last_signature == signature)
    can_send_now = bool(force_send or _telegram_messages_allowed_now())
    should_create_approval = bool(create_approval and (not send_telegram or (not recently_sent and can_send_now)))
    request_id: Optional[str] = None
    response: Dict[str, Any]
    if not should_create_approval:
        response = {"success": True, "action": "self_improve_report", "report": report, "approval_required": False}
    else:
        approval_payload = {"action": "self_improve_apply", "report": report}
        response = json.loads(_create_approval(
            tool_name="personal_runtime",
            action="apply_self_improve_report",
            summary="apply Hermes self-improvement maintenance plan",
            reason="Hermes found maintenance or review items and should not apply them invisibly.",
            benefit="You get a visible report first, then approve only if the plan looks right.",
            payload=approval_payload,
        ))
        request_id = str(response.get("request_id") or "")
        response = {
            **response,
            "action": "self_improve_report",
            "report": report,
        }
    if send_telegram and not recently_sent and can_send_now:
        message = _runtime_self_improve_report_message(report, request_id or str(response.get("request_id") or ""))
        send_result = _focus_guard_send_telegram_message(message)
        response["sent"] = not bool(send_result.get("suppressed"))
        response["send_result"] = send_result
        response["send_reason"] = "sent" if response["sent"] else str(send_result.get("reason") or "suppressed")
        state = state if isinstance(state, dict) else {}
        state["report_delivery"] = {
            "last_sent_at": now.isoformat(),
            "last_signature": signature,
            "last_request_id": request_id or response.get("request_id"),
        }
        _write_json(SELF_IMPROVE_STATE_PATH, state)
    elif send_telegram:
        response["sent"] = False
        response["send_reason"] = "same_report_recently_sent" if recently_sent else "outside_hours"
    else:
        response["sent"] = False
        response["send_reason"] = "telegram_disabled"
    return response


def _self_improve_pipeline_stages() -> List[str]:
    return ["detect", "classify", "branch", "patch", "test", "diff", "approval", "deploy", "verify", "rollback"]


def _self_improve_pipeline_artifacts(pipeline_id: str) -> Dict[str, str]:
    artifact_dir = HERMES_HOME / "self_improve_artifacts" / pipeline_id
    return {
        "artifact_dir": str(artifact_dir),
        "patch_plan_path": str(artifact_dir / "patch_plan.md"),
        "test_summary_path": str(artifact_dir / "test_summary.json"),
        "diff_summary_path": str(artifact_dir / "diff_summary.md"),
        "rollback_notes_path": str(artifact_dir / "rollback_notes.md"),
    }


def _self_improve_pipeline_write_artifacts(pipeline: Dict[str, Any], *, stage_label: str) -> None:
    artifacts = dict(pipeline.get("artifacts") or {})
    artifact_dir = Path(str(artifacts.get("artifact_dir") or "")).expanduser()
    if not artifact_dir:
        return
    artifact_dir.mkdir(parents=True, exist_ok=True)
    def _write_artifact_text(path_value: str, content: str) -> None:
        path = Path(str(path_value or "")).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    proposal_ids = list(pipeline.get("proposal_ids") or [])
    verify_checklist = list(pipeline.get("verify_checklist") or [])
    rollback = dict(pipeline.get("rollback") or {})
    test_commands = list(pipeline.get("test_commands") or [])
    proposal_lines = [f"- `{proposal_id}`" for proposal_id in proposal_ids] or ["- `runtime_self_improve_report`"]
    stage_lines = [f"- `{stage}`" for stage in list(pipeline.get("stages") or [])]
    checklist_lines = [f"- `{item}`" for item in verify_checklist]
    rollback_lines = [f"- `{item}`" for item in list(rollback.get("preserve_artifacts") or [])]
    patch_plan = "\n".join(
        [
            "# Hermes Self-Improve Patch Plan",
            "",
            f"- Pipeline ID: `{pipeline.get('pipeline_id')}`",
            f"- Stage: `{stage_label}`",
            f"- Branch: `{pipeline.get('branch_name')}`",
            f"- Summary: {pipeline.get('summary')}",
            "",
            "## Proposal Scope",
            *proposal_lines,
            "",
            "## Planned Stages",
            *stage_lines,
            "",
            "## Verify Checklist",
            *checklist_lines,
            "",
        ]
    ).strip() + "\n"
    _write_artifact_text(str(artifacts.get("patch_plan_path") or ""), patch_plan)

    test_summary = {
        "pipeline_id": pipeline.get("pipeline_id"),
        "stage": stage_label,
        "test_commands": test_commands,
        "verify_checklist": verify_checklist,
        "status": "pending_execution" if stage_label == "proposed" else "approved_ready_for_patch",
    }
    _write_json(Path(str(artifacts.get("test_summary_path") or "")).expanduser(), test_summary)

    diff_summary = "\n".join(
        [
            "# Hermes Diff Summary",
            "",
            f"- Pipeline ID: `{pipeline.get('pipeline_id')}`",
            f"- Stage: `{stage_label}`",
            f"- Diff Strategy: {pipeline.get('diff_strategy')}",
            "",
            "No patch has been generated yet. This artifact reserves the review surface for the eventual branch diff.",
            "",
        ]
    ).strip() + "\n"
    _write_artifact_text(str(artifacts.get("diff_summary_path") or ""), diff_summary)

    rollback_notes = "\n".join(
        [
            "# Hermes Rollback Notes",
            "",
            f"- Pipeline ID: `{pipeline.get('pipeline_id')}`",
            f"- Stage: `{stage_label}`",
            f"- Strategy: {rollback.get('strategy') or 'unspecified' }",
            "",
            "## Preserve Artifacts",
            *rollback_lines,
            "",
        ]
    ).strip() + "\n"
    _write_artifact_text(str(artifacts.get("rollback_notes_path") or ""), rollback_notes)


def _build_self_improve_pipeline(proposals: List[Dict[str, Any]]) -> Dict[str, Any]:
    now_iso = datetime.now(timezone.utc).isoformat()
    first = dict(proposals[0] if proposals else {})
    slug_source = str(first.get("kind") or first.get("task_title") or "general").lower().replace(" ", "-").replace("_", "-")
    slug = "".join(ch for ch in slug_source if ch.isalnum() or ch == "-").strip("-") or "general"
    pipeline_id = f"pipeline_{uuid.uuid4().hex[:10]}"
    return {
        "pipeline_id": pipeline_id,
        "created_at": now_iso,
        "proposal_ids": [item.get("proposal_id") for item in proposals if item.get("proposal_id")],
        "branch_name": f"hermes/self-improve/{slug}",
        "stages": _self_improve_pipeline_stages(),
        "current_stage": "detect",
        "next_stage": "classify",
        "test_commands": [
            "pytest tests/plugins/test_personal_ops_todoist.py -q",
            "$env:PYTHONPATH='C:\\Users\\Marketplace\\temp-personal-ops'; pytest tests -q",
        ],
        "diff_strategy": "review_generated_patch_and_runtime_trace_changes_before_apply",
        "rollback": {
            "strategy": "revert_branch_or_restore_previous_runtime_state",
            "preserve_artifacts": ["self_improve_report", "promptfoo_eval_cases", "runtime_traces"],
        },
        "artifacts": _self_improve_pipeline_artifacts(pipeline_id),
        "verify_checklist": ["run_targeted_tests", "run_full_plugin_suite", "inspect_diff_summary", "confirm_rollback_notes"],
        "status": "proposed",
        "summary": f"Reviewed GitOps self-improvement pipeline for {len(proposals)} proposal(s).",
    }


def _runtime_self_improve_pipeline(args: Dict[str, Any]) -> Dict[str, Any]:
    mode = str(args.get("mode") or "status").strip().lower()
    state = _self_improve_pipelines_read()
    pipelines = list(state.get("pipelines") or [])
    if mode == "status":
        return {"success": True, "action": "self_improve_pipeline", "mode": mode, "pipeline_count": len(pipelines), "pipelines": pipelines[-20:]}
    if mode == "propose":
        proposals = list((_self_improve_proposals_read().get("proposals") or []))
        if not proposals:
            proposals = [{
                "proposal_id": "runtime_self_improve_report",
                "kind": "maintenance_review",
                "task_title": "Hermes self-improvement maintenance",
            }]
        pipeline = _build_self_improve_pipeline(proposals)
        _self_improve_pipeline_write_artifacts(pipeline, stage_label="proposed")
        pipelines.append(pipeline)
        state["pipelines"] = pipelines[-100:]
        _self_improve_pipelines_write(state)
        response = json.loads(_create_approval(
            tool_name="personal_runtime",
            action="self_improve_pipeline_apply",
            summary="Approve Hermes self-improvement GitOps pipeline",
            reason="Code and systems improvements should move through a visible reviewed pipeline instead of silent mutation.",
            benefit="You get an explicit branch/test/diff/rollback plan before Hermes advances the pipeline.",
            payload={"action": "self_improve_pipeline_apply", "pipeline": pipeline},
        ))
        response["pipeline"] = pipeline
        return response
    raise ValueError(f"Unsupported self_improve_pipeline mode: {mode}")


def _runtime_external_systems_status(args: Dict[str, Any]) -> Dict[str, Any]:
    del args
    calendar_status = _runtime_calendar_status({})
    calendar_provider = _calendar_provider()
    systems = {
        "calendar": {
            "configured": bool(calendar_provider),
            "role": "timing_and_availability_signal",
            "access_mode": "observe_or_draft",
            "risk_policy": "never_mutate_without_explicit_approval",
            "provider": calendar_status.get("provider"),
            "status_mode": calendar_status.get("mode"),
        },
        "home_assistant": {
            "configured": bool(_env_first("HERMES_HOME_ASSISTANT_URL", "HOME_ASSISTANT_URL")),
            "role": "household_context_signal",
            "access_mode": "observe_first",
            "risk_policy": "no_device_control_without_explicit_approval",
        },
        "paperless": {
            "configured": bool(_env_first("HERMES_PAPERLESS_URL", "PAPERLESS_URL")),
            "role": "document_lookup_and_admin_grounding",
            "access_mode": "read_only",
            "risk_policy": "never_delete_or_modify_documents_without_explicit_approval",
        },
        "actual_budget": {
            "configured": bool(_env_first("HERMES_ACTUAL_BUDGET_URL", "ACTUAL_BUDGET_URL")),
            "role": "budget_review_and_cost_visibility",
            "access_mode": "read_only",
            "risk_policy": "read_only_budget_review",
        },
    }
    return {"success": True, "action": "external_systems_status", "systems": systems}


def _runtime_hermes_capabilities_dossier(args: Dict[str, Any]) -> Dict[str, Any]:
    del args
    calendar = _runtime_calendar_status({})
    external = _runtime_external_systems_status({})
    profiles = _runtime_isolation_profile_plan({})
    jobs = _runtime_orchestration_job({"mode": "status", "limit": 10})
    return {
        "success": True,
        "action": "hermes_capabilities_dossier",
        "identity": {
            "mode": "bounded_personal_operations_kernel",
            "scope": "Hermes is a disciplined personal operator with memory, common sense, approvals, traces, and task-system operations.",
        },
        "calendar": {
            "provider": calendar.get("provider"),
            "status": "browser_handoff_ready" if calendar.get("configured") else "unconfigured",
            "approval_policy": calendar.get("approval_policy"),
            "mode": calendar.get("mode"),
        },
        "external_systems": external.get("systems"),
        "orchestration_governance": {
            "profiles": profiles.get("profiles"),
            "job_board": {
                "status": "live" if jobs.get("success") else "degraded",
                "job_count": jobs.get("job_count"),
                "latest_jobs": jobs.get("jobs"),
            },
            "controller_worker_rule": "Hermes may plan/review/approve-request; workers produce artifacts only and never deploy or approve themselves.",
        },
        "live_layers": [
            "core_state_machine",
            "adaptive_nudge_intelligence",
            "memory_and_todoist_operations",
            "observability_and_evals",
            "gitops_self_improve_pipeline",
            "controller_worker_job_board",
        ],
        "boundaries": [
            "approval_gated",
            "approval_gated_external_writes",
            "browser_backed_calendar_handoff",
            "read_only_budget_review",
            "no_silent_destructive_actions",
            "intention_gate_before_worker_dispatch",
        ],
    }


def _runtime_hermes_system_audit(args: Dict[str, Any]) -> Dict[str, Any]:
    del args
    snapshot = _operating_snapshot({})
    presence = _runtime_presence_status()
    trace_status = _runtime_trace_status({})
    calendar = _runtime_calendar_status({})
    external = _runtime_external_systems_status({})
    memory = _runtime_memory_console({"mode": "list"})
    rules = _runtime_todoist_rule_store({"mode": "status"})
    pipeline = _runtime_self_improve_pipeline({"mode": "status"})
    eval_export = _runtime_eval_suite_export({})
    snapshot_payload = dict(snapshot.get("snapshot") or {})
    presence_snapshot = dict(snapshot_payload.get("presence") or {})
    trace_runtime_ok = bool(trace_status.get("success"))
    trace_langfuse_ok = bool((trace_status.get("langfuse") or {}).get("configured"))
    surfaces = {
        "core_state_machine": {
            "status": "live" if snapshot.get("success") and snapshot_payload else "degraded",
            "details": {
                "has_presence_slice": bool(presence_snapshot),
                "has_adaptive_nudge_slice": bool(snapshot_payload.get("adaptive_nudge")),
                "event_count": int((snapshot.get("normalized_events") or {}).get("count") or 0),
            },
        },
        "presence_model": {
            "status": "live" if presence.get("configured") and str((presence.get("last_signal") or {}).get("source") or "") == "activitywatch-forwarder" else "degraded",
            "details": {
                "source": (presence.get("last_signal") or {}).get("source"),
                "confidence": presence.get("confidence"),
                "activitywatch_forwarder_primary": str((presence.get("last_signal") or {}).get("source") or "") == "activitywatch-forwarder",
                "server_local_activitywatch_configured": bool((presence.get("activitywatch") or {}).get("configured")),
            },
        },
        "adaptive_nudge": {
            "status": "live" if snapshot_payload.get("adaptive_nudge") else "degraded",
            "details": dict(snapshot_payload.get("adaptive_nudge") or {}),
        },
        "memory_console": {
            "status": "live" if memory.get("success") else "degraded",
            "details": {"memory_count": memory.get("memory_count"), "mode": memory.get("mode")},
        },
        "todoist_rule_store": {
            "status": "live" if rules.get("success") else "degraded",
            "details": {"rule_count": rules.get("rule_count"), "task_metadata_count": rules.get("task_metadata_count")},
        },
        "tracing": {
            "status": "live" if (trace_runtime_ok and trace_langfuse_ok) else "local_live" if trace_runtime_ok else "degraded",
            "details": {
                "trace_count": trace_status.get("trace_count"),
                "langfuse_configured_now": trace_langfuse_ok,
            },
        },
        "evals": {
            "status": "live" if eval_export.get("success") else "degraded",
            "details": {"case_count": eval_export.get("case_count"), "config_path": eval_export.get("config_path")},
        },
        "self_improve_pipeline": {
            "status": "live" if pipeline.get("success") else "degraded",
            "details": {"pipeline_count": pipeline.get("pipeline_count")},
        },
        "calendar": {
            "status": "live" if calendar.get("configured") and calendar.get("provider") == "browser_google_calendar" else "degraded",
            "details": {
                "provider": calendar.get("provider"),
                "mode": calendar.get("mode"),
                "approval_policy": calendar.get("approval_policy"),
            },
        },
        "home_assistant": {
            "status": "scaffolded" if (external.get("systems") or {}).get("home_assistant", {}).get("configured") else "unconfigured",
            "details": (external.get("systems") or {}).get("home_assistant", {}),
        },
        "paperless": {
            "status": "scaffolded" if (external.get("systems") or {}).get("paperless", {}).get("configured") else "unconfigured",
            "details": (external.get("systems") or {}).get("paperless", {}),
        },
        "actual_budget": {
            "status": "scaffolded" if (external.get("systems") or {}).get("actual_budget", {}).get("configured") else "unconfigured",
            "details": (external.get("systems") or {}).get("actual_budget", {}),
        },
    }
    non_connected = []
    if not bool((trace_status.get("langfuse") or {}).get("configured")):
        non_connected.append("Langfuse is not currently configured in the live Hermes runtime; local trace receipts still work.")
    if not bool((presence.get("activitywatch") or {}).get("configured")):
        non_connected.append("Server-local ActivityWatch polling is not configured; forwarded ActivityWatch heartbeats are the real live presence source.")
    for name in ("home_assistant", "paperless", "actual_budget"):
        if surfaces[name]["status"] == "scaffolded":
            non_connected.append(f"{name} is scaffolded and policy-bounded, not a fully exercised end-to-end integration yet.")
    overall_status = "honest_with_gaps" if non_connected else "fully_live_for_audited_surfaces"
    return {
        "success": True,
        "action": "hermes_system_audit",
        "overall_status": overall_status,
        "surfaces": surfaces,
        "non_connected": non_connected,
    }


def _runtime_live_watch_status() -> Dict[str, Any]:
    payload = _read_json(LIVE_WATCH_STATE_PATH, {})
    if not isinstance(payload, dict) or not payload:
        return {
            "configured": False,
            "summary": "No live watch run recorded yet.",
            "ran_at": None,
            "focus_guard": None,
            "adaptive_companion": None,
            "status_message": None,
        }

    companion = payload.get("adaptive_companion") or {}
    focus_guard = payload.get("focus_guard") or {}
    if companion.get("sent"):
        summary = "Live watch is active and the last cycle sent a Telegram message."
    else:
        reason = str(companion.get("reason") or "unknown").strip() or "unknown"
        summary = f"Live watch is active. Last cycle stayed quiet because: {reason}."
    return {
        "configured": True,
        "summary": summary,
        "ran_at": payload.get("ran_at"),
        "filter": payload.get("filter"),
        "focus_guard": focus_guard,
        "adaptive_companion": companion,
        "operator_brief": payload.get("operator_brief"),
        "operator_brief_error": payload.get("operator_brief_error"),
        "agi_operator_cycle": payload.get("agi_operator_cycle"),
        "agi_operator_cycle_error": payload.get("agi_operator_cycle_error"),
        "status_message": payload.get("status_message"),
    }


def _runtime_live_watch_status_message(payload: Dict[str, Any]) -> str:
    focus_guard = dict(payload.get("focus_guard") or {})
    companion = dict(payload.get("adaptive_companion") or {})
    companion_state = dict(companion.get("state") or {})
    lenses = dict(companion_state.get("insight_lenses") or {})
    surface = dict(payload.get("surface_policy") or lenses.get("surface_policy") or {})
    if not surface:
        fallback_state = dict(companion_state)
        fallback_state["insight_lenses"] = lenses
        surface = _adaptive_companion_surface_policy(state=fallback_state, focus_state=focus_guard)
    target = str(((focus_guard.get("most_important_task") or {}).get("content") or "")).strip() or "None"
    suspicious_labels = [
        str(((item.get("task") or {}).get("content") or "")).strip()
        for item in list(focus_guard.get("suspicious_tasks") or [])[:3]
        if str(((item.get("task") or {}).get("content") or "")).strip()
    ]
    reason = str(companion.get("reason") or "").strip()
    summary = "sent a Telegram nudge" if companion.get("sent") else f"stayed quiet ({reason or 'unknown'})"
    ran_at = str(payload.get("ran_at") or "").strip() or "unknown"
    filter_text = str(payload.get("filter") or "all tasks").strip()
    lines = ["Hermes Live Watch", f"Last run: {ran_at}", f"Top task: {target}", f"Last decision: {summary}"]
    if suspicious_labels:
        lines.insert(3, f"Flagged side task: {suspicious_labels[0]}")
    if not surface.get("compact_status"):
        lines.insert(2, f"Filter: {filter_text}")
        lines.insert(3, f"Focus status: {focus_guard.get('status', 'unknown')}")
    threshold = dict(lenses.get("threshold_detection") or {})
    if threshold:
        lines.append(f"Threshold: {threshold.get('level', 'low')} - {threshold.get('signal', '')}".strip())
    recovery = dict(lenses.get("recovery_intelligence") or {})
    if recovery:
        lines.append(f"Recovery: {recovery.get('mode', 'pressure')} - {recovery.get('suggestion', '')}".strip())
    respect = dict(lenses.get("respect_engine") or {})
    if respect and respect.get("note") and not surface.get("compact_status"):
        lines.append(f"Respect: {respect.get('note')}")
    silent = list(lenses.get("silent_interventions") or [])
    if silent:
        lines.append(f"Silent move: {silent[0]}")
    if surface.get("mode"):
        lines.append(f"Surface: {surface.get('mode')}")
    return "\n".join(line for line in lines if line).strip()


def _runtime_live_watch_update_status_message(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if _env("LIVE_WATCH_STATUS_MESSAGE").strip().lower() in {"0", "false", "no", "off"}:
        return None

    state = _read_json(LIVE_WATCH_STATE_PATH, {})
    prior_status = dict((state or {}).get("status_message") or {})
    _, default_chat_id = _focus_guard_telegram_config()
    target_chat_id = str(prior_status.get("chat_id") or default_chat_id).strip()
    text = _runtime_live_watch_status_message(payload)
    message_id = prior_status.get("message_id")

    if message_id:
        response = _focus_guard_telegram_post(
            "editMessageText",
            {
                "chat_id": target_chat_id,
                "message_id": int(message_id),
                "text": text,
            },
        )
        result = response.get("result")
        resolved_message_id = int(message_id)
        if isinstance(result, dict):
            resolved_message_id = int(result.get("message_id") or resolved_message_id)
        return {"chat_id": target_chat_id, "message_id": resolved_message_id}

    response = _focus_guard_telegram_post(
        "sendMessage",
        {
            "chat_id": target_chat_id,
            "text": text,
            "disable_notification": True,
        },
    )
    result = response.get("result") or {}
    resolved_message_id = int(result.get("message_id") or 0)
    status_payload = {"chat_id": target_chat_id, "message_id": resolved_message_id}
    if resolved_message_id and _env("LIVE_WATCH_PIN_STATUS").strip().lower() in {"1", "true", "yes", "on"}:
        _focus_guard_telegram_post(
            "pinChatMessage",
            {
                "chat_id": target_chat_id,
                "message_id": resolved_message_id,
                "disable_notification": True,
            },
        )
    return status_payload


def _runtime_ensure_todoist_mcp() -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    if HERMES_CONFIG_PATH.exists():
        raw = HERMES_CONFIG_PATH.read_text(encoding="utf-8")
        loaded = yaml.safe_load(raw) if yaml is not None else _minimal_yaml_load(raw)
        loaded = loaded or {}
        if isinstance(loaded, dict):
            data = loaded
    servers = dict(data.get("mcp_servers") or {})
    expected = {
        "url": "https://ai.todoist.net/mcp",
        "auth": "oauth",
        "enabled": False,
        "timeout": 120,
        "connect_timeout": 60,
    }
    prior = dict(servers.get("todoist") or {})
    changed = prior != {**prior, **expected}
    servers["todoist"] = {**prior, **expected}
    data["mcp_servers"] = servers
    if changed or not HERMES_CONFIG_PATH.exists():
        HERMES_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        if yaml is not None:
            rendered = yaml.safe_dump(data, sort_keys=False)
        else:
            rendered = _minimal_yaml_dump(data)
        HERMES_CONFIG_PATH.write_text(rendered, encoding="utf-8")
    return {
        "success": True,
        "changed": changed,
        "mcp_servers": sorted(servers.keys()),
        "todoist": servers["todoist"],
        "summary": (
            "Todoist hosted MCP is recorded but disabled for 24/7 reliability. "
            "Hermes uses the stable Todoist API-token path as primary; enable OAuth MCP only for diagnostics."
        ),
    }


def _approval_response(request_id: str, summary: str, reason: str, benefit: str) -> str:
    return _tool_result(
        success=False,
        approval_required=True,
        request_id=request_id,
        summary=summary,
        reason=reason,
        benefit=benefit,
        message=(
            f"Approval required for {summary}. Reason: {reason} Benefit: {benefit}. "
            f"Approve with personal_security(action='approve_request', request_id='{request_id}') "
            f"or deny with personal_security(action='deny_request', request_id='{request_id}')."
        ),
    )


def _create_approval(*, tool_name: str, action: str, summary: str, reason: str, benefit: str, payload: Dict[str, Any]) -> str:
    approvals = _load_approvals()
    request_id = f"req_{uuid.uuid4().hex[:10]}"
    approvals["pending"][request_id] = {
        "request_id": request_id,
        "tool": tool_name,
        "action": action,
        "summary": summary,
        "reason": reason,
        "benefit": benefit,
        "payload": payload,
        "created_at": _now(),
    }
    approvals["history"].append(
        {
            "request_id": request_id,
            "event": "created",
            "tool": tool_name,
            "action": action,
            "summary": summary,
            "ts": _now(),
        }
    )
    _save_approvals(approvals)
    _append_event(
        "approval_created",
        {"request_id": request_id, "tool": tool_name, "action": action, "summary": summary},
    )
    return _approval_response(request_id, summary, reason, benefit)


def _pop_pending(request_id: str) -> Optional[Dict[str, Any]]:
    approvals = _load_approvals()
    pending = approvals.get("pending", {}).pop(request_id, None)
    if pending is not None:
        approvals["history"].append(
            {
                "request_id": request_id,
                "event": "removed",
                "tool": pending.get("tool"),
                "action": pending.get("action"),
                "summary": pending.get("summary"),
                "ts": _now(),
            }
        )
        _save_approvals(approvals)
    return pending


def _todoist_headers() -> Dict[str, str]:
    token = _env_first("TODOIST_API_TOKEN", "TODOIST_API_KEY")
    if not token:
        raise ValueError("TODOIST_API_TOKEN or TODOIST_API_KEY is not configured in ~/.hermes/.env")
    return {"Authorization": f"Bearer {token}"}


def _clickup_headers() -> Dict[str, str]:
    token = _env("CLICKUP_API_TOKEN")
    if not token:
        raise ValueError("CLICKUP_API_TOKEN is not configured in ~/.hermes/.env")
    return {"Authorization": token, "Content-Type": "application/json"}


def _clickup_allowed_space_id() -> str:
    value = str(_env("CLICKUP_ALLOWED_SPACE_ID") or "").strip()
    if not value:
        raise ValueError("CLICKUP_ALLOWED_SPACE_ID is required")
    return value


def _clickup_allowed_folder_name() -> str:
    return str(_env("CLICKUP_ALLOWED_FOLDER_NAME") or "my stuff").strip()


def _resolve_clickup_boundary(client: Any) -> Dict[str, Any]:
    space_id = _clickup_allowed_space_id()
    folder_name = _clickup_allowed_folder_name().lower()

    folder_resp = client.get(f"{CLICKUP_BASE}/space/{space_id}/folder", headers=_clickup_headers())
    folder_resp.raise_for_status()
    folders = (folder_resp.json() or {}).get("folders") or []
    matches = [folder for folder in folders if str(folder.get("name") or "").strip().lower() == folder_name]
    if not matches:
        raise ValueError(f"Allowed ClickUp folder '{_clickup_allowed_folder_name()}' was not found in space {space_id}")
    if len(matches) > 1:
        raise ValueError(f"Multiple ClickUp folders matched '{_clickup_allowed_folder_name()}'; refusing to guess")

    folder = matches[0]
    folder_id = str(folder.get("id") or "").strip()
    list_resp = client.get(f"{CLICKUP_BASE}/folder/{folder_id}/list", headers=_clickup_headers())
    list_resp.raise_for_status()
    lists = (list_resp.json() or {}).get("lists") or []
    if not lists:
        raise ValueError(f"Allowed ClickUp folder '{folder.get('name')}' has no lists")

    clean_lists = [{"id": str(item.get("id")), "name": item.get("name")} for item in lists if item.get("id") is not None]
    return {
        "space_id": space_id,
        "folder": {"id": folder_id, "name": folder.get("name")},
        "lists": clean_lists,
        "list_ids": {item["id"] for item in clean_lists},
    }


def _public_clickup_boundary(boundary: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not boundary:
        return boundary
    return {
        "space_id": boundary.get("space_id"),
        "folder": boundary.get("folder"),
        "lists": boundary.get("lists", []),
        "list_ids": sorted(boundary.get("list_ids", [])),
    }


def _twilio_auth() -> tuple[str, str, str]:
    sid = _env_first("PERSONAL_TWILIO_ACCOUNT_SID", "TWILIO_ACCOUNT_SID")
    token = _env_first("PERSONAL_TWILIO_AUTH_TOKEN", "TWILIO_AUTH_TOKEN")
    from_number = _env_first("PERSONAL_TWILIO_PHONE_NUMBER", "TWILIO_PHONE_NUMBER")
    if not sid or not token or not from_number:
        raise ValueError(
            "PERSONAL_TWILIO_ACCOUNT_SID/PERSONAL_TWILIO_AUTH_TOKEN/PERSONAL_TWILIO_PHONE_NUMBER "
            "or TWILIO_ACCOUNT_SID/TWILIO_AUTH_TOKEN/TWILIO_PHONE_NUMBER must be configured in ~/.hermes/.env"
        )
    return sid, token, from_number


def _execute_todoist(payload: Dict[str, Any]) -> Dict[str, Any]:
    action = payload.get("action")
    with _http_client() as client:
        if action == "add_task":
            body = {
                k: v
                for k, v in payload.items()
                if k
                in {
                    "content",
                    "description",
                    "project_id",
                    "section_id",
                    "labels",
                    "priority",
                    "due_string",
                    "due_datetime",
                }
                and v not in (None, "", [])
            }
            resp = client.post(f"{TODOIST_BASE}/tasks", headers=_todoist_headers(), json=body)
            resp.raise_for_status()
            return {"success": True, "action": action, "task": resp.json()}
        if action == "close_task":
            task_id = str(payload.get("task_id") or "").strip()
            if "id=" in task_id:
                task_id = task_id.split("id=")[-1]
            elif "/" in task_id:
                task_id = task_id.rstrip("/").split("/")[-1]
            if not task_id:
                raise ValueError("task_id is required")
            resp = client.post(f"{TODOIST_BASE}/tasks/{task_id}/close", headers=_todoist_headers())
            resp.raise_for_status()
            state = _adaptive_companion_read_state()
            state = _adaptive_companion_record_task_completion(
                state=state,
                task_id=task_id,
                completed_at=datetime.now(timezone.utc).isoformat(),
            )
            latest = list(state.get("recent_interventions") or [])
            latest_item = dict(latest[-1] or {}) if latest else {}
            state = _adaptive_companion_refresh_insight_lenses(
                state=state,
                trigger={
                    "task_label": latest_item.get("task_label"),
                    "evidence": latest_item.get("message") or "",
                    "kind": latest_item.get("trigger") or "completion",
                },
                pattern=latest_item.get("pattern") or {"label": "momentum_present"},
                focus_state={"status": "needs_focus", "task_count": 0, "suspicious_tasks": []},
                now_hour=_adaptive_companion_now_local_hour(),
            )
            _adaptive_companion_write_state(state)
            return {"success": True, "action": action, "task_id": task_id}
        if action == "reopen_task":
            task_id = str(payload.get("task_id") or "").strip()
            if "id=" in task_id:
                task_id = task_id.split("id=")[-1]
            elif "/" in task_id:
                task_id = task_id.rstrip("/").split("/")[-1]
            if not task_id:
                raise ValueError("task_id is required")
            resp = client.post(f"{TODOIST_BASE}/tasks/{task_id}/reopen", headers=_todoist_headers())
            resp.raise_for_status()
            return {"success": True, "action": action, "task_id": task_id}
        if action == "update_task":
            task_id = str(payload.get("task_id") or "").strip()
            if "id=" in task_id:
                task_id = task_id.split("id=")[-1]
            elif "/" in task_id:
                task_id = task_id.rstrip("/").split("/")[-1]
            if not task_id:
                raise ValueError("task_id is required for update_task")
            body = {
                k: v
                for k, v in payload.items()
                if k
                in {
                    "content",
                    "description",
                    "due_string",
                    "due_date",
                    "due_datetime",
                    "labels",
                    "priority",
                }
                and v not in (None, "", [])
            }
            resp = client.post(f"{TODOIST_BASE}/tasks/{task_id}", headers=_todoist_headers(), json=body)
            resp.raise_for_status()
            return {"success": True, "action": action, "task_id": task_id, "task": resp.json()}
    raise ValueError(f"Unsupported Todoist approval action: {action}")


def _enrich_and_sort_todoist_hierarchy(tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not tasks:
        return []

    task_map = {t.get("id"): t for t in tasks if t.get("id")}

    for t in tasks:
        parent_id = t.get("parent_id") or t.get("parentId")
        if parent_id and parent_id in task_map:
            t["is_subtask"] = True
            parent_task = task_map[parent_id]
            t["parent_content"] = str(parent_task.get("content") or parent_task.get("name") or parent_task.get("title") or "").strip()
            t["indentation_level"] = 1
        else:
            t["is_subtask"] = False
            t["parent_content"] = None
            t["indentation_level"] = 0

    roots = []
    children_map = {}

    for t in tasks:
        parent_id = t.get("parent_id") or t.get("parentId")
        if parent_id and parent_id in task_map:
            if parent_id not in children_map:
                children_map[parent_id] = []
            children_map[parent_id].append(t)
        else:
            roots.append(t)

    for pid in children_map:
        children_map[pid].sort(key=lambda x: (x.get("child_order") or 0, x.get("id") or ""))

    sorted_tasks = []
    seen = set()

    def traverse(task, depth):
        tid = task.get("id")
        if not tid or tid in seen:
            return
        seen.add(tid)
        task["indentation_level"] = depth
        sorted_tasks.append(task)

        if tid in children_map:
            for child in children_map[tid]:
                traverse(child, depth + 1)

    for root in roots:
        traverse(root, 0)

    for t in tasks:
        tid = t.get("id")
        if tid and tid not in seen:
            t["indentation_level"] = 0
            sorted_tasks.append(t)

    return sorted_tasks


def _render_hierarchical_markdown_list(tasks: List[Dict[str, Any]]) -> str:
    if not tasks:
        return "No tasks found."

    lines = []
    for t in tasks:
        level = t.get("indentation_level", 0)
        indent = "    " * level
        title = str(t.get("content") or t.get("name") or "").strip()
        t_id = t.get("id")

        lines.append(f"{indent}*   {title}")
        if t_id:
            lines.append(f"{indent}    Link: https://app.todoist.com/app/task/{t_id}")

    return "\n".join(lines)


def _todoist_native_call(args: Dict[str, Any]) -> Dict[str, Any]:
    action = str(args.get("action") or "list_tasks").strip().lower()
    with _http_client() as client:
        if action == "status":
            token = _env_first("TODOIST_API_TOKEN", "TODOIST_API_KEY")
            return {
                "success": True,
                "configured": bool(token),
                "token_masked": _mask(token),
                "connector": "native_api",
                "stable_primary": _todoist_connector_mode() in {"native", "native_primary", "api", "api_primary"},
                "auth_model": "personal_api_token",
            }
        if action in {"list_tasks", "search_tasks"}:
            params: Dict[str, Any] = {}
            if args.get("filter"):
                params["filter"] = args.get("filter")
            elif args.get("project_id"):
                params["project_id"] = args.get("project_id")
            elif args.get("section_id"):
                params["section_id"] = args.get("section_id")
            elif args.get("label"):
                params["label"] = args.get("label")
            tasks = _todoist_native_fetch_tasks(client, params, args.get("limit"))

            filter_str = str(args.get("filter") or "").strip().lower()
            if filter_str:
                from datetime import datetime, timedelta
                today_str = _operator_local_date()
                try:
                    today_dt = datetime.fromisoformat(today_str)
                    tomorrow_str = (today_dt + timedelta(days=1)).date().isoformat()
                except Exception:
                    tomorrow_str = ""

                filtered_tasks = []
                for t in tasks:
                    labels = [str(l).lower() for l in t.get("labels") or []]
                    excluded_labels = {
                        "exclude_workload", "reference", "hermes_hidden", "checklist_item", "duplicate",
                        "someday", "maybe", "someday_maybe", "someday-maybe", "someday/maybe"
                    }
                    if any(l in excluded_labels for l in labels):
                        continue

                    due = t.get("due")
                    if isinstance(due, dict) and due.get("date"):
                        date_part = str(due["date"]).split("T")[0]
                        is_recurring = due.get("is_recurring") is True

                        # Skip overdue recurring routines to avoid past routine carryover clutter
                        if is_recurring and date_part < today_str:
                            continue

                        if "today" in filter_str and "overdue" in filter_str:
                            if date_part <= today_str:
                                filtered_tasks.append(t)
                        elif "today" in filter_str:
                            if date_part == today_str:
                                filtered_tasks.append(t)
                        elif "overdue" in filter_str:
                            if date_part < today_str:
                                filtered_tasks.append(t)
                        elif "tomorrow" in filter_str:
                            if tomorrow_str and date_part == tomorrow_str:
                                filtered_tasks.append(t)
                        else:
                            filtered_tasks.append(t)
                    else:
                        if not any(k in filter_str for k in ["today", "overdue", "tomorrow"]):
                            filtered_tasks.append(t)
                tasks = filtered_tasks

            query = str(args.get("query") or "").strip().lower()
            match_mode = "all"
            if query:
                ranked = _rank_records(
                    query=query,
                    records=tasks,
                    field_getter=lambda task: {
                        "title": task.get("content", ""),
                        "body": task.get("description", ""),
                        "tags": task.get("labels", []),
                        "state": task.get("section_id") or task.get("project_id") or "",
                        "recency_hint": task.get("due", {}),
                    },
                )
                tasks = [{**item["record"], "_why_matched": item["why_matched"], "_score": item["score"]} for item in ranked]
                match_mode = _match_mode_for_query(query)
                top_matches = [_compact_record_match(item, "content", "description") for item in ranked[:5]]
                summary = _summarize_record_matches(query, ranked, "content")
            else:
                tasks = _enrich_and_sort_todoist_hierarchy(tasks)
                top_matches = []
                summary = f"Found {len(tasks)} Todoist task(s)."
            _append_event("todoist_read", {"action": action, "count": len(tasks), "query": query, "match_mode": match_mode, "connector": "native"})
            formatted_list = _render_hierarchical_markdown_list(tasks)
            return {"success": True, "action": action, "count": len(tasks), "match_mode": match_mode, "summary": summary, "top_matches": top_matches, "tasks": tasks, "formatted_list": formatted_list}
        if action == "add_task":
            content = str(args.get("content") or "").strip()
            if not content:
                return json.loads(_tool_error("content is required for add_task"))
            return json.loads(_create_approval(
                tool_name="personal_todoist",
                action=action,
                summary=f"add Todoist task '{content[:80]}'",
                reason="This creates a real task in your Todoist workspace.",
                benefit="Hermes can add the task for you without manual entry.",
                payload=args,
            ))
        if action in {"close_task", "reopen_task"}:
            task_id = str(args.get("task_id") or "").strip()
            if not task_id:
                return json.loads(_tool_error("task_id is required"))
            verb = "close" if action == "close_task" else "reopen"
            return json.loads(_create_approval(
                tool_name="personal_todoist",
                action=action,
                summary=f"{verb} Todoist task {task_id}",
                reason="This changes the completion state of a real Todoist task.",
                benefit="Hermes can keep your task system in sync with chat decisions.",
                payload=args,
            ))
        if action == "update_task":
            task_id = str(args.get("task_id") or "").strip()
            if not task_id:
                return json.loads(_tool_error("task_id is required for update_task"))
            return json.loads(_create_approval(
                tool_name="personal_todoist",
                action=action,
                summary=f"update Todoist task {task_id}",
                reason="This updates the due date, labels, or content of a real Todoist task.",
                benefit="Hermes can keep your tasks accurately scheduled and synchronized.",
                payload=args,
            ))
    return json.loads(_tool_error(f"Unsupported Todoist action: {action}"))


def _todoist_native_fetch_tasks(client: Any, params: Dict[str, Any], requested_limit: Any = None) -> List[Dict[str, Any]]:
    base_params = dict(params or {})
    try:
        max_total = int(requested_limit) if requested_limit is not None else 500
    except Exception:
        max_total = 500
    max_total = max(1, min(max_total, 1000))
    page_limit = min(max_total, 100)
    tasks: List[Dict[str, Any]] = []
    cursor = str(base_params.pop("cursor", "") or "").strip()
    seen_cursors = set()
    for _ in range(20):
        page_params = dict(base_params)
        page_params["limit"] = min(page_limit, max_total - len(tasks))
        if cursor:
            page_params["cursor"] = cursor
        resp = client.get(f"{TODOIST_BASE}/tasks", headers=_todoist_headers(), params=page_params)
        resp.raise_for_status()
        payload = resp.json() or {}
        if isinstance(payload, list):
            page_tasks = payload
            next_cursor = ""
        else:
            page_tasks = payload.get("results") or payload.get("tasks") or []
            next_cursor = (
                payload.get("next_cursor")
                or payload.get("nextCursor")
                or ((payload.get("pagination") or {}).get("next_cursor"))
                or ((payload.get("pagination") or {}).get("nextCursor"))
                or ""
            )
        # Filter out reference, hidden, and checklist tasks from the active listings
        page_tasks_filtered = []
        for t in page_tasks:
            lbls = [str(l).lower() for l in t.get("labels") or []]
            if any(l in {"exclude_workload", "reference", "hermes_hidden", "checklist_item", "duplicate"} for l in lbls):
                continue
            page_tasks_filtered.append(t)
        tasks.extend(page_tasks_filtered)
        if len(tasks) >= max_total:
            break
        cursor = str(next_cursor or "").strip()
        if not cursor or cursor in seen_cursors:
            break
        seen_cursors.add(cursor)
    return tasks[:max_total]


def _todoist_connector_mode() -> str:
    raw = (os.getenv("TODOIST_CONNECTOR_MODE") or _env("TODOIST_CONNECTOR_MODE") or "native_primary").strip().lower()
    aliases = {
        "native": "native_primary",
        "api": "native_primary",
        "api_primary": "native_primary",
        "token": "native_primary",
        "token_primary": "native_primary",
        "mcp": "mcp_primary",
    }
    return aliases.get(raw, raw or "native_primary")


def _todoist_native_intelligence(args: Dict[str, Any], *, primary_error: Optional[str] = None) -> Dict[str, Any]:
    limit = max(1, min(int(args.get("limit") or 10), 50))
    filter_query = str(args.get("filter") or "today | overdue").strip()
    project_id = str(args.get("project_id") or args.get("projectId") or "").strip()
    list_args = {"action": "list_tasks", "filter": filter_query, "limit": limit}
    if project_id:
        list_args["project_id"] = project_id
    native = _todoist_native_call(list_args)
    tasks = list(native.get("tasks") or [])[:limit]
    summary = _todoist_intelligence_summary(tasks=tasks, completed=[], updated=[], project_health=None).replace(
        "Todoist MCP intelligence",
        "Todoist API-token intelligence",
    )
    if primary_error:
        summary = f"Todoist hosted MCP unavailable; stable API-token path is serving tasks. {summary}"
    return {
        "success": True,
        "action": "intelligence",
        "connector": "native_api",
        "auth_model": "personal_api_token",
        "fallback_used": bool(primary_error),
        "primary_error": primary_error,
        "filter": filter_query,
        "project_id": project_id or None,
        "summary": summary,
        "active_tasks": {
            "count": len(tasks),
            "tasks": tasks,
            "raw": native,
        },
        "activity": {
            "completed_count": 0,
            "updated_count": 0,
            "completed": [],
            "updated": [],
            "raw_completed": {"success": False, "reason": "native_api_path_does_not_query_activity"},
            "raw_updated": {"success": False, "reason": "native_api_path_does_not_query_activity"},
        },
        "productivity": {"success": False, "reason": "native_api_path_does_not_query_productivity"},
        "overview": {"success": False, "reason": "native_api_path_does_not_query_overview"},
        "project_health": None,
        "recommendations": [
            f"Pick one visible task and finish it first: {_todoist_task_title(tasks[0]) or tasks[0].get('id')}."
        ] if tasks else [],
        "errors": {"mcp": primary_error} if primary_error else {},
    }


def _todoist_mcp_tool_candidates(action: str) -> List[str]:
    names = {
        "list_tasks": ["mcp_todoist_find_tasks", "mcp_todoist_find_tasks_by_date", "mcp_todoist_get_tasks", "mcp_todoist_list_tasks", "mcp_todoist_search_tasks", "mcp_todoist_tasks"],
        "search_tasks": ["mcp_todoist_find_tasks", "mcp_todoist_search_tasks", "mcp_todoist_get_tasks", "mcp_todoist_list_tasks", "mcp_todoist_tasks"],
        "add_task": ["mcp_todoist_add_tasks", "mcp_todoist_create_task", "mcp_todoist_add_task"],
        "close_task": ["mcp_todoist_complete_tasks", "mcp_todoist_complete_task", "mcp_todoist_close_task"],
        "reopen_task": ["mcp_todoist_uncomplete_tasks", "mcp_todoist_reopen_task", "mcp_todoist_uncomplete_task"],
    }
    return names.get(action, [])


def _todoist_mcp_available() -> bool:
    try:
        from tools.registry import registry
    except Exception:
        return False
    try:
        has_tool = any(
            registry.get_entry(tool_name) is not None
            for action in ["list_tasks", "search_tasks", "add_task", "close_task", "reopen_task"]
            for tool_name in _todoist_mcp_tool_candidates(action)
        )
        if not has_tool:
            from tools.mcp_tool import discover_mcp_tools
            discover_mcp_tools()
    except Exception:
        pass
    for action in ["list_tasks", "search_tasks", "add_task", "close_task", "reopen_task"]:
        for tool_name in _todoist_mcp_tool_candidates(action):
            if registry.get_entry(tool_name) is not None:
                return True
    return False


def _todoist_priority_to_mcp(value: Any) -> str:
    mapping = {4: "p1", 3: "p2", 2: "p3", 1: "p4"}
    try:
        return mapping.get(int(value), "p4")
    except Exception:
        text = str(value or "").strip().lower()
        return text if text in {"p1", "p2", "p3", "p4"} else "p4"


def _todoist_mcp_payload(action: str, payload: Dict[str, Any], tool_name: str = "") -> Dict[str, Any]:
    result = {k: v for k, v in payload.items() if v not in (None, "", [])}
    if tool_name == "mcp_todoist_find_tasks_by_date":
        return {
            "startDate": "today",
            "overdueOption": "include-overdue",
            "limit": int(result.get("limit") or 50),
        }
    if action in {"list_tasks", "search_tasks"}:
        mcp_payload: Dict[str, Any] = {"limit": int(result.get("limit") or 50)}
        if result.get("filter"):
            mcp_payload["filter"] = result["filter"]
        elif result.get("query"):
            mcp_payload["searchText"] = result["query"]
        else:
            mcp_payload["filter"] = "today | overdue"
        return mcp_payload
    if action == "add_task":
        task: Dict[str, Any] = {"content": result.get("content") or result.get("task") or result.get("title")}
        if result.get("description"):
            task["description"] = result["description"]
        if result.get("due_string") or result.get("dueString") or result.get("due"):
            task["dueString"] = result.get("due_string") or result.get("dueString") or result.get("due")
        if result.get("priority"):
            task["priority"] = _todoist_priority_to_mcp(result["priority"])
        if result.get("labels"):
            task["labels"] = result["labels"]
        if result.get("project_id") or result.get("projectId"):
            task["projectId"] = result.get("project_id") or result.get("projectId")
        if result.get("section_id") or result.get("sectionId"):
            task["sectionId"] = result.get("section_id") or result.get("sectionId")
        if result.get("parent_id") or result.get("parentId"):
            task["parentId"] = result.get("parent_id") or result.get("parentId")
        return {"tasks": [task]}
    if action in {"close_task", "reopen_task"}:
        task_id = result.get("task_id") or result.get("id")
        return {"ids": [task_id]} if task_id else {"ids": []}
    return result


def _todoist_mcp_call(action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from tools.registry import registry
    except Exception as exc:
        raise RuntimeError(f"MCP registry unavailable: {exc}") from exc
    try:
        if not any(registry.get_entry(tool_name) is not None for tool_name in _todoist_mcp_tool_candidates(action)):
            from tools.mcp_tool import discover_mcp_tools
            discover_mcp_tools()
    except Exception:
        pass
    last_error: Optional[str] = None
    for tool_name in _todoist_mcp_tool_candidates(action):
        if registry.get_entry(tool_name) is None:
            continue
        raw = registry.dispatch(tool_name, _todoist_mcp_payload(action, payload, tool_name))
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = {"raw_result": raw}
        if isinstance(parsed, dict) and parsed.get("error"):
            last_error = str(parsed.get("error"))
            continue
        if not isinstance(parsed, dict):
            parsed = {"result": parsed}
        structured = parsed.get("structuredContent")
        if isinstance(structured, dict):
            if isinstance(structured.get("tasks"), list):
                parsed.setdefault("tasks", structured["tasks"])
                parsed.setdefault("count", len(structured["tasks"]))
            if structured.get("totalCount") is not None:
                parsed.setdefault("total_count", structured.get("totalCount"))
            if structured.get("hasMore") is not None:
                parsed.setdefault("has_more", structured.get("hasMore"))
            if structured.get("nextCursor"):
                parsed.setdefault("next_cursor", structured.get("nextCursor"))
        if parsed.get("count") is not None and not parsed.get("summary"):
            parsed["summary"] = f"Todoist MCP returned {parsed['count']} task(s)."
        parsed.setdefault("success", True)
        parsed.setdefault("action", action)
        parsed["mcp_tool"] = tool_name
        return parsed
    if last_error:
        raise RuntimeError(last_error)
    raise RuntimeError(f"No registered Todoist MCP tool found for action {action}")


def _todoist_mcp_tool_call(tool_name: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    try:
        from tools.registry import registry
    except Exception as exc:
        raise RuntimeError(f"MCP registry unavailable: {exc}") from exc
    try:
        if registry.get_entry(tool_name) is None:
            from tools.mcp_tool import discover_mcp_tools
            discover_mcp_tools()
    except Exception:
        pass
    if registry.get_entry(tool_name) is None:
        raise RuntimeError(f"No registered MCP tool found: {tool_name}")
    raw = registry.dispatch(tool_name, payload or {})
    try:
        parsed = json.loads(raw)
    except Exception:
        parsed = {"raw_result": raw}
    if not isinstance(parsed, dict):
        parsed = {"result": parsed}
    if parsed.get("error"):
        raise RuntimeError(str(parsed.get("error")))
    parsed.setdefault("success", True)
    parsed["mcp_tool"] = tool_name
    return parsed


def _todoist_extract_structured_list(result: Dict[str, Any], key: str) -> List[Dict[str, Any]]:
    value = result.get(key)
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        value = structured.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        for fallback_key in ["tasks", "projects", "activity", "events", "items"]:
            value = structured.get(fallback_key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _todoist_activity_items(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    for key in ["activity", "events", "items", "logs"]:
        items = _todoist_extract_structured_list(result, key)
        if items:
            return items
    return []


def _todoist_task_title(task: Dict[str, Any]) -> str:
    return str(task.get("content") or task.get("name") or task.get("title") or "").strip()


def _todoist_intelligence_summary(*, tasks: List[Dict[str, Any]], completed: List[Dict[str, Any]], updated: List[Dict[str, Any]], project_health: Optional[Dict[str, Any]]) -> str:
    top = [_todoist_task_title(task) for task in tasks[:3] if _todoist_task_title(task)]
    parts = [
        f"Todoist MCP intelligence: {len(tasks)} active today/overdue task(s), {len(completed)} recent completion event(s), {len(updated)} recent update event(s)."
    ]
    if top:
        parts.append("Highest-friction visible tasks: " + "; ".join(top) + ".")
    if project_health:
        health_text = ""
        structured = project_health.get("structuredContent")
        if isinstance(structured, dict):
            health_text = str(structured.get("healthStatus") or structured.get("status") or structured.get("summary") or "").strip()
        if not health_text:
            health_text = str(project_health.get("summary") or project_health.get("result") or "").strip()
        if health_text:
            parts.append(f"Project health signal: {health_text[:220]}.")
    if not completed and tasks:
        parts.append("No recent completion signal was found; prefer one concrete completion over another reminder.")
    return " ".join(parts)


def _todoist_mcp_intelligence(args: Dict[str, Any]) -> Dict[str, Any]:
    if not _todoist_mcp_available():
        raise RuntimeError("Todoist MCP is not available")
    limit = max(1, min(int(args.get("limit") or 10), 50))
    filter_query = str(args.get("filter") or "today | overdue").strip()
    project_id = str(args.get("project_id") or args.get("projectId") or "").strip()
    errors: Dict[str, str] = {}

    def safe_call(label: str, tool_name: str, payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        try:
            return _todoist_mcp_tool_call(tool_name, payload)
        except Exception as exc:
            errors[label] = str(exc)
            return {"success": False, "error": str(exc), "mcp_tool": tool_name}

    active_tasks_result = safe_call("active_tasks", "mcp_todoist_find_tasks", {"filter": filter_query, "limit": limit})
    completed_activity_result = safe_call("completed_activity", "mcp_todoist_find_activity", {"objectType": "task", "eventType": "completed", "limit": limit})
    updated_activity_result = safe_call("updated_activity", "mcp_todoist_find_activity", {"objectType": "task", "eventType": "updated", "limit": limit})
    productivity_result = safe_call("productivity_stats", "mcp_todoist_get_productivity_stats", {})
    overview_result = safe_call("overview", "mcp_todoist_get_overview", {"projectId": project_id} if project_id else {})
    project_health_result = None
    if project_id:
        project_health_result = safe_call("project_health", "mcp_todoist_get_project_health", {"projectId": project_id, "includeContext": bool(args.get("include_context"))})

    tasks = _todoist_extract_structured_list(active_tasks_result, "tasks")
    completed = _todoist_activity_items(completed_activity_result)
    updated = _todoist_activity_items(updated_activity_result)
    recommendations: List[str] = []
    if tasks:
        recommendations.append(f"Pick one visible task and finish it first: {_todoist_task_title(tasks[0]) or tasks[0].get('id')}.")
    if len(tasks) >= 8:
        recommendations.append("The active list is large; reschedule, delete, or merge at least three low-value tasks before adding new ones.")
    if not completed and tasks:
        recommendations.append("No completion activity came back from MCP; use the next nudge to drive a finish, not another planning pass.")
    if updated and not completed:
        recommendations.append("There is update activity without completion activity; watch for task-shuffling disguised as progress.")
    if project_id and project_health_result and project_health_result.get("success"):
        recommendations.append("Use the project health result to choose the next unblock, not just the highest-priority task.")

    return {
        "success": True,
        "action": "intelligence",
        "connector": "mcp",
        "fallback_used": False,
        "filter": filter_query,
        "project_id": project_id or None,
        "summary": _todoist_intelligence_summary(
            tasks=tasks,
            completed=completed,
            updated=updated,
            project_health=project_health_result,
        ),
        "active_tasks": {
            "count": len(tasks),
            "tasks": tasks,
            "raw": active_tasks_result,
        },
        "activity": {
            "completed_count": len(completed),
            "updated_count": len(updated),
            "completed": completed,
            "updated": updated,
            "raw_completed": completed_activity_result,
            "raw_updated": updated_activity_result,
        },
        "productivity": productivity_result,
        "overview": overview_result,
        "project_health": project_health_result,
        "recommendations": recommendations,
        "errors": errors,
    }


def _todoist_intelligence(args: Dict[str, Any]) -> Dict[str, Any]:
    mode = _todoist_connector_mode()
    if mode == "mcp_primary":
        try:
            return _todoist_mcp_intelligence(args)
        except Exception as exc:
            if _env("TODOIST_MCP_REQUIRED").strip().lower() in {"1", "true", "yes", "on"}:
                raise
            return _todoist_native_intelligence(args, primary_error=str(exc))
    try:
        return _todoist_native_intelligence(args)
    except Exception as exc:
        # Keeps old unit tests and diagnostic shells usable when they provide a
        # mocked MCP path but no local Todoist token. In production the API
        # token path should succeed and hosted MCP should remain optional.
        try:
            mcp_result = _todoist_mcp_intelligence(args)
            mcp_result["fallback_used"] = True
            mcp_result["primary_error"] = str(exc)
            return mcp_result
        except Exception:
            raise exc


_TASK_VERBS = {
    "add", "archive", "ask", "book", "buy", "call", "cancel", "check", "choose", "clean", "close",
    "confirm", "create", "decide", "delete", "draft", "email", "finish", "find", "fix", "follow",
    "get", "make", "message", "move", "open", "order", "pay", "pick", "plan", "prepare", "publish",
    "read", "repair", "reply", "reschedule", "review", "schedule", "send", "set", "ship", "split",
    "start", "submit", "test", "update", "write",
}


def _operator_read_state() -> Dict[str, Any]:
    state = _read_json(OPERATOR_STATE_PATH, {})
    return state if isinstance(state, dict) else {}


def _operator_write_state(state: Dict[str, Any]) -> None:
    _write_json(OPERATOR_STATE_PATH, state)


def _operator_memory_default_state() -> Dict[str, Any]:
    return {
        "memories": [],
        "rules": [],
        "task_metadata": {},
        "approval_bundles": [],
    }


def _operator_memory_read_state() -> Dict[str, Any]:
    data = _read_json(OPERATOR_MEMORY_PATH, _operator_memory_default_state())
    if not isinstance(data, dict):
        return _operator_memory_default_state()
    state = _operator_memory_default_state()
    state.update(data)
    if not isinstance(state.get("memories"), list):
        state["memories"] = []
    if not isinstance(state.get("rules"), list):
        state["rules"] = []
    if not isinstance(state.get("task_metadata"), dict):
        state["task_metadata"] = {}
    if not isinstance(state.get("approval_bundles"), list):
        state["approval_bundles"] = []
    return state


def _operator_memory_write_state(state: Dict[str, Any]) -> None:
    _write_json(OPERATOR_MEMORY_PATH, state)


def _self_improve_proposals_read() -> Dict[str, Any]:
    data = _read_json(SELF_IMPROVE_PROPOSALS_PATH, {"proposals": []})
    if not isinstance(data, dict):
        return {"proposals": []}
    proposals = list(data.get("proposals") or [])
    return {"proposals": [item for item in proposals if isinstance(item, dict)]}


def _self_improve_proposals_write(data: Dict[str, Any]) -> None:
    _write_json(SELF_IMPROVE_PROPOSALS_PATH, data)


def _self_improve_pipelines_read() -> Dict[str, Any]:
    data = _read_json(SELF_IMPROVE_PIPELINES_PATH, {"pipelines": []})
    if not isinstance(data, dict):
        return {"pipelines": []}
    pipelines = list(data.get("pipelines") or [])
    return {"pipelines": [item for item in pipelines if isinstance(item, dict)]}


def _self_improve_pipelines_write(data: Dict[str, Any]) -> None:
    _write_json(SELF_IMPROVE_PIPELINES_PATH, data)


def _todoist_rules_read_state() -> Dict[str, Any]:
    data = _read_json(TODOIST_RULES_PATH, {"task_metadata": {}, "rules": []})
    if not isinstance(data, dict):
        return {"task_metadata": {}, "rules": []}
    metadata = data.get("task_metadata") if isinstance(data.get("task_metadata"), dict) else {}
    rules = list(data.get("rules") or [])
    return {"task_metadata": metadata, "rules": [item for item in rules if isinstance(item, dict)]}


def _todoist_rules_write_state(data: Dict[str, Any]) -> None:
    _write_json(TODOIST_RULES_PATH, data)


def _operator_local_date(now: Optional[datetime] = None) -> str:
    return (now or datetime.now(timezone.utc)).astimezone(_runtime_local_tz()).date().isoformat()


def _operator_parse_task_due(task: Dict[str, Any]) -> Optional[datetime]:
    due = task.get("due") if isinstance(task.get("due"), dict) else None
    value = (
        task.get("dueDate")
        or task.get("deadlineDate")
        or (due or {}).get("datetime")
        or (due or {}).get("date")
    )
    if not value:
        return None
    text = str(value)
    try:
        if len(text) == 10:
            return datetime.fromisoformat(text).replace(tzinfo=_runtime_local_tz()).astimezone(timezone.utc)
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None


def _operator_task_id(task: Dict[str, Any]) -> str:
    return str(task.get("id") or task.get("task_id") or "").strip()


def _operator_task_description(task: Dict[str, Any]) -> str:
    return str(task.get("description") or task.get("note") or "").strip()


def _operator_task_project(task: Dict[str, Any]) -> str:
    return str(task.get("project") or task.get("projectName") or task.get("projectId") or task.get("project_id") or "").strip()


def _operator_task_priority(task: Dict[str, Any]) -> int:
    value = task.get("priority")
    if isinstance(value, str) and value.lower().startswith("p"):
        try:
            return max(1, 5 - int(value[1:]))
        except Exception:
            return 1
    try:
        return int(value or 1)
    except Exception:
        return 1


def _operator_task_labels(task: Dict[str, Any]) -> List[str]:
    labels = task.get("labels") or []
    return [str(item).lower() for item in labels if str(item).strip()] if isinstance(labels, list) else []


def _operator_task_shape(task: Dict[str, Any]) -> Dict[str, Any]:
    title = _todoist_task_title(task)
    desc = _operator_task_description(task)
    lowered = title.lower().strip()
    words = [w.strip(":-_/,.()[]{}").lower() for w in title.split() if w.strip(":-_/,.()[]{}")]
    issues: List[str] = []
    repair_options: List[str] = []
    if not title:
        issues.append("empty_title")
    if not words or words[0] not in _TASK_VERBS:
        issues.append("no_clear_verb")
    if len(words) <= 2:
        issues.append("too_short_or_category_like")
    vague_terms = ["admin", "cleanup", "stuff", "things", "misc", "soon", "asap", "do as soon as possible", "todo", "follow up", "website", "social media", "taxes", "subscriptions"]
    if any(term in lowered for term in vague_terms):
        issues.append("vague_or_junk_drawer_title")
    hidden_lines = [line for line in desc.splitlines() if line.strip().startswith(("-", "*", "1.", "2.", "3."))]
    if len(hidden_lines) >= 2:
        issues.append("description_hides_subtasks")
    if any(sep in lowered for sep in [" and ", " / ", ",", "&"]):
        issues.append("possibly_multiple_actions")
    if "reference" in _operator_task_labels(task):
        issues.append("reference_material_mixed_with_tasks")
    score = max(0.05, 1.0 - (0.16 * len(issues)))
    if "do as soon as possible" in lowered or "admin" in lowered:
        repair_options.extend(["Move one named admin item forward", "Split this into the next visible action", "Delete or park it if it is not actionable today"])
    if not repair_options:
        repair_options.append("Rewrite as: verb + object + finish condition")
    return {
        "task_id": _operator_task_id(task),
        "title": title,
        "shape_score": round(score, 2),
        "issues": issues,
        "recommended_fix": repair_options[0],
        "repair_options": repair_options[:4],
    }


def _operator_update_avoidance_memory(state: Dict[str, Any], tasks: List[Dict[str, Any]], now: datetime) -> Dict[str, Any]:
    memory = dict(state.get("sticky_tasks") or {})
    today = _operator_local_date(now)
    for task in tasks:
        task_id = _operator_task_id(task)
        if not task_id:
            continue
        due = _operator_parse_task_due(task)
        is_overdue = bool(due and due.astimezone(_runtime_local_tz()).date().isoformat() < today)
        rec = dict(memory.get(task_id) or {})
        rec.setdefault("task_id", task_id)
        rec.setdefault("first_seen", now.isoformat())
        rec["last_seen"] = now.isoformat()
        rec["title"] = _todoist_task_title(task)
        rec["project"] = _operator_task_project(task)
        rec["times_seen"] = int(rec.get("times_seen") or 0) + 1
        rec["times_overdue"] = int(rec.get("times_overdue") or 0) + (1 if is_overdue else 0)
        shape = _operator_task_shape(task)
        rec["shape_score"] = shape["shape_score"]
        raw = min(1.0, (rec["times_seen"] * 0.08) + (rec["times_overdue"] * 0.16) + ((1.0 - shape["shape_score"]) * 0.35))
        rec["avoidance_score"] = round(raw, 2)
        if "description_hides_subtasks" in shape["issues"] or shape["shape_score"] < 0.55:
            rec["suspected_blocker"] = "unclear_next_action"
            rec["recommended_strategy"] = "task_repair"
        elif rec["times_overdue"] >= 2:
            rec["suspected_blocker"] = "admin_friction"
            rec["recommended_strategy"] = "direct_10_minute_action"
        else:
            rec["suspected_blocker"] = "unknown"
            rec["recommended_strategy"] = "operator_check"
        memory[task_id] = rec
    active_ids = {_operator_task_id(task) for task in tasks}
    for task_id, rec in list(memory.items()):
        if task_id not in active_ids and rec.get("completed") is not True:
            rec["last_absent"] = now.isoformat()
            rec["completed"] = True
            memory[task_id] = rec
    state["sticky_tasks"] = dict(sorted(memory.items(), key=lambda item: float((item[1] or {}).get("avoidance_score") or 0), reverse=True)[:80])
    return state


def _operator_analyze_noise(tasks: List[Dict[str, Any]], shapes: List[Dict[str, Any]], now: datetime) -> Dict[str, Any]:
    local_today = now.astimezone(_runtime_local_tz()).date()
    overdue = 0
    old_overdue = 0
    recurring = 0
    reference = 0
    high_priority = 0
    for task in tasks:
        due = _operator_parse_task_due(task)
        if due and due.astimezone(_runtime_local_tz()).date() < local_today:
            overdue += 1
            if (local_today - due.astimezone(_runtime_local_tz()).date()).days >= 3:
                old_overdue += 1
        if task.get("recurring") or (isinstance(task.get("due"), dict) and task["due"].get("is_recurring")):
            recurring += 1
        if "reference" in _operator_task_labels(task):
            reference += 1
        if _operator_task_priority(task) >= 4 or str(task.get("priority")).lower() == "p1":
            high_priority += 1
    vague = len([shape for shape in shapes if shape["shape_score"] < 0.65])
    hidden = len([shape for shape in shapes if "description_hides_subtasks" in shape["issues"]])
    score = min(1.0, (overdue * 0.07) + (old_overdue * 0.10) + (vague * 0.08) + (hidden * 0.08) + (reference * 0.04) + max(0, len(tasks) - 10) * 0.03)
    if score >= 0.75:
        status = "noisy"
    elif score >= 0.45:
        status = "getting_noisy"
    elif score >= 0.2:
        status = "moderate"
    else:
        status = "clean"
    sources: List[str] = []
    if overdue:
        sources.append("old_overdue_tasks" if old_overdue else "overdue_tasks")
    if vague:
        sources.append("vague_tasks")
    if hidden:
        sources.append("hidden_subtasks")
    if recurring >= 5:
        sources.append("recurring_task_load")
    if reference:
        sources.append("reference_tasks_in_active_view")
    return {
        "todoist_noise_score": round(score, 2),
        "status": status,
        "main_sources": sources,
        "counts": {
            "task_count": len(tasks),
            "overdue": overdue,
            "old_overdue": old_overdue,
            "recurring": recurring,
            "vague": vague,
            "hidden_subtasks": hidden,
            "reference": reference,
            "high_priority": high_priority,
        },
        "recommended_cleanup": [
            "Repair or delete stale overdue tasks",
            "Split hidden subtasks into visible actions",
            "Move reference material out of active task views",
        ][: max(1, min(3, len(sources) or 1))],
    }


def _todoist_lint_normalized_title(title: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else " " for ch in str(title or ""))
    return " ".join(cleaned.split())


def _todoist_lint_is_recurring(task: Dict[str, Any]) -> bool:
    due = task.get("due") if isinstance(task.get("due"), dict) else {}
    return bool(
        task.get("recurring")
        or task.get("isRecurring")
        or task.get("is_recurring")
        or (due or {}).get("is_recurring")
        or (due or {}).get("isRecurring")
    )


def _todoist_lint_hidden_lines(task: Dict[str, Any]) -> List[str]:
    desc = _operator_task_description(task)
    lines: List[str] = []
    for raw in desc.splitlines():
        line = raw.strip()
        if not line:
            continue
        lowered = line.lower()
        if line.startswith(("-", "*")):
            lines.append(line.lstrip("-* ").strip())
        elif len(line) > 2 and line[0].isdigit() and line[1] in {".", ")"}:
            lines.append(line[2:].strip())
        elif lowered.startswith(("next:", "todo:", "then:", "also:")):
            lines.append(line.split(":", 1)[1].strip() if ":" in line else line)
    return [line for line in lines if line]


def _todoist_lint_task_evidence(task: Dict[str, Any]) -> str:
    parts = [f"task_id={_operator_task_id(task) or 'unknown'}", f"title={_todoist_task_title(task) or 'untitled'}"]
    project = _operator_task_project(task)
    if project:
        parts.append(f"project={project}")
    due = task.get("due") if isinstance(task.get("due"), dict) else {}
    due_text = str(task.get("dueDate") or (due or {}).get("date") or "").strip()
    if due_text:
        parts.append(f"due={due_text}")
    if _todoist_lint_is_recurring(task):
        parts.append("recurring=true")
    labels = _operator_task_labels(task)
    if labels:
        parts.append(f"labels={','.join(labels[:5])}")
    return ", ".join(parts)


def _todoist_lint_repair_id(kind: str, task_ids: List[str], suggested_title: str) -> str:
    payload = {"kind": kind, "task_ids": task_ids, "suggested_title": suggested_title}
    return "repair_" + hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:12]


def _todoist_lint_make_proposal(
    *,
    kind: str,
    task_ids: List[str],
    problem: str,
    evidence: List[str],
    suggested_title: str,
    suggested_description: str,
    due_date_change: str,
    risk: str,
    approval_needed: bool = True,
) -> Dict[str, Any]:
    clean_task_ids = [str(task_id) for task_id in task_ids if str(task_id).strip()]
    proposal = {
        "kind": kind,
        "task_ids": clean_task_ids,
        "problem": problem,
        "evidence": [str(item) for item in evidence if str(item).strip()],
        "suggested_title": suggested_title,
        "suggested_description": suggested_description,
        "due_date_change": due_date_change,
        "risk": risk,
        "approval_needed": bool(approval_needed),
        "actions": ["approve", "edit", "skip", "explain"],
    }
    proposal["id"] = _todoist_lint_repair_id(kind, clean_task_ids, suggested_title)
    return proposal


def _todoist_lint_title_is_incomplete(title: str) -> bool:
    words = [word.strip(":-_/,.()[]{}").lower() for word in str(title or "").split() if word.strip(":-_/,.()[]{}")]
    if not words:
        return False
    trailing = {"within", "for", "to", "from", "about", "with", "before", "after", "by"}
    return words[-1] in trailing or str(title or "").strip().endswith(("-", "/", ":", ","))


def _todoist_lint_vague_repair_title(task: Dict[str, Any]) -> str:
    title = _todoist_task_title(task)
    lowered = title.lower()
    if "laundry" in lowered:
        return "Move laundry forward: start, switch, fold, or mark no laundry needed"
    if "tax" in lowered:
        return "Find tax amount, deadline, and next payment step"
    if "subscription" in lowered or "cost" in lowered:
        return "Choose one subscription or cost to keep, cancel, or renegotiate"
    if "family" in lowered or "handoff" in lowered:
        return "Ask what needs help and take one concrete home task"
    if "read" in lowered:
        return f"Turn '{title}' into one action or move it to reference"
    return f"Rewrite '{title or 'this task'}' as verb + object + finish condition"


def _todoist_lint_task_proposals(task: Dict[str, Any], shape: Dict[str, Any], *, duplicate_task_ids: set[str]) -> List[Dict[str, Any]]:
    proposals: List[Dict[str, Any]] = []
    task_id = _operator_task_id(task)
    title = _todoist_task_title(task)
    lowered = title.lower()
    hidden_lines = _todoist_lint_hidden_lines(task)
    labels = _operator_task_labels(task)
    evidence_base = [_todoist_lint_task_evidence(task)]

    if "do as soon as possible" in lowered or ("vague_or_junk_drawer_title" in shape.get("issues", []) and len(hidden_lines) >= 2):
        first_line = hidden_lines[0] if hidden_lines else "Choose the first concrete item"
        proposals.append(_todoist_lint_make_proposal(
            kind="junk_drawer_task",
            task_ids=[task_id],
            problem="This task is a junk drawer: it bundles multiple unrelated actions under a vague title.",
            evidence=evidence_base + [f"hidden_item={line}" for line in hidden_lines[:5]],
            suggested_title=first_line,
            suggested_description="Split each bullet into its own Todoist task with a visible finish condition. Do not keep this as one overdue catch-all item.",
            due_date_change="Replace the catch-all due date with realistic due dates on the split tasks.",
            risk="needs_user_choice",
        ))

    if len(hidden_lines) >= 3 and not any(item.get("kind") == "junk_drawer_task" for item in proposals):
        proposals.append(_todoist_lint_make_proposal(
            kind="hidden_subtask_bundle",
            task_ids=[task_id],
            problem="The description hides several subtasks, so Hermes can only nag the bundle instead of helping with the real next action.",
            evidence=evidence_base + [f"hidden_item={line}" for line in hidden_lines[:5]],
            suggested_title=hidden_lines[0],
            suggested_description="Extract the hidden lines into separate visible tasks, then keep only the next immediate action in Today.",
            due_date_change="Move only the first actionable item to Today; schedule the rest on realistic days.",
            risk="low_internal_draft",
        ))

    reference_like = "reference" in labels or ("identity statement" in lowered) or ("final program rules" in lowered)
    if reference_like:
        proposals.append(_todoist_lint_make_proposal(
            kind="reference_as_task",
            task_ids=[task_id],
            problem="This looks like reference material mixed into the active task list.",
            evidence=evidence_base + [f"shape_issues={','.join(shape.get('issues') or [])}"],
            suggested_title=f"Move '{title}' to reference review",
            suggested_description="Keep the material in notes or a low-frequency review task unless it produces one concrete next action today.",
            due_date_change="Remove from Today or schedule as a weekly/monthly review if it is still useful.",
            risk="low_internal_draft",
        ))

    if _todoist_lint_title_is_incomplete(title):
        proposals.append(_todoist_lint_make_proposal(
            kind="incomplete_title",
            task_ids=[task_id],
            problem="The title appears cut off or missing a concrete finish condition.",
            evidence=evidence_base + [f"title_ends_with={title.split()[-1] if title.split() else ''}"],
            suggested_title=_todoist_lint_vague_repair_title(task),
            suggested_description="First capture the missing amount, date, person, or finish condition. Then rewrite the task as one executable action.",
            due_date_change="Keep or set a due date only after the missing finish condition is known.",
            risk="missing_information",
        ))

    if (
        shape.get("shape_score", 1) < 0.7
        and task_id not in duplicate_task_ids
        and not any(item.get("kind") in {"junk_drawer_task", "reference_as_task", "incomplete_title"} for item in proposals)
    ):
        proposals.append(_todoist_lint_make_proposal(
            kind="vague_task",
            task_ids=[task_id],
            problem="The task is too vague or category-like for a useful nudge.",
            evidence=evidence_base + [f"shape_score={shape.get('shape_score')}", f"shape_issues={','.join(shape.get('issues') or [])}"],
            suggested_title=_todoist_lint_vague_repair_title(task),
            suggested_description="Rewrite it as a visible next action with a verb, object, and done condition.",
            due_date_change="Keep in Today only if the rewritten action can be done today.",
            risk="low_internal_draft",
        ))

    due = _operator_parse_task_due(task)
    if _todoist_lint_is_recurring(task) and due:
        local_today = datetime.now(timezone.utc).astimezone(_runtime_local_tz()).date()
        due_date = due.astimezone(_runtime_local_tz()).date()
        if due_date < local_today:
            proposals.append(_todoist_lint_make_proposal(
                kind="overdue_recurring_drift",
                task_ids=[task_id],
                problem="A recurring task is overdue, which can create a guilt loop instead of a useful routine.",
                evidence=evidence_base + [f"overdue_days={(local_today - due_date).days}"],
                suggested_title=title,
                suggested_description="Decide whether the recurrence is still useful. If yes, complete or reschedule the current instance cleanly. If not, pause or lower the frequency.",
                due_date_change="Review recurrence cadence before carrying it forward again.",
                risk="recurrence_change_requires_review",
            ))

    return proposals


def _todoist_lint_tasks(tasks: List[Dict[str, Any]], *, now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    shapes = [_operator_task_shape(task) for task in tasks]
    proposals: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()

    duplicate_task_ids: set[str] = set()
    recurring_groups: Dict[str, List[Dict[str, Any]]] = {}
    for task in tasks:
        title = _todoist_task_title(task)
        normalized = _todoist_lint_normalized_title(title)
        if normalized and _todoist_lint_is_recurring(task):
            recurring_groups.setdefault(normalized, []).append(task)
    for group in recurring_groups.values():
        if len(group) < 2:
            continue
        task_ids = [_operator_task_id(task) for task in group]
        duplicate_task_ids.update(task_id for task_id in task_ids if task_id)
        title = _todoist_task_title(group[0])
        proposal = _todoist_lint_make_proposal(
            kind="duplicate_recurring_task",
            task_ids=task_ids,
            problem="Multiple recurring tasks have the same title, so Hermes may treat duplicates as separate obligations.",
            evidence=[_todoist_lint_task_evidence(task) for task in group],
            suggested_title=title,
            suggested_description="Keep the best recurring version, merge any useful description text, and retire the duplicate after review.",
            due_date_change="Keep one recurring schedule; remove or pause the duplicate only after approval.",
            risk="needs_user_choice",
        )
        proposals.append(proposal)
        seen_ids.add(proposal["id"])

    for task, shape in zip(tasks, shapes):
        for proposal in _todoist_lint_task_proposals(task, shape, duplicate_task_ids=duplicate_task_ids):
            if proposal["id"] in seen_ids:
                continue
            seen_ids.add(proposal["id"])
            proposals.append(proposal)

    by_kind: Dict[str, int] = {}
    for proposal in proposals:
        kind = str(proposal.get("kind") or "unknown")
        by_kind[kind] = by_kind.get(kind, 0) + 1
    noise = _operator_analyze_noise(tasks, shapes, now)
    return {
        "shapes": shapes,
        "anti_noise": noise,
        "proposals": proposals,
        "counts": {
            "tasks_scanned": len(tasks),
            "proposals": len(proposals),
            "by_kind": by_kind,
            "vague_or_low_shape": len([shape for shape in shapes if float(shape.get("shape_score") or 1) < 0.7]),
            "duplicates": by_kind.get("duplicate_recurring_task", 0),
        },
    }


def _todoist_lint_report_message(report: Dict[str, Any], request_id: Optional[str] = None) -> str:
    counts = report.get("counts") if isinstance(report.get("counts"), dict) else {}
    proposals = list(report.get("proposals") or [])
    lines = [
        "Todoist repair report",
        report.get("summary") or f"Found {counts.get('proposals', len(proposals))} repair proposal(s).",
    ]
    for index, proposal in enumerate(proposals[:6], start=1):
        lines.append(f"{index}. {proposal.get('kind')}: {proposal.get('problem')}")
        lines.append(f"   Suggested: {proposal.get('suggested_title')}")
        evidence = list(proposal.get("evidence") or [])
        if evidence:
            lines.append(f"   Evidence: {evidence[0]}")
    if not proposals:
        lines.append("No repair proposals were supported by evidence right now.")
    if request_id:
        lines.extend([
            f"Request ID: {request_id}",
            f"Approve: personal_security(action='approve_request', request_id='{request_id}')",
            f"Deny: personal_security(action='deny_request', request_id='{request_id}')",
        ])
    return "\n".join(lines)


def _runtime_todoist_lint_report(args: Dict[str, Any]) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    filter_query = str(args.get("filter") or "today | overdue").strip()
    limit = max(1, min(int(args.get("limit") or 50), 50))
    source: Dict[str, Any] = {"connector": "mcp", "fallback_used": False, "filter": filter_query}
    try:
        intel = _todoist_intelligence({"filter": filter_query, "limit": limit, "project_id": args.get("project_id") or ""})
        tasks = list(((intel.get("active_tasks") or {}).get("tasks")) or [])
        source["connector"] = str(intel.get("connector") or "mcp")
        source["fallback_used"] = bool(intel.get("fallback_used"))
    except Exception as exc:
        native = _todoist_native_call({"action": "list_tasks", "filter": filter_query})
        tasks = list(native.get("tasks") or [])
        source = {"connector": "native", "fallback_used": True, "filter": filter_query, "primary_error": str(exc)}

    lint = _todoist_lint_tasks(tasks, now=now)
    proposals = list(lint.get("proposals") or [])
    report = {
        "success": True,
        "action": "todoist_lint_report",
        "generated_at": now.isoformat(),
        "summary": (
            f"Todoist repair report found {len(proposals)} proposal(s) across "
            f"{len(tasks)} active task(s)."
        ),
        "source": source,
        "counts": lint["counts"],
        "proposals": proposals,
        "task_shapes": lint["shapes"][:limit],
        "anti_noise": lint["anti_noise"],
        "approval_policy": "This report is draft-only. Todoist edits, deletes, duplicate retirement, recurrence changes, and bulk changes require separate explicit approval.",
    }
    report["telegram_message"] = _todoist_lint_report_message(report)

    create_approval = bool(args.get("create_approval", False))
    if create_approval and proposals:
        response = json.loads(_create_approval(
            tool_name="personal_runtime",
            action="apply_todoist_repair_report",
            summary="approve Todoist repair queue draft",
            reason="Hermes found task-system issues and should record the repair queue for review without editing Todoist invisibly.",
            benefit="You get a concrete repair queue with evidence, suggested titles, risks, and one-tap choices before any task changes happen.",
            payload={"action": "todoist_repair_apply", "report": report},
        ))
        request_id = str(response.get("request_id") or "")
        report["telegram_message"] = _todoist_lint_report_message(report, request_id=request_id)
        response = {**response, "action": "todoist_lint_report", "report": report, "telegram_message": report["telegram_message"]}
    else:
        response = {**report, "approval_required": False}

    if bool(args.get("send_telegram", False)):
        now_hour = datetime.now(timezone.utc).astimezone(_runtime_local_tz()).hour
        if bool(args.get("force_send", False)) or _telegram_messages_allowed_now(now_hour):
            _focus_guard_send_telegram_message(report["telegram_message"])
            response["sent"] = True
            response["send_reason"] = "sent"
        else:
            response["sent"] = False
            response["send_reason"] = "outside_hours"
    else:
        response["sent"] = False
        response["send_reason"] = "telegram_disabled"
    _append_event("todoist_lint_report", {"proposal_count": len(proposals), "task_count": len(tasks), "connector": source.get("connector")})
    return response


def _runtime_todoist_repair_apply(payload: Dict[str, Any]) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    report = dict(payload.get("report") or {})
    record = {
        "status": "approved_draft_only",
        "approved_at": now.isoformat(),
        "applied": False,
        "reason": "Approval recorded the repair queue only; no Todoist task was edited, deleted, merged, or rescheduled.",
        "report": report,
    }
    _write_json(TODOIST_REPAIR_QUEUE_PATH, record)
    _append_event(
        "todoist_repair_queue_approved",
        {
            "proposal_count": int(((report.get("counts") or {}).get("proposals")) or len(report.get("proposals") or [])),
            "applied": False,
        },
    )
    return {
        "success": True,
        "action": "todoist_repair_apply",
        "applied": False,
        "queue_path": str(TODOIST_REPAIR_QUEUE_PATH),
        "summary": "Todoist repair queue was approved for review and saved. No Todoist edits were made.",
        "report": report,
    }


_COMMON_SENSE_BUSINESS_HOURS = {
    0: [("08:00", "20:00")],
    1: [("08:00", "20:00")],
    2: [("08:00", "20:00")],
    3: [("08:00", "20:00")],
    4: [("08:00", "20:00")],
    5: [("08:00", "20:00")],
    6: [("09:00", "15:00")],
}


def _common_sense_now() -> datetime:
    return datetime.now(timezone.utc).astimezone(_runtime_local_tz())


def _common_sense_localize(now: Optional[datetime]) -> datetime:
    current = now or _common_sense_now()
    if current.tzinfo is None:
        return current.replace(tzinfo=_runtime_local_tz())
    return current.astimezone(_runtime_local_tz())


def _common_sense_time_minutes(value: str) -> int:
    hour, minute = str(value).split(":", 1)
    return int(hour) * 60 + int(minute)


def _common_sense_task_text(task: Dict[str, Any]) -> str:
    return " ".join(
        item
        for item in [
            _todoist_task_title(task),
            _operator_task_description(task),
            " ".join(_operator_task_labels(task)),
            _operator_task_project(task),
        ]
        if item
    ).lower()


def _common_sense_task_type(task: Dict[str, Any]) -> str:
    text = _common_sense_task_text(task)
    labels = {str(label).lower() for label in _operator_task_labels(task)}
    if "do as soon as possible" in text or "as soon as possible" in text or "junk_drawer" in labels:
        return "junk_drawer"
    if "window_breakfast" in labels or "breakfast" in text or ("eggs" in text and "vegetable" in text):
        return "meal_breakfast"
    if "window_morning" in labels or "morning launch" in text or ("life os" in text and "morning" in text):
        return "morning_routine"
    if "laundry" in text:
        return "laundry_home"
    if "window_evening" in labels or "evening visible reset" in text or "visible reset" in text:
        return "evening_reset"
    if "reference" in labels or "identity statement" in text or "final program rules" in text or text.startswith("read "):
        return "reference"
    if "requires_gym" in labels or "gym" in text or "workout" in text or "lower a" in text or "upper a" in text:
        return "workout"
    business_terms = [
        "business",
        "staff",
        "va",
        "cleaner",
        "cleaners",
        "client",
        "customer",
        "vendor",
        "follow up",
        "follow-up",
        "close business loop",
    ]
    if "window_business_hours" in labels or any(term in text for term in business_terms):
        return "business_contact" if any(term in text for term in ["staff", "va", "cleaner", "client", "customer", "vendor", "follow up", "follow-up", "close business loop"]) else "business_admin"
    if any(term in text for term in ["tax", "payment", "subscription", "cost", "admin", "paperwork"]):
        return "admin"
    if "family" in text or "handoff" in text or "dad block" in text:
        return "family_transition"
    return "anytime"


def _common_sense_business_hours(now: Optional[datetime] = None) -> Dict[str, Any]:
    local_now = _common_sense_localize(now)
    current_minutes = local_now.hour * 60 + local_now.minute
    windows = _COMMON_SENSE_BUSINESS_HOURS.get(local_now.weekday(), [])
    open_now = False
    closing_soon = False
    minutes_until_close: Optional[int] = None
    minutes_since_close: Optional[int] = None
    today_window = None
    for start, end in windows:
        start_m = _common_sense_time_minutes(start)
        end_m = _common_sense_time_minutes(end)
        if start_m <= current_minutes < end_m:
            open_now = True
            minutes_until_close = end_m - current_minutes
            closing_soon = minutes_until_close <= 30
            today_window = {"start": start, "end": end}
            break
        if current_minutes >= end_m:
            minutes_since_close = current_minutes - end_m
            today_window = {"start": start, "end": end}
    next_open = None
    for offset in range(0, 8):
        candidate_day = local_now + timedelta(days=offset)
        candidate_windows = _COMMON_SENSE_BUSINESS_HOURS.get(candidate_day.weekday(), [])
        for start, _end in candidate_windows:
            start_m = _common_sense_time_minutes(start)
            if offset > 0 or current_minutes < start_m:
                hour, minute = start.split(":", 1)
                next_open = candidate_day.replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)
                break
        if next_open is not None:
            break
    return {
        "timezone": HERMES_LOCAL_TIMEZONE,
        "open_now": open_now,
        "closing_soon": closing_soon,
        "minutes_until_close": minutes_until_close,
        "minutes_since_close": None if open_now else minutes_since_close,
        "today_window": today_window,
        "next_open_local": next_open.isoformat() if next_open else None,
        "schedule": {
            "monday_saturday": "08:00-20:00",
            "sunday": "09:00-15:00",
        },
    }


def _common_sense_window_for_task(task_type: str, now: datetime) -> Dict[str, Any]:
    hour_float = now.hour + (now.minute / 60.0)
    if task_type == "family_transition":
        if 16 <= hour_float < 21.5:
            return {"status": "actionable_now", "fit": 0.8, "mode": "relational_action", "valid": True}
        if 21.5 <= hour_float < 22:
            return {"status": "repair_window", "fit": 0.35, "mode": "small_repair_or_tomorrow", "valid": False}
        if hour_float >= 22 or hour_float < 7:
            return {"status": "quiet_hours_or_sleep_likely", "fit": 0.0, "mode": "quiet_or_tomorrow", "valid": False}
        return {"status": "waiting_for_window", "fit": 0.25, "mode": "wait_for_family_transition", "valid": False}
    if task_type == "meal_breakfast":
        if 6 <= hour_float < 10.5:
            return {"status": "actionable_now", "fit": 1.0, "mode": "eat_or_log", "valid": True}
        if 10.5 <= hour_float < 12:
            return {"status": "missed_but_recoverable", "fit": 0.45, "mode": "late_log_or_recover", "valid": False}
        return {"status": "missed_window", "fit": 0.0, "mode": "log_or_recover", "valid": False}
    if task_type == "morning_routine":
        if 5 <= hour_float < 11:
            return {"status": "actionable_now", "fit": 1.0, "mode": "morning_launch", "valid": True}
        if 11 <= hour_float < 14:
            return {"status": "missed_but_recoverable", "fit": 0.45, "mode": "midday_relaunch", "valid": False}
        return {"status": "missed_window", "fit": 0.0, "mode": "tomorrow_setup", "valid": False}
    if task_type == "business_contact":
        business = _common_sense_business_hours(now)
        if business["open_now"]:
            return {"status": "window_closing" if business["closing_soon"] else "actionable_now", "fit": 0.65 if business["closing_soon"] else 1.0, "mode": "contact_or_close_loop", "valid": True}
        return {"status": "external_contact_window_closed", "fit": 0.0, "mode": "draft_or_schedule", "valid": False}
    if task_type == "workout":
        if 6 <= hour_float < 21:
            return {"status": "actionable_now", "fit": 0.85, "mode": "workout_or_minimum", "valid": True}
        if 21 <= hour_float < 22:
            return {"status": "too_late_for_full_version", "fit": 0.35, "mode": "minimum_or_reschedule", "valid": False}
        return {"status": "missed_window", "fit": 0.0, "mode": "reschedule_or_recovery", "valid": False}
    if task_type in {"laundry_home", "evening_reset"}:
        if 17 <= hour_float < 21.5:
            return {"status": "actionable_now", "fit": 0.85, "mode": "small_home_action", "valid": True}
        if 21.5 <= hour_float < 22:
            return {"status": "window_closing", "fit": 0.45, "mode": "tiny_quiet_reset_or_defer", "valid": True}
        return {"status": "waiting_for_window" if hour_float < 17 else "missed_window", "fit": 0.2 if hour_float < 17 else 0.0, "mode": "defer_or_tomorrow", "valid": False}
    if task_type == "reference":
        return {"status": "probably_irrelevant_now", "fit": 0.15, "mode": "weekly_review_or_reference", "valid": False}
    if task_type in {"admin", "business_admin", "junk_drawer"}:
        return {"status": "needs_task_repair", "fit": 0.3, "mode": "repair_missing_info", "valid": False}
    if hour_float >= 22 or hour_float < 7:
        return {"status": "quiet_hours_or_sleep_likely", "fit": 0.0, "mode": "quiet_or_tomorrow", "valid": False}
    return {"status": "actionable_now", "fit": 0.65, "mode": "execute_or_defer", "valid": True}


def _common_sense_decision_text(task_type: str, title: str, window: Dict[str, Any], business: Dict[str, Any]) -> tuple[str, List[str], str]:
    if task_type == "meal_breakfast" and not window["valid"]:
        return (
            "Breakfast window passed. I am not treating this as a do-now breakfast task. Quick log?",
            ["Ate it", "Ate something else", "Skipped", "Prep tomorrow", "Change task"],
            "execution_nudge",
        )
    if task_type == "business_contact" and not window["valid"]:
        next_open = str(business.get("next_open_local") or "the next business window")
        return (
            f"Business contact window is closed. I will treat '{title}' as draft or schedule work unless it is urgent. Next open window: {next_open}.",
            ["Handled", "Draft tomorrow", "Schedule next window", "Urgent"],
            "frictionless_question",
        )
    if task_type == "morning_routine" and window["mode"] == "tomorrow_setup":
        return (
            "Morning Launch is no longer useful as a morning routine tonight. Best recovery is tomorrow setup, not catch-up.",
            ["Set tomorrow", "Mark missed", "Done already", "Skip"],
            "frictionless_question",
        )
    if task_type == "morning_routine" and window["mode"] == "midday_relaunch":
        return (
            "Morning Launch is stale as a morning routine, but the useful part is still recoverable: open Today and start one real task for 10 minutes.",
            ["10-min relaunch", "Done already", "Missed", "Set tomorrow"],
            "execution_nudge",
        )
    if task_type == "laundry_home":
        return (
            "Laundry is still useful tonight if you're home and it is not too late or noisy. Minimum: start, switch, fold one small piece, or mark no laundry needed.",
            ["Done", "Not home", "Defer", "No laundry"],
            "execution_nudge",
        )
    if task_type == "evening_reset":
        return (
            "Evening visible reset still fits tonight. Keep it small: one visible improvement, then stop.",
            ["Done", "5-min reset", "Defer", "Too late"],
            "execution_nudge",
        )
    if task_type == "workout" and not window["valid"]:
        return (
            "It is late for the full workout. Choose a recovery version: 10-minute minimum, move to the next slot, or protect sleep.",
            ["10-min minimum", "Move to next slot", "Completed", "Recovery day"],
            "frictionless_question",
        )
    if task_type == "family_transition" and window["valid"]:
        return (
            f"'{title}' is a relationship transition, not a productivity task. Make the small present move now, then mark it done.",
            ["Done", "Small repair", "Not appropriate now", "Tomorrow"],
            "execution_nudge",
        )
    if task_type == "family_transition":
        return (
            f"'{title}' is not a do-now task during quiet hours. Preserve the purpose tomorrow or use a small repair only if you are already awake and it is appropriate.",
            ["Done already", "Set tomorrow", "Not appropriate now", "Skip"],
            "log_only",
        )
    if task_type == "reference":
        return (
            f"'{title}' looks like reference/setup material, not a task worth interrupting for right now.",
            ["Move to review", "Done already", "Skip", "Explain"],
            "log_only",
        )
    if task_type in {"admin", "business_admin", "junk_drawer"} and window["mode"] == "repair_missing_info":
        return (
            f"'{title}' is not executable yet. Repair the task first: find the missing amount, date, person, or finish condition.",
            ["Repair task", "Handled", "Skip", "Explain"],
            "repair_request",
        )
    if window["mode"] == "quiet_or_tomorrow":
        return (
            f"'{title}' is not worth interrupting for during quiet hours. Queue it for the next sensible window.",
            ["Done already", "Tomorrow", "Skip", "Explain"],
            "log_only",
        )
    return (
        f"'{title}' is actionable now. Best move: spend 10 minutes, then mark it done or defer honestly.",
        ["Done", "Start 10m", "Defer", "Blocked"],
        "execution_nudge",
    )


def _common_sense_task_decision(task: Dict[str, Any], *, now: Optional[datetime] = None) -> Dict[str, Any]:
    local_now = _common_sense_localize(now)
    title = _todoist_task_title(task) or "Untitled task"
    task_type = _common_sense_task_type(task)
    business = _common_sense_business_hours(local_now)
    window = _common_sense_window_for_task(task_type, local_now)
    text, buttons, message_type = _common_sense_decision_text(task_type, title, window, business)
    original_valid = bool(window.get("valid"))
    fit = float(window.get("fit") or 0)
    can_message = _telegram_messages_allowed_now(local_now.hour)
    not_worth = task_type == "reference"
    should_message = bool(can_message and not not_worth and (original_valid or window.get("mode") in {"draft_or_schedule", "log_or_recover", "tomorrow_setup", "minimum_or_reschedule"}))
    if task_type == "business_contact" and not original_valid:
        safe_next = "Draft the message now or schedule the follow-up for the next business window; do not push after-hours contact unless urgent."
    elif task_type == "meal_breakfast" and not original_valid:
        safe_next = "Log what happened, mark it missed, or prep tomorrow; do not treat breakfast as a do-now task at night."
    elif task_type == "morning_routine" and not original_valid:
        safe_next = "Use a relaunch if early enough, otherwise set tomorrow's first action."
    elif task_type == "laundry_home":
        safe_next = "If home, move laundry forward for 10 minutes or mark no laundry needed."
    elif task_type == "family_transition" and not original_valid:
        safe_next = "Do not turn a family transition into a late-night productivity catch-up; preserve it for tomorrow or use a tiny repair only if appropriate."
    elif task_type in {"admin", "business_admin", "junk_drawer"} and not original_valid:
        safe_next = "Repair the task into one clear next action before nudging or executing it."
    elif task_type == "reference":
        safe_next = "Keep this for weekly review unless it directly supports a current action."
    else:
        safe_next = text
    assumptions = [
        {
            "assumption": "Todoist shows the task open, but Hermes does not know whether it was completed but not marked.",
            "confidence": 0.8,
            "source": "Todoist state",
        },
        {
            "assumption": "Overdue does not automatically mean do it now; time window and social context must be checked.",
            "confidence": 0.95,
            "source": "common_sense_policy",
        },
    ]
    if task_type == "business_contact":
        assumptions.append({
            "assumption": "Business contact should normally happen during stated business hours unless urgent.",
            "confidence": 0.95,
            "source": "user_provided_business_hours",
        })
    return {
        "task_id": _operator_task_id(task),
        "task_title": title,
        "task_type": task_type,
        "current_time_local": local_now.isoformat(),
        "current_status": window.get("status"),
        "original_action_valid": original_valid,
        "window_fit_score": round(fit, 2),
        "best_mode": window.get("mode"),
        "blocked_reason": None if original_valid else str(window.get("status")),
        "safe_next_action": safe_next,
        "reasonable_transformations": [
            "do_as_written" if original_valid else "do_not_do_as_written",
            str(window.get("mode")),
            "ask_with_buttons" if should_message else "log_or_review",
        ],
        "should_message": should_message,
        "message_type": message_type,
        "telegram_text": text,
        "buttons": buttons,
        "business_hours": business if task_type == "business_contact" else {},
        "human_reality_score": round(max(0.0, min(1.0, fit + (0.15 if should_message else -0.1) - (0.3 if not_worth else 0))), 2),
        "assumption_ledger": assumptions,
        "known_unknowns": [
            "Whether the task was completed outside Todoist.",
            "Whether the user is busy, low-energy, interrupted, or handling an emergency.",
            "Whether the task still matters today.",
        ],
        "evidence_envelope": {
            "claim": f"{title} should be handled as {window.get('mode')}.",
            "confidence": round(0.55 + (fit * 0.3), 2),
            "evidence": [
                {"source": "Todoist task", "fact": f"title={title}", "strength": "high"},
                {"source": "Common Sense Kernel", "fact": f"task_type={task_type}, status={window.get('status')}", "strength": "high"},
            ],
            "uncertainties": [
                "Completion may not be synced back to Todoist.",
                "Presence and location may be unknown.",
            ],
            "safe_next_action": safe_next,
        },
    }


def _common_sense_salvage(decisions: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    buckets = {
        "expired": [],
        "closed": [],
        "still_useful": [],
        "needs_repair": [],
        "not_worth_interrupting": [],
    }
    for decision in decisions:
        title = str(decision.get("task_title") or "")
        status = str(decision.get("current_status") or "")
        mode = str(decision.get("best_mode") or "")
        task_type = str(decision.get("task_type") or "")
        if status == "external_contact_window_closed":
            buckets["closed"].append(title)
        elif task_type == "reference":
            buckets["not_worth_interrupting"].append(title)
        elif mode in {"log_or_recover", "tomorrow_setup"} or status == "missed_window":
            buckets["expired"].append(title)
        elif mode == "repair_missing_info" or status == "needs_task_repair":
            buckets["needs_repair"].append(title)
        elif bool(decision.get("original_action_valid")):
            buckets["still_useful"].append(title)
    return buckets


def _common_sense_best_decision(decisions: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not decisions:
        return None
    preferred_modes = {"small_home_action", "contact_or_close_loop", "workout_or_minimum", "execute_or_defer"}
    ranked = sorted(
        decisions,
        key=lambda item: (
            1 if item.get("best_mode") in preferred_modes else 0,
            1 if item.get("original_action_valid") else 0,
            float(item.get("human_reality_score") or 0),
            float(item.get("window_fit_score") or 0),
        ),
        reverse=True,
    )
    for decision in ranked:
        if decision.get("task_type") != "reference" and decision.get("should_message"):
            return decision
    return ranked[0]


def _common_sense_analyze_tasks(tasks: List[Dict[str, Any]], *, now: Optional[datetime] = None) -> Dict[str, Any]:
    local_now = _common_sense_localize(now)
    decisions = [_common_sense_task_decision(task, now=local_now) for task in tasks]
    best = _common_sense_best_decision(decisions)
    salvage = _common_sense_salvage(decisions)
    allowed = _telegram_messages_allowed_now(local_now.hour)
    return {
        "generated_at": local_now.isoformat(),
        "operating_state": {
            "time": {
                "local": local_now.isoformat(),
                "allowed_telegram_window": allowed,
                "quiet_hours": not allowed,
            },
            "todoist_state": {
                "today_overdue_count": len(tasks),
                "expired_count": len(salvage["expired"]),
                "closed_count": len(salvage["closed"]),
                "still_useful_count": len(salvage["still_useful"]),
                "needs_repair_count": len(salvage["needs_repair"]),
                "not_worth_interrupting_count": len(salvage["not_worth_interrupting"]),
            },
            "policy_state": {
                "can_message": allowed,
                "can_edit_todoist_without_approval": False,
                "must_explain_why_now": True,
            },
        },
        "decisions": decisions,
        "decision_by_task_id": {str(item.get("task_id")): item for item in decisions if item.get("task_id")},
        "late_day_salvage": salvage,
        "summary": {
            "should_message": bool(best and best.get("should_message") and allowed),
            "message_type": (best or {}).get("message_type") if best else "log_only",
            "best_move": {
                "task_id": (best or {}).get("task_id"),
                "task_title": (best or {}).get("task_title"),
                "mode": (best or {}).get("best_mode"),
                "safe_next_action": (best or {}).get("safe_next_action"),
                "telegram_text": (best or {}).get("telegram_text"),
                "buttons": (best or {}).get("buttons"),
            } if best else None,
        },
        "core_rule": "Do not treat overdue as do it now. First classify whether the task is actionable as written, expired, closed, stale, badly designed, or best handled by a question.",
    }


def _runtime_common_sense_decision(args: Dict[str, Any]) -> Dict[str, Any]:
    now = _common_sense_now()
    filter_query = str(args.get("filter") or "today | overdue").strip()
    limit = max(1, min(int(args.get("limit") or 50), 50))
    source: Dict[str, Any] = {"connector": "mcp", "fallback_used": False, "filter": filter_query}
    try:
        intel = _todoist_intelligence({"filter": filter_query, "limit": limit, "project_id": args.get("project_id") or ""})
        tasks = list(((intel.get("active_tasks") or {}).get("tasks")) or [])
        source["connector"] = str(intel.get("connector") or "mcp")
        source["fallback_used"] = bool(intel.get("fallback_used"))
    except Exception as exc:
        native = _todoist_native_call({"action": "list_tasks", "filter": filter_query})
        tasks = list(native.get("tasks") or [])
        source = {"connector": "native", "fallback_used": True, "filter": filter_query, "primary_error": str(exc)}
    analysis = _common_sense_analyze_tasks(tasks, now=now)
    result = {
        "success": True,
        "action": "common_sense_decision",
        "source": source,
        **analysis,
    }
    _append_event(
        "common_sense_decision",
        {
            "task_count": len(tasks),
            "best_task": ((analysis.get("summary") or {}).get("best_move") or {}).get("task_title"),
            "should_message": ((analysis.get("summary") or {}).get("should_message")),
        },
    )
    return result


def _runtime_event_log_state(args: Dict[str, Any]) -> Dict[str, Any]:
    limit = int(args.get("limit") or 200)
    events = _read_jsonl_all(EVENTS_PATH)
    recent = events[-limit:]
    by_type: Dict[str, int] = {}
    by_event_type: Dict[str, int] = {}
    for event in recent:
        event_kind = str(event.get("type") or "").strip() or "unknown"
        by_type[event_kind] = by_type.get(event_kind, 0) + 1
        nested_kind = str(event.get("event_type") or "").strip()
        if nested_kind:
            by_event_type[nested_kind] = by_event_type.get(nested_kind, 0) + 1
    operator_state = _operator_read_state()
    memory_state = _operator_memory_read_state()
    last_feedback = None
    for rec in reversed(list(operator_state.get("nudge_records") or [])):
        if rec.get("user_action"):
            last_feedback = {
                "task_id": rec.get("task_id"),
                "task_title": rec.get("task_title"),
                "feedback": rec.get("user_action"),
                "feedback_at": rec.get("feedback_at"),
            }
            break
    return {
        "success": True,
        "action": "event_log_state",
        "event_log": {
            "event_count": len(events),
            "recent_count": len(recent),
            "by_type": by_type,
            "by_event_type": by_event_type,
            "recent_events": recent[-20:],
        },
        "snapshot": {
            "last_feedback": last_feedback,
            "memory_count": len(list(operator_state.get("operator_memories") or [])) + len(list(memory_state.get("memories") or [])),
            "rule_count": len(list(memory_state.get("rules") or [])),
            "task_metadata_count": len(dict(memory_state.get("task_metadata") or {})),
            "pending_nudges": len([rec for rec in list(operator_state.get("nudge_records") or []) if rec.get("outcome") == "pending"]),
        },
    }


def _runtime_memory_console(args: Dict[str, Any]) -> Dict[str, Any]:
    mode = str(args.get("mode") or "list").strip().lower()
    state = _operator_memory_read_state()
    memories = list(state.get("memories") or [])
    if mode == "list":
        include_expired = bool(args.get("include_expired"))
        visible = memories if include_expired else [item for item in memories if not item.get("expired_at")]
        return {"success": True, "action": "memory_console", "mode": mode, "memory_count": len(visible), "memories": visible}
    if mode == "upsert":
        memory = dict(args.get("memory") or {})
        content = str(memory.get("content") or "").strip()
        if not content:
            raise ValueError("memory.content is required")
        now_iso = datetime.now(timezone.utc).isoformat()
        memory_id = str(memory.get("memory_id") or f"mem_{uuid.uuid4().hex[:10]}")
        entry = {
            "memory_id": memory_id,
            "content": content,
            "type": str(memory.get("type") or "note").strip(),
            "source": str(memory.get("source") or "runtime").strip(),
            "confidence": float(memory.get("confidence") or 0.7),
            "created_at": str(memory.get("created_at") or now_iso),
            "last_confirmed_at": str(memory.get("last_confirmed_at") or now_iso),
        }
        replaced = False
        for idx, existing in enumerate(memories):
            if str(existing.get("memory_id") or "") == memory_id:
                memories[idx] = {**existing, **entry}
                replaced = True
                break
        if not replaced:
            memories.append(entry)
        state["memories"] = memories[-200:]
        _operator_memory_write_state(state)
        return {"success": True, "action": "memory_console", "mode": mode, "memory": entry}
    if mode == "correct":
        memory_id = str(args.get("memory_id") or "").strip()
        content = str(args.get("content") or "").strip()
        if not memory_id or not content:
            raise ValueError("memory_id and content are required")
        now_iso = datetime.now(timezone.utc).isoformat()
        updated = None
        for idx, existing in enumerate(memories):
            if str(existing.get("memory_id") or "") != memory_id:
                continue
            updated = {
                **existing,
                "previous_content": existing.get("content"),
                "content": content,
                "confidence": float(args.get("confidence") if args.get("confidence") is not None else existing.get("confidence") or 0.7),
                "corrected_at": now_iso,
                "last_confirmed_at": now_iso,
            }
            memories[idx] = updated
            break
        if updated is None:
            raise ValueError("memory_id was not found")
        state["memories"] = memories[-200:]
        _operator_memory_write_state(state)
        return {"success": True, "action": "memory_console", "mode": mode, "memory": updated}
    if mode == "expire":
        memory_id = str(args.get("memory_id") or "").strip()
        if not memory_id:
            raise ValueError("memory_id is required")
        now_iso = datetime.now(timezone.utc).isoformat()
        updated = None
        for idx, existing in enumerate(memories):
            if str(existing.get("memory_id") or "") != memory_id:
                continue
            updated = {**existing, "expired_at": now_iso}
            memories[idx] = updated
            break
        if updated is None:
            raise ValueError("memory_id was not found")
        state["memories"] = memories[-200:]
        _operator_memory_write_state(state)
        return {"success": True, "action": "memory_console", "mode": mode, "memory": updated}
    if mode == "delete":
        memory_id = str(args.get("memory_id") or "").strip()
        if not memory_id:
            raise ValueError("memory_id is required")
        before = len(memories)
        state["memories"] = [item for item in memories if str(item.get("memory_id") or "") != memory_id]
        _operator_memory_write_state(state)
        return {"success": True, "action": "memory_console", "mode": mode, "deleted": len(state["memories"]) < before, "memory_id": memory_id}
    raise ValueError(f"Unsupported memory_console mode: {mode}")


def _runtime_todoist_rule_store(args: Dict[str, Any]) -> Dict[str, Any]:
    mode = str(args.get("mode") or "status").strip().lower()
    state = _todoist_rules_read_state()
    if mode == "status":
        return {
            "success": True,
            "action": "todoist_rule_store",
            "mode": mode,
            "task_metadata_count": len(dict(state.get("task_metadata") or {})),
            "rule_count": len(list(state.get("rules") or [])),
            "task_metadata": state.get("task_metadata") or {},
            "rules": state.get("rules") or [],
        }
    if mode == "upsert_task_metadata":
        task_key = str(args.get("task_key") or "").strip()
        metadata = dict(args.get("metadata") or {})
        if not task_key:
            raise ValueError("task_key is required")
        state["task_metadata"][task_key] = {
            **dict(state.get("task_metadata") or {}).get(task_key, {}),
            **metadata,
            "task_key": task_key,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        _todoist_rules_write_state(state)
        return {"success": True, "action": "todoist_rule_store", "mode": mode, "task_key": task_key, "metadata": state["task_metadata"][task_key]}
    if mode == "upsert_rule":
        rule = dict(args.get("rule") or {})
        rule_id = str(rule.get("rule_id") or f"rule_{uuid.uuid4().hex[:10]}")
        entry = {**rule, "rule_id": rule_id, "updated_at": datetime.now(timezone.utc).isoformat()}
        rules = list(state.get("rules") or [])
        replaced = False
        for idx, existing in enumerate(rules):
            if str(existing.get("rule_id") or "") == rule_id:
                rules[idx] = {**existing, **entry}
                replaced = True
                break
        if not replaced:
            rules.append(entry)
        state["rules"] = rules[-200:]
        _todoist_rules_write_state(state)
        return {"success": True, "action": "todoist_rule_store", "mode": mode, "rule": entry}
    if mode == "classify_tasks":
        tasks = list(args.get("tasks") or [])
        if not tasks:
            intel = _todoist_intelligence({"filter": args.get("filter") or "today | overdue", "limit": int(args.get("limit") or 25)})
            tasks = list((((intel.get("active_tasks") or {}).get("tasks")) or []))
        classified: List[Dict[str, Any]] = []
        for task in tasks:
            decision = _common_sense_task_decision(task, now=_common_sense_now())
            task_key = str(task.get("task_key") or _operator_task_id(task) or _todoist_task_title(task).lower().strip())
            metadata = {
                **dict(state.get("task_metadata") or {}).get(task_key, {}),
                "task_key": task_key,
                "task_id": decision.get("task_id"),
                "task_title": decision.get("task_title"),
                "task_type": decision.get("task_type"),
                "rollover_policy": "carry_until_done" if bool(decision.get("original_action_valid")) else "skip_if_missed",
                "after_window_behavior": decision.get("best_mode"),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            state["task_metadata"][task_key] = metadata
            classified.append(metadata)
        _todoist_rules_write_state(state)
        return {"success": True, "action": "todoist_rule_store", "mode": mode, "classified_count": len(classified), "classified": classified}
    raise ValueError(f"Unsupported todoist_rule_store mode: {mode}")


def _rollover_recommended_state(decision: Dict[str, Any], metadata: Dict[str, Any]) -> str:
    policy = str(metadata.get("rollover_policy") or "").strip().lower()
    mode = str(decision.get("best_mode") or "").strip().lower()
    if policy == "skip_if_missed" and mode in {"log_or_recover", "late_log_or_recover", "tomorrow_setup"}:
        return "log_or_skip"
    if mode == "draft_or_schedule":
        return "schedule_next_window"
    if mode == "repair_missing_info":
        return "repair_before_rollover"
    if mode in {"quiet_or_tomorrow", "defer_or_tomorrow"}:
        return "defer_cleanly"
    return "carry_or_complete"


def _runtime_rollover_preview(args: Dict[str, Any]) -> Dict[str, Any]:
    tasks = list(args.get("tasks") or [])
    if not tasks:
        intel = _todoist_intelligence({"filter": args.get("filter") or "today | overdue", "limit": int(args.get("limit") or 20)})
        tasks = list((((intel.get("active_tasks") or {}).get("tasks")) or []))
    rules = _todoist_rules_read_state()
    metadata_map = dict(rules.get("task_metadata") or {})
    decisions: List[Dict[str, Any]] = []
    for task in tasks:
        decision = _common_sense_task_decision(task, now=_common_sense_now())
        task_key = str(task.get("task_key") or _operator_task_id(task) or _todoist_task_title(task).lower().strip())
        metadata = dict(metadata_map.get(task_key) or {})
        decisions.append({
            "task_id": decision.get("task_id"),
            "task_title": decision.get("task_title"),
            "task_key": task_key,
            "task_type": metadata.get("task_type") or decision.get("task_type"),
            "rollover_policy": metadata.get("rollover_policy") or ("carry_until_done" if decision.get("original_action_valid") else "skip_if_missed"),
            "after_window_behavior": metadata.get("after_window_behavior") or decision.get("best_mode"),
            "original_action_valid": decision.get("original_action_valid"),
            "recommended_state": _rollover_recommended_state(decision, metadata),
            "safe_next_action": decision.get("safe_next_action"),
        })
    carry_forward_count = len([item for item in decisions if item.get("recommended_state") in {"carry_or_complete", "schedule_next_window", "defer_cleanly"}])
    skip_or_log_count = len([item for item in decisions if item.get("recommended_state") == "log_or_skip"])
    repair_count = len([item for item in decisions if item.get("recommended_state") == "repair_before_rollover"])
    simulation = {
        "before": {
            "task_count": len(decisions),
            "stale_count": len([item for item in decisions if not item.get("original_action_valid")]),
        },
        "after": {
            "carry_forward_count": carry_forward_count,
            "skip_or_log_count": skip_or_log_count,
            "repair_count": repair_count,
        },
        "delta": {
            "today_cleanup_reduction": skip_or_log_count + repair_count,
        },
    }
    return {"success": True, "action": "rollover_preview", "decision_count": len(decisions), "decisions": decisions, "simulation": simulation}


def _runtime_approval_bundle(args: Dict[str, Any]) -> Dict[str, Any]:
    mode = str(args.get("mode") or "list").strip().lower()
    state = _operator_memory_read_state()
    bundles = list(state.get("approval_bundles") or [])
    if mode == "list":
        return {"success": True, "action": "approval_bundle", "mode": mode, "bundle_count": len(bundles), "bundles": bundles}
    if mode == "simulate":
        return {"success": True, "action": "approval_bundle", "mode": mode, "simulation": dict(args.get("simulation") or {})}
    if mode == "create":
        bundle = {
            "bundle_id": f"bundle_{uuid.uuid4().hex[:10]}",
            "bundle_type": str(args.get("bundle_type") or "generic").strip(),
            "summary": str(args.get("summary") or "Approval bundle").strip(),
            "items": list(args.get("items") or []),
            "simulation": dict(args.get("simulation") or {}),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        bundles.append(bundle)
        state["approval_bundles"] = bundles[-100:]
        _operator_memory_write_state(state)
        response = json.loads(_create_approval(
            tool_name="personal_runtime",
            action="approval_bundle_apply",
            summary=bundle["summary"],
            reason="Bundle contains grouped Hermes maintenance or Todoist changes that should be reviewed before execution.",
            benefit="Lets Hermes batch related low-risk fixes with a before/after simulation instead of one-off noisy approvals.",
            payload={"action": "approval_bundle_apply", "bundle": bundle},
        ))
        response["simulation"] = bundle["simulation"]
        return response
    raise ValueError(f"Unsupported approval_bundle mode: {mode}")


def _apply_safe_bundle_item(item: Dict[str, Any]) -> Dict[str, Any]:
    kind = str(item.get("kind") or "").strip().lower()
    if kind == "memory_correct":
        return _runtime_memory_console({
            "mode": "correct",
            "memory_id": item.get("memory_id"),
            "content": item.get("content"),
            "confidence": item.get("confidence"),
        })
    if kind == "memory_expire":
        return _runtime_memory_console({
            "mode": "expire",
            "memory_id": item.get("memory_id"),
        })
    if kind == "task_metadata_upsert":
        return _runtime_todoist_rule_store({
            "mode": "upsert_task_metadata",
            "task_key": item.get("task_key"),
            "metadata": dict(item.get("metadata") or {}),
        })
    return {"success": False, "skipped": True, "kind": kind, "reason": "unsupported_safe_bundle_item"}


def _runtime_approval_bundle_apply(payload: Dict[str, Any]) -> Dict[str, Any]:
    bundle = dict(payload.get("bundle") or {})
    items = list(bundle.get("items") or [])
    applied = 0
    skipped = 0
    results: List[Dict[str, Any]] = []
    for item in items:
        result = _apply_safe_bundle_item(dict(item))
        results.append(result)
        if result.get("success"):
            applied += 1
        else:
            skipped += 1
    memory_state = _operator_memory_read_state()
    bundles = list(memory_state.get("approval_bundles") or [])
    updated_bundle = {**bundle, "executed_at": datetime.now(timezone.utc).isoformat(), "applied_count": applied, "skipped_count": skipped}
    for idx, existing in enumerate(bundles):
        if str(existing.get("bundle_id") or "") == str(bundle.get("bundle_id") or ""):
            bundles[idx] = updated_bundle
            break
    memory_state["approval_bundles"] = bundles[-100:]
    _operator_memory_write_state(memory_state)
    return {
        "success": True,
        "action": "approval_bundle_apply",
        "bundle_id": bundle.get("bundle_id"),
        "applied_count": applied,
        "skipped_count": skipped,
        "results": results,
        "summary": {
            "bundle_type": bundle.get("bundle_type"),
            "applied_count": applied,
            "skipped_count": skipped,
            "simulation": dict(bundle.get("simulation") or {}),
        },
        "simulation": dict(bundle.get("simulation") or {}),
    }


def _derive_bad_nudge_proposal(target: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    title = str(target.get("task_title") or "").strip()
    message = str(target.get("message") or "").strip()
    lowered = f"{title} {message}".lower()
    if not lowered:
        return None
    if "breakfast" in lowered:
        return {
            "kind": "bad_nudge_rule",
            "domain": "meal_breakfast",
            "rule_summary": "Breakfast tasks should not be nudged as original breakfast actions after late morning; convert them to log/recovery/prep flows.",
            "rule_patch": {
                "task_type": "meal_breakfast",
                "after_expiry_behavior": "log_or_recover",
                "disallow_original_after": "12:00",
            },
            "eval_case": {
                "name": "breakfast_after_hours_bad_nudge",
                "input": {"task": title or "Breakfast task", "current_time": "19:00"},
                "expected_behavior": "Do not suggest eating breakfast now; offer log, skipped, or prep tomorrow.",
            },
        }
    return {
        "kind": "bad_nudge_rule",
        "domain": "general",
        "rule_summary": f"Reduce similar nudges for '{title or 'unknown task'}' in matching timing/context and prefer repair, question, or silence.",
        "rule_patch": {
            "task_title": title,
            "feedback": "bad_nudge",
            "preferred_fallback": "repair_or_silence",
        },
        "eval_case": {
            "name": "generic_bad_nudge_regression",
            "input": {"task": title or "Unknown task"},
            "expected_behavior": "Do not repeat the same nudge style immediately after bad_nudge feedback.",
        },
    }


def _record_bad_nudge_self_improvement(target: Dict[str, Any], *, now: datetime) -> Optional[Dict[str, Any]]:
    proposal = _derive_bad_nudge_proposal(target)
    if not proposal:
        return None
    state = _self_improve_proposals_read()
    proposals = list(state.get("proposals") or [])
    entry = {
        "proposal_id": f"proposal_{uuid.uuid4().hex[:10]}",
        "created_at": now.isoformat(),
        "source": "telegram_feedback_bad_nudge",
        "task_id": target.get("task_id"),
        "task_title": target.get("task_title"),
        **proposal,
    }
    proposals.append(entry)
    state["proposals"] = proposals[-120:]
    _self_improve_proposals_write(state)
    return entry


def _runtime_self_improve_proposals(args: Dict[str, Any]) -> Dict[str, Any]:
    mode = str(args.get("mode") or "list").strip().lower()
    state = _self_improve_proposals_read()
    proposals = list(state.get("proposals") or [])
    if mode == "list":
        return {"success": True, "action": "self_improve_proposals", "mode": mode, "proposal_count": len(proposals), "proposals": proposals}
    raise ValueError(f"Unsupported self_improve_proposals mode: {mode}")


def _runtime_trace_status(args: Dict[str, Any]) -> Dict[str, Any]:
    del args
    traces = _read_jsonl_recent(TRACE_LOG_PATH, limit=50)
    base_url = _env_first("HERMES_LANGFUSE_BASE_URL", "LANGFUSE_BASE_URL") or "https://cloud.langfuse.com"
    public_key = _env_first("HERMES_LANGFUSE_PUBLIC_KEY", "LANGFUSE_PUBLIC_KEY")
    secret_key = _env_first("HERMES_LANGFUSE_SECRET_KEY", "LANGFUSE_SECRET_KEY")
    return {
        "success": True,
        "action": "trace_status",
        "trace_count": len(traces),
        "recent_traces": traces[-10:],
        "langfuse": {
            "configured": bool(public_key and secret_key),
            "base_url": base_url,
            "public_key_masked": _mask(public_key),
            "secret_key_masked": _mask(secret_key),
        },
    }


def _build_trace_entry(
    *,
    trace_type: str,
    status: str,
    data: Optional[Dict[str, Any]] = None,
    trace_family: str = "",
    span_name: str = "",
    tags: Optional[List[str]] = None,
) -> Dict[str, Any]:
    base_url = _env_first("HERMES_LANGFUSE_BASE_URL", "LANGFUSE_BASE_URL") or "https://cloud.langfuse.com"
    public_key = _env_first("HERMES_LANGFUSE_PUBLIC_KEY", "LANGFUSE_PUBLIC_KEY")
    secret_key = _env_first("HERMES_LANGFUSE_SECRET_KEY", "LANGFUSE_SECRET_KEY")
    return {
        "trace_id": f"trace_{uuid.uuid4().hex[:12]}",
        "ts": datetime.now(timezone.utc).isoformat(),
        "trace_type": trace_type,
        "trace_family": trace_family or ("operator" if "operator" in trace_type else "runtime"),
        "span_name": span_name or trace_type,
        "status": status,
        "tags": [str(tag).strip() for tag in list(tags or []) if str(tag).strip()],
        "data": dict(data or {}),
        "langfuse": {
            "configured": bool(public_key and secret_key),
            "base_url": base_url,
        },
    }


def _runtime_trace_event(args: Dict[str, Any]) -> Dict[str, Any]:
    trace_type = str(args.get("trace_type") or "").strip().lower()
    if not trace_type:
        raise ValueError("trace_type is required")
    entry = _build_trace_entry(
        trace_type=trace_type,
        status=str(args.get("status") or "success").strip().lower(),
        data=dict(args.get("data") or {}),
        trace_family=str(args.get("trace_family") or "").strip().lower(),
        span_name=str(args.get("span_name") or "").strip(),
        tags=list(args.get("tags") or []),
    )
    _append_jsonl(TRACE_LOG_PATH, entry)
    return {"success": True, "action": "trace_event", "trace": entry}


def _runtime_eval_suite_export(args: Dict[str, Any]) -> Dict[str, Any]:
    del args
    proposals = list((_self_improve_proposals_read().get("proposals") or []))
    tests: List[Dict[str, Any]] = []
    for proposal in proposals:
        eval_case = dict(proposal.get("eval_case") or {})
        if not eval_case:
            continue
        tests.append(
            {
                "description": str(eval_case.get("name") or proposal.get("proposal_id") or "unnamed_eval"),
                "vars": dict(eval_case.get("input") or {}),
                "assert": [{"type": "contains", "value": str(eval_case.get("expected_behavior") or "").strip()}],
                "metadata": {
                    "proposal_id": proposal.get("proposal_id"),
                    "kind": proposal.get("kind"),
                    "task_title": proposal.get("task_title"),
                },
            }
        )
    traces = _read_jsonl_recent(TRACE_LOG_PATH, limit=100)
    for trace in traces:
        if str(trace.get("status") or "").strip().lower() != "failure":
            continue
        data = dict(trace.get("data") or {})
        expected = str(data.get("expected_behavior") or "").strip()
        if not expected:
            continue
        tests.append(
            {
                "description": f"trace_failure_{trace.get('trace_id')}",
                "vars": {
                    "task": str(data.get("task_title") or ""),
                    "task_type": str(data.get("task_type") or ""),
                    "current_time": str(data.get("current_time") or ""),
                },
                "assert": [{"type": "contains", "value": expected}],
                "metadata": {
                    "source": "trace_failure",
                    "trace_id": trace.get("trace_id"),
                    "trace_type": trace.get("trace_type"),
                },
            }
        )
    payload = {"tests": tests}
    _write_json(PROMPTFOO_EVALS_PATH, payload)
    config = {
        "description": "Hermes promptfoo export",
        "tests_file": str(PROMPTFOO_EVALS_PATH),
        "default_assert_type": "contains",
    }
    _write_json(PROMPTFOO_CONFIG_PATH, config)
    return {
        "success": True,
        "action": "eval_suite_export",
        "case_count": len(tests),
        "path": str(PROMPTFOO_EVALS_PATH),
        "config_path": str(PROMPTFOO_CONFIG_PATH),
        "command_hint": f"promptfoo eval -c {PROMPTFOO_CONFIG_PATH}",
    }


def _normalized_event_family(event: Dict[str, Any]) -> str:
    event_type = str(event.get("event_type") or "").strip().lower()
    raw_type = str(event.get("type") or "").strip().lower()
    if event_type in {"wake", "desktop_unlocked", "leaving_house", "outing_request", "voice_memo_received", "activitywatch_heartbeat"}:
        return "presence"
    if event_type == "telegram_feedback":
        return "telegram"
    if raw_type.startswith("approval_"):
        return "approval"
    if raw_type.startswith("self_improve_"):
        return "self_improve"
    if raw_type in {"common_sense_decision", "todoist_lint_report", "live_watch_run"}:
        return "operator"
    if raw_type.startswith("trace_"):
        return "trace"
    if raw_type.startswith("todoist_"):
        return "todoist"
    if raw_type.startswith("runtime_event_ingested"):
        return "system"
    return "system"


def _normalized_events(limit: int = 200) -> Dict[str, Any]:
    events = _read_jsonl_all(EVENTS_PATH)
    recent = events[-limit:]
    normalized: List[Dict[str, Any]] = []
    family_counts: Dict[str, int] = {}
    for event in recent:
        family = _normalized_event_family(event)
        family_counts[family] = family_counts.get(family, 0) + 1
        normalized.append(
            {
                "ts": event.get("ts"),
                "family": family,
                "type": event.get("type"),
                "event_type": event.get("event_type"),
                "source": event.get("source"),
            }
        )
    return {"events": normalized, "family_counts": family_counts, "count": len(normalized)}


def _common_sense_rule_registry() -> Dict[str, Any]:
    domains = {
        "meal_breakfast": {"window": "06:00-10:30", "expiry": "late_morning", "recovery": "log_or_recover"},
        "morning_routine": {"window": "05:00-11:00", "expiry": "afternoon", "recovery": "midday_relaunch_or_tomorrow_setup"},
        "business_contact": {"window": "business_hours", "expiry": "business_close", "recovery": "draft_or_schedule"},
        "family_transition": {"window": "late_afternoon_evening", "expiry": "night", "recovery": "small_repair_or_tomorrow"},
        "workout": {"window": "day_evening", "expiry": "late_evening", "recovery": "minimum_or_reschedule"},
        "laundry_home": {"window": "evening_home", "expiry": "late_night", "recovery": "defer_or_small_action"},
        "evening_reset": {"window": "evening", "expiry": "quiet_hours", "recovery": "tiny_reset_or_tomorrow"},
        "reference": {"window": "review_only", "expiry": "always_low_priority", "recovery": "weekly_review"},
        "admin": {"window": "anytime_with_context", "expiry": "when_missing_info", "recovery": "repair_missing_info"},
    }
    return {"domains": domains}


def _snapshot_presence_state(now: Optional[datetime] = None) -> Dict[str, Any]:
    presence = _runtime_presence_status(now=now)
    last_signal = dict(presence.get("last_signal") or {})
    return {
        "source": str(last_signal.get("source") or ""),
        "event_type": str(last_signal.get("event_type") or ""),
        "confidence": presence.get("confidence"),
        "level": presence.get("level"),
        "can_proactively_message": presence.get("can_proactively_message"),
        "summary": presence.get("summary"),
    }


def _snapshot_nudge_state() -> Dict[str, Any]:
    operator_state = _operator_read_state()
    records = list(operator_state.get("nudge_records") or [])
    last_feedback = None
    for rec in reversed(records):
        if rec.get("user_action"):
            last_feedback = {
                "task_id": rec.get("task_id"),
                "task_title": rec.get("task_title"),
                "feedback": rec.get("user_action"),
                "feedback_at": rec.get("feedback_at"),
            }
            break
    return {
        "pending_count": len([rec for rec in records if rec.get("outcome") == "pending"]),
        "record_count": len(records),
        "last_feedback": last_feedback,
    }


def _snapshot_adaptive_nudge_state() -> Dict[str, Any]:
    state = _operator_read_state()
    records = list(state.get("nudge_records") or [])
    outcome_counts: Dict[str, int] = {}
    time_buckets: Dict[str, Dict[str, int]] = {}
    for rec in records:
        outcome = str(rec.get("outcome") or "unknown").strip().lower() or "unknown"
        outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1
        rec_dt = _runtime_parse_iso(str(rec.get("feedback_at") or rec.get("sent_at") or ""))
        local_hour = rec_dt.astimezone(_runtime_local_tz()).hour if rec_dt else None
        if local_hour is None:
            bucket = "unknown"
        elif local_hour < 12:
            bucket = "morning"
        elif local_hour < 17:
            bucket = "afternoon"
        elif local_hour < 22:
            bucket = "evening"
        else:
            bucket = "night"
        bucket_counts = time_buckets.setdefault(bucket, {})
        bucket_counts[outcome] = bucket_counts.get(outcome, 0) + 1
    return {
        "record_count": len(records),
        "outcome_counts": outcome_counts,
        "time_buckets": time_buckets,
    }


def _snapshot_approval_state() -> Dict[str, Any]:
    approvals = _load_approvals()
    pending = dict(approvals.get("pending") or {})
    return {
        "pending_count": len(pending),
        "pending_ids": sorted(pending.keys()),
    }


def _snapshot_memory_state() -> Dict[str, Any]:
    operator_state = _operator_read_state()
    memory_state = _operator_memory_read_state()
    return {
        "memory_count": len(list(operator_state.get("operator_memories") or [])) + len(list(memory_state.get("memories") or [])),
        "rule_count": len(list(memory_state.get("rules") or [])),
        "task_metadata_count": len(dict(memory_state.get("task_metadata") or {})),
    }


def _operating_snapshot(args: Dict[str, Any]) -> Dict[str, Any]:
    limit = int(args.get("limit") or 200)
    now = datetime.now(timezone.utc)
    normalized = _normalized_events(limit=limit)
    snapshot = {
        "generated_at": now.isoformat(),
        "presence": _snapshot_presence_state(now=now),
        "nudge": _snapshot_nudge_state(),
        "adaptive_nudge": _snapshot_adaptive_nudge_state(),
        "approval": _snapshot_approval_state(),
        "memory": _snapshot_memory_state(),
    }
    return {
        "success": True,
        "action": "operating_snapshot",
        "normalized_events": normalized,
        "snapshot": snapshot,
        "common_sense_registry": _common_sense_rule_registry(),
    }


def _operating_delta(args: Dict[str, Any]) -> Dict[str, Any]:
    previous = dict(args.get("previous_snapshot") or {})
    current = dict(args.get("current_snapshot") or {})
    changes = {
        "presence_changed": previous.get("presence") != current.get("presence"),
        "nudge_feedback_changed": ((previous.get("nudge") or {}).get("last_feedback")) != ((current.get("nudge") or {}).get("last_feedback")),
        "approval_changed": previous.get("approval") != current.get("approval"),
        "memory_changed": previous.get("memory") != current.get("memory"),
    }
    changed_keys = [key for key, value in changes.items() if value]
    return {
        "success": True,
        "action": "operating_delta",
        "changes": changes,
        "summary": "No meaningful snapshot changes." if not changed_keys else f"Changed: {', '.join(changed_keys)}",
    }


def _operator_activity_count(intel: Dict[str, Any], key: str) -> int:
    return int(((intel.get("activity") or {}).get(key)) or 0)


def _operator_choose_mode(*, noise: Dict[str, Any], mood: Dict[str, Any], shapes: List[Dict[str, Any]], presence: Dict[str, Any], completed_count: int, updated_count: int) -> str:
    mood_label = str(((mood.get("last_mood") or {}).get("label") or "")).lower()
    if presence.get("configured") and not bool(presence.get("can_proactively_message")):
        return "shield"
    if mood_label in {"low_energy", "frustrated", "confused"}:
        return "coach" if completed_count else "recovery"
    if noise.get("status") in {"noisy", "getting_noisy"}:
        return "auditor"
    if any(shape["shape_score"] < 0.55 for shape in shapes[:5]):
        return "planner"
    if updated_count > completed_count + 2:
        return "auditor"
    return "operator"


def _operator_primary_friction(*, tasks: List[Dict[str, Any]], shapes: List[Dict[str, Any]], completed_count: int, updated_count: int, noise: Dict[str, Any]) -> tuple[str, str]:
    titles = " ".join(_todoist_task_title(task).lower() for task in tasks[:8])
    if any(term in titles for term in ["dialpad", "tax", "subscription", "invoice", "payment", "admin", "quo"]):
        primary = "admin_cleanup"
    elif any(shape["shape_score"] < 0.55 for shape in shapes[:5]):
        primary = "unclear_next_action"
    elif noise.get("status") in {"noisy", "getting_noisy"}:
        primary = "system_noise"
    elif len(tasks) >= 10:
        primary = "too_many_small_tasks"
    else:
        primary = "no_clear_priority" if not tasks else "execution_friction"
    risk = "task_shuffling" if updated_count > completed_count + 1 else ("system_noise" if primary == "system_noise" else "stale_task_drift")
    return primary, risk


def _operator_select_top_task(tasks: List[Dict[str, Any]], sticky: Dict[str, Any], shapes: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    shape_by_id = {shape["task_id"]: shape for shape in shapes}
    best: Optional[Dict[str, Any]] = None
    best_score = -1.0
    for task in tasks:
        task_id = _operator_task_id(task)
        shape = shape_by_id.get(task_id) or _operator_task_shape(task)
        sticky_rec = dict((sticky or {}).get(task_id) or {})
        score = 0.0
        score += _operator_task_priority(task) * 0.12
        score += float(sticky_rec.get("avoidance_score") or 0) * 0.45
        score += shape["shape_score"] * 0.18
        due = _operator_parse_task_due(task)
        if due:
            days = (datetime.now(timezone.utc).astimezone(_runtime_local_tz()).date() - due.astimezone(_runtime_local_tz()).date()).days
            if days > 0:
                score += min(0.25, days * 0.04)
        if score > best_score:
            best_score = score
            best = {
                "id": task_id,
                "title": _todoist_task_title(task),
                "project": _operator_task_project(task),
                "priority": _operator_task_priority(task),
                "avoidance_score": float(sticky_rec.get("avoidance_score") or 0),
                "shape_score": shape["shape_score"],
                "shape_issues": shape["issues"],
                "recommended_fix": shape["recommended_fix"],
                "reason_selected": "Highest combined priority, staleness, avoidance, and executability signal.",
                "raw": task,
            }
    return best


def _operator_next_action(top_task: Optional[Dict[str, Any]], mode: str) -> str:
    if not top_task:
        return "Keep the system quiet; no specific task deserves an interruption."
    title = top_task.get("title") or "the selected task"
    if mode == "planner" or float(top_task.get("shape_score") or 1) < 0.55:
        return f"Repair “{title}” into one visible next action: {top_task.get('recommended_fix') or 'verb + object + finish condition'}."
    if mode == "recovery":
        return f"Close or honestly defer “{title}”; the win is reducing tomorrow's pressure."
    if mode == "auditor":
        return f"Use “{title}” as the cleanup anchor: finish it, split it, or reschedule it honestly."
    return f"Spend 10 minutes on “{title}” now, then mark it done or reschedule it to a real date."


def _operator_recent_nudge_context(state: Dict[str, Any], now: datetime, top_task: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    nudges = list(state.get("nudge_records") or [])
    latest = nudges[-1] if nudges else None
    minutes = None
    similar = False
    recent_bad = None
    if latest:
        sent = _runtime_parse_iso(str(latest.get("sent_at") or ""))
        if sent:
            minutes = int((now - sent).total_seconds() // 60)
        similar = bool(top_task and latest.get("task_id") == top_task.get("id"))
    for rec in reversed(nudges):
        if not top_task or rec.get("task_id") != top_task.get("id"):
            continue
        if str(rec.get("outcome") or "").strip().lower() != "bad_nudge":
            continue
        sent = _runtime_parse_iso(str(rec.get("feedback_at") or rec.get("sent_at") or ""))
        if not sent:
            continue
        recent_bad = int((now - sent).total_seconds() // 60)
        break
    return {
        "last_nudge_minutes_ago": minutes,
        "similar_nudge_recently": bool(similar and minutes is not None and minutes < 90),
        "recent_bad_nudge_minutes_ago": recent_bad,
        "recent_bad_nudge_same_task": bool(recent_bad is not None and recent_bad < 24 * 60),
        "repetition_risk": "high" if similar and minutes is not None and minutes < 90 else ("medium" if minutes is not None and minutes < 45 else "low"),
        "last_nudge": latest,
    }


def _operator_time_bucket(dt: Optional[datetime]) -> str:
    if not dt:
        return "unknown"
    hour = dt.astimezone(_runtime_local_tz()).hour
    if hour < 12:
        return "morning"
    if hour < 17:
        return "afternoon"
    if hour < 22:
        return "evening"
    return "night"


def _operator_adaptive_nudge_summary(
    state: Dict[str, Any],
    *,
    top_task: Optional[Dict[str, Any]] = None,
    task_type: str = "",
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    current_time_bucket = _operator_time_bucket(now)
    records = list(state.get("nudge_records") or [])
    same_task_records: List[Dict[str, Any]] = []
    same_task_type_records: List[Dict[str, Any]] = []
    same_time_bucket_records: List[Dict[str, Any]] = []
    for rec in records:
        if top_task and str(rec.get("task_id") or "") == str(top_task.get("id") or ""):
            same_task_records.append(rec)
        if task_type and str(rec.get("task_type") or "") == task_type:
            same_task_type_records.append(rec)
            rec_dt = _runtime_parse_iso(str(rec.get("feedback_at") or rec.get("sent_at") or ""))
            if _operator_time_bucket(rec_dt) == current_time_bucket:
                same_time_bucket_records.append(rec)

    def _count_outcomes(rows: List[Dict[str, Any]]) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for row in rows:
            outcome = str(row.get("outcome") or "unknown").strip().lower() or "unknown"
            counts[outcome] = counts.get(outcome, 0) + 1
        return counts

    return {
        "record_count": len(records),
        "current_time_bucket": current_time_bucket,
        "same_task_records": same_task_records[-12:],
        "same_task_type_records": same_task_type_records[-24:],
        "same_time_bucket_records": same_time_bucket_records[-24:],
        "same_task_outcomes": _count_outcomes(same_task_records),
        "same_task_type_outcomes": _count_outcomes(same_task_type_records),
        "same_time_bucket_outcomes": _count_outcomes(same_time_bucket_records),
    }


def _operator_adaptive_nudge_route(
    *,
    top_task: Optional[Dict[str, Any]],
    top_common_sense: Optional[Dict[str, Any]],
    mode: str,
    presence: Dict[str, Any],
    recent_nudges: Dict[str, Any],
    adaptive_summary: Dict[str, Any],
) -> Dict[str, Any]:
    reasons: List[str] = []
    score = 0.72
    same_task_outcomes = dict(adaptive_summary.get("same_task_outcomes") or {})
    same_time_outcomes = dict(adaptive_summary.get("same_time_bucket_outcomes") or {})
    if mode == "shield":
        score -= 0.45
        reasons.append("Shield mode still takes priority.")
    if not top_task:
        score -= 0.4
        reasons.append("No top task is available.")
    if presence.get("configured") and not bool(presence.get("can_proactively_message")):
        score -= 0.25
        reasons.append("Presence is too weak for a proactive interruption.")
    if same_task_outcomes.get("bad_nudge", 0) >= 1:
        score -= 0.35
        reasons.append("Recent bad nudge history exists for this task.")
    if same_task_outcomes.get("blocked", 0) >= 2:
        score -= 0.18
        reasons.append("Blocked history suggests a question is better than another instruction.")
        route = "ask"
    elif same_task_outcomes.get("defer_tomorrow", 0) >= 2 and str(adaptive_summary.get("current_time_bucket")) in {"evening", "night"}:
        score -= 0.28
        reasons.append("Repeated defer-to-tomorrow outcomes in this time window reduce interruption value.")
        route = "digest"
    else:
        route = "instruct"
    score -= min(0.18, 0.09 * int(same_time_outcomes.get("defer_tomorrow", 0)))
    if recent_nudges.get("similar_nudge_recently"):
        score -= 0.14
        reasons.append("A similar nudge was sent recently.")
    if top_common_sense and not bool(top_common_sense.get("original_action_valid")):
        score -= 0.22
        reasons.append("Common sense says the original action is no longer valid as written.")
    score = round(max(0.0, min(1.0, score)), 2)
    if route == "instruct" and score < 0.35:
        route = "stay_quiet"
    elif route == "instruct" and score < 0.62:
        route = "digest"
    return {
        "route": route,
        "learned_score": score,
        "reasons": reasons or ["No adverse outcome pattern was strong enough to change the default route."],
        "evidence": {
            "same_task_outcomes": same_task_outcomes,
            "same_time_bucket_outcomes": same_time_outcomes,
            "current_time_bucket": adaptive_summary.get("current_time_bucket"),
        },
    }


def _operator_calculate_nudge_trust_score(
    task: Optional[Dict[str, Any]],
    presence: Dict[str, Any],
    recent_nudges: Dict[str, Any],
    mode: str,
    intel: Dict[str, Any],
    now_hour: int
) -> float:
    score = 2.0
    if not task:
        return 0.0
    content = str(task.get("content") or "").lower()
    labels = [str(l).lower() for l in task.get("labels") or []]

    # 1. Timing Quality
    if 9 <= now_hour < 18:
        score += 1.5
    else:
        score -= 2.0

    # 2. Urgency
    priority = int(task.get("priority") or 1)
    if priority >= 3 or "focus" in labels or "deep_work" in labels:
        score += 1.5

    # 3. Actionability
    action_verbs = {
        "read", "write", "code", "draft", "call", "email", "review", "plan",
        "clean", "prep", "build", "design", "buy", "send", "fix", "check"
    }
    has_verb = any(content.startswith(v) for v in action_verbs)
    if has_verb:
        score += 1.0

    # 4. Repetition penalty
    recent_sent = recent_nudges.get("sent_nudges") or []
    for n in recent_sent[-3:]:
        if n.get("task_id") == task.get("id"):
            score -= 3.0
            break

    # 5. Emotional load penalty
    overdue_count = len(intel.get("overdue_tasks") or [])
    if overdue_count > 15:
        score -= 1.0

    return score


def _operator_nudge_quality_gate(*, mode: str, top_task: Optional[Dict[str, Any]], presence: Dict[str, Any], focus_state: Dict[str, Any], recent_nudges: Dict[str, Any], recommended_next_action: str, intel: Dict[str, Any], now_hour: int) -> Dict[str, Any]:
    reasons: List[str] = []
    score = 0.35

    # Run user-trust/notification credibility gate
    trust_score = _operator_calculate_nudge_trust_score(top_task, presence, recent_nudges, mode, intel, now_hour)
    if trust_score < 3.0:
        reasons.append(f"Notification value score too low ({trust_score:.2f} < 3.00). Suppressing message to protect nervous system.")
    if mode == "shield":
        reasons.append("Shield mode selected.")
    if not _telegram_messages_allowed_now(now_hour):
        reasons.append("Outside allowed Telegram hours.")
    if presence.get("configured") and not bool(presence.get("can_proactively_message")):
        reasons.append("Presence is not confident enough for proactive messaging.")
    if not top_task:
        reasons.append("No specific task or project anchor.")
    else:
        score += 0.22
    if recent_nudges.get("similar_nudge_recently"):
        reasons.append("Similar nudge was sent recently.")
    else:
        score += 0.12
    if recent_nudges.get("recent_bad_nudge_same_task"):
        reasons.append("Recent bad nudge feedback exists for this task.")
    if recommended_next_action and top_task:
        score += 0.16
    if int(((intel.get("active_tasks") or {}).get("count")) or 0) > 0:
        score += 0.10
    if _operator_activity_count(intel, "completed_count") > 0:
        score += 0.05
    passed = not reasons and score >= 0.62
    return {
        "passed": passed,
        "score": round(min(1.0, score), 2),
        "reason": "Specific, evidence-backed, non-repetitive, sane timing, and likely useful." if passed else " ".join(reasons) or "Nudge value score too low.",
        "alternative_action": "send_message" if passed else ("stay_quiet" if mode == "shield" else "log_only"),
        "next_check_minutes": 90 if passed else 60,
    }


def _operator_render_telegram_message(*, mode: str, primary_friction: str, risk: str, top_task: Optional[Dict[str, Any]], completed_count: int, updated_count: int, next_action: str, noise: Dict[str, Any]) -> str:
    if not top_task:
        return "Operator note: no specific task needs an interruption right now. I am staying quiet and watching for a real state change."
    title = top_task.get("title") or "selected task"
    task_line = f"Task: “{title}”"
    changed = f"What changed: {completed_count} recent completion event(s), {updated_count} update event(s), Todoist noise is {noise.get('status')}."
    if mode == "coach":
        lead = "Operator note: this is a low-pressure clarity check."
    elif mode == "recovery":
        lead = "Recovery check: do not try to rescue the whole list right now."
    elif mode == "auditor":
        lead = "Auditor note: Todoist is asking for cleanup, not more reminders."
    elif mode == "planner":
        lead = "Planner note: the task shape is the friction."
    else:
        lead = "Operator note: this is worth interrupting because there is a specific next move."
    return "\n".join([
        lead,
        f"The issue looks like {primary_friction}, with risk of {risk}.",
        task_line,
        changed,
        f"Best next 5-15 minutes: {next_action}",
        "If that is not realistic today, reschedule it honestly instead of letting it float.",
    ])


def _operator_update_daily_narrative(state: Dict[str, Any], brief: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    date_key = _operator_local_date(now)
    narrative = dict(state.get("daily_narrative") or {})
    day = dict(narrative.get(date_key) or {"date": date_key})
    hour = now.astimezone(_runtime_local_tz()).hour
    if hour < 11:
        slot = "morning_assessment"
    elif hour < 16:
        slot = "midday_assessment"
    elif hour < 21:
        slot = "afternoon_assessment"
    else:
        slot = "evening_assessment"
    day[slot] = brief.get("summary")
    day["completed_count"] = ((brief.get("evidence") or {}).get("todoist_mcp") or {}).get("completed_recently")
    day["sticky_tasks"] = [((brief.get("top_task") or {}).get("title"))] if brief.get("top_task") else []
    day["main_lesson"] = brief.get("recommended_next_action")
    day["last_updated"] = now.isoformat()
    narrative[date_key] = day
    state["daily_narrative"] = dict(sorted(narrative.items())[-14:])
    return state


def _operator_feedback_buttons(brief: Dict[str, Any]) -> List[str]:
    common = (brief.get("common_sense") or {}) if isinstance(brief.get("common_sense"), dict) else {}
    best = common.get("best_decision") if isinstance(common.get("best_decision"), dict) else {}
    buttons = [str(button).strip() for button in list(best.get("buttons") or []) if str(button).strip()]
    if buttons:
        return buttons
    return ["Done", "Defer 30m", "Blocked", "Bad nudge"]


def _operator_record_nudge(state: Dict[str, Any], brief: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    if not brief.get("should_message"):
        return state
    records = list(state.get("nudge_records") or [])
    top_task = brief.get("top_task") or {}
    best_decision = (((brief.get("common_sense") or {}).get("best_decision")) if isinstance(brief.get("common_sense"), dict) else {}) or {}
    buttons = _operator_feedback_buttons(brief)
    records.append({
        "id": f"nudge_{now.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}",
        "task_id": top_task.get("id"),
        "task_title": top_task.get("title"),
        "task_type": best_decision.get("task_type"),
        "sent_at": now.isoformat(),
        "message_class": "operator_brief",
        "mode": brief.get("mode"),
        "tone": ((brief.get("evidence") or {}).get("mood") or {}).get("recommended_tone"),
        "message": brief.get("telegram_message"),
        "buttons": buttons,
        "quality_gate_score": (brief.get("nudge_gate") or {}).get("score"),
        "expected_outcome": "complete_or_reschedule",
        "followup_after_minutes": (brief.get("next_check") or {}).get("minutes"),
        "outcome": "pending",
        "user_action": None,
    })
    state["nudge_records"] = records[-120:]
    state["last_message_at"] = now.isoformat()
    return state


def _operator_attach_nudge_delivery(
    state: Dict[str, Any],
    *,
    response: Optional[Dict[str, Any]],
    now: datetime,
) -> Dict[str, Any]:
    records = list(state.get("nudge_records") or [])
    if not records:
        return state
    latest = records[-1]
    if latest.get("outcome") != "pending":
        state["nudge_records"] = records[-120:]
        return state
    payload = dict(response or {})
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    message_id = payload.get("message_id") or result.get("message_id")
    if message_id is not None:
        latest["message_id"] = str(message_id)
    latest["delivery"] = "sent"
    latest["delivered_at"] = now.isoformat()
    state["nudge_records"] = records[-120:]
    return state


def _operator_feedback_policy_update(feedback: str) -> str:
    normalized = str(feedback or "").strip().lower()
    mapping = {
        "done": "Completed from Telegram feedback; reduce follow-up pressure on this nudge.",
        "defer_30m": "Deferred by user; check later without repeating the same wording immediately.",
        "defer_tomorrow": "Deferred to tomorrow; avoid more pressure tonight.",
        "blocked": "Blocked by user feedback; prefer blocker clarification over another execution nudge.",
        "bad_nudge": "Bad nudge received; reduce similar nudges in matching context and prefer repair or silence.",
        "handled": "Handled elsewhere; do not assume Todoist incompletion means the work was not done.",
        "schedule_next_window": "Needs next-window scheduling; preserve timing constraints instead of pushing now.",
        "draft_tomorrow": "After-hours recovery chosen; prefer draft/schedule paths for similar tasks.",
    }
    return mapping.get(normalized, "Feedback recorded; use it to refine timing, task shape, and nudge style.")


def _operator_record_feedback(args: Dict[str, Any], *, now: datetime) -> Dict[str, Any]:
    state = _operator_read_state()
    records = list(state.get("nudge_records") or [])
    message_id = str(args.get("message_id") or "").strip()
    feedback = str(args.get("feedback") or "").strip().lower()
    task_id = str(args.get("task_id") or "").strip()
    if not feedback:
        raise ValueError("feedback is required")
    target = None
    for rec in reversed(records):
        if message_id and str(rec.get("message_id") or "").strip() == message_id:
            target = rec
            break
        if task_id and str(rec.get("task_id") or "").strip() == task_id and rec.get("outcome") == "pending":
            target = rec
            break
    if target is None:
        return {
            "handled": False,
            "event_type": "telegram_feedback",
            "feedback": feedback,
            "summary": "No matching nudge receipt was found for Telegram feedback.",
        }
    target["user_action"] = feedback
    target["feedback_at"] = now.isoformat()
    target["outcome"] = feedback
    target["checked_at"] = now.isoformat()
    target["confidence"] = 0.95
    target["policy_update"] = _operator_feedback_policy_update(feedback)
    state["nudge_records"] = records[-120:]
    _operator_write_state(state)
    proposal = _record_bad_nudge_self_improvement(target, now=now) if feedback == "bad_nudge" else None
    return {
        "handled": True,
        "event_type": "telegram_feedback",
        "feedback": feedback,
        "task_id": target.get("task_id"),
        "message_id": target.get("message_id"),
        "summary": f"Recorded Telegram feedback '{feedback}' for the matching nudge receipt.",
        "receipt": target,
        "self_improve_proposal": proposal,
    }


def _operator_update_nudge_outcomes(state: Dict[str, Any], active_tasks: List[Dict[str, Any]], now: datetime) -> Dict[str, Any]:
    active_ids = {_operator_task_id(task) for task in active_tasks if _operator_task_id(task)}
    records = list(state.get("nudge_records") or [])
    for rec in records:
        if rec.get("outcome") != "pending":
            continue
        sent = _runtime_parse_iso(str(rec.get("sent_at") or ""))
        if not sent or (now - sent).total_seconds() < 45 * 60:
            continue
        task_id = str(rec.get("task_id") or "")
        rec["checked_at"] = now.isoformat()
        rec["outcome"] = "ignored" if task_id in active_ids else "completed_or_removed"
        rec["confidence"] = 0.72 if rec["outcome"] == "completed_or_removed" else 0.61
        rec["lesson"] = "Task no longer appears in active view after nudge." if rec["outcome"] == "completed_or_removed" else "Task still appears after nudge; next intervention should repair, split, or defer."
    state["nudge_records"] = records[-120:]
    return state


def _operator_brief(args: Dict[str, Any]) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    now_hour = _adaptive_companion_now_local_hour()
    state = _operator_read_state()
    intel = _todoist_intelligence({"filter": args.get("filter") or "today | overdue", "limit": int(args.get("limit") or 12), "project_id": args.get("project_id") or ""})
    tasks = list(((intel.get("active_tasks") or {}).get("tasks")) or [])
    state = _operator_update_avoidance_memory(state, tasks, now)
    state = _operator_update_nudge_outcomes(state, tasks, now)
    shapes = [_operator_task_shape(task) for task in tasks]
    noise = _operator_analyze_noise(tasks, shapes, now)
    mood = _mood_router_status()
    presence = _runtime_presence_status(now=now)
    focus_state = _focus_guard_read_state()
    live_watch = _runtime_live_watch_status()
    completed_count = _operator_activity_count(intel, "completed_count")
    updated_count = _operator_activity_count(intel, "updated_count")
    mode = _operator_choose_mode(
        noise=noise,
        mood=mood,
        shapes=shapes,
        presence=presence,
        completed_count=completed_count,
        updated_count=updated_count,
    )
    primary_friction, risk = _operator_primary_friction(
        tasks=tasks,
        shapes=shapes,
        completed_count=completed_count,
        updated_count=updated_count,
        noise=noise,
    )
    common_sense = _common_sense_analyze_tasks(tasks, now=_common_sense_now())
    top_task = _operator_select_top_task(tasks, dict(state.get("sticky_tasks") or {}), shapes)
    next_action = _operator_next_action(top_task, mode)
    recent_nudges = _operator_recent_nudge_context(state, now, top_task)
    top_common_sense = None
    if top_task and top_task.get("id"):
        top_common_sense = (common_sense.get("decision_by_task_id") or {}).get(str(top_task.get("id")))
    adaptive_summary = _operator_adaptive_nudge_summary(
        state,
        top_task=top_task,
        task_type=str((top_common_sense or {}).get("task_type") or ""),
        now=_common_sense_now(),
    )
    adaptive_nudge = _operator_adaptive_nudge_route(
        top_task=top_task,
        top_common_sense=top_common_sense,
        mode=mode,
        presence=presence,
        recent_nudges=recent_nudges,
        adaptive_summary=adaptive_summary,
    )
    gate = _operator_nudge_quality_gate(
        mode=mode,
        top_task=top_task,
        presence=presence,
        focus_state=focus_state,
        recent_nudges=recent_nudges,
        recommended_next_action=next_action,
        intel=intel,
        now_hour=now_hour,
    )
    if top_common_sense and not bool(top_common_sense.get("original_action_valid")):
        gate = {
            **gate,
            "passed": False,
            "score": min(float(gate.get("score") or 0), 0.45),
            "reason": f"Common sense blocked original task: {top_common_sense.get('current_status')}. {gate.get('reason')}",
            "alternative_action": str(top_common_sense.get("best_mode") or "ask_or_recover"),
        }
        next_action = str(top_common_sense.get("safe_next_action") or next_action)
    if adaptive_nudge.get("route") == "digest":
        gate = {
            **gate,
            "passed": False,
            "score": min(float(gate.get("score") or 0), float(adaptive_nudge.get("learned_score") or 0)),
            "reason": f"Adaptive nudge routing chose digest. {gate.get('reason')}",
            "alternative_action": "digest",
            "next_check_minutes": 180,
        }
    elif adaptive_nudge.get("route") == "ask":
        gate = {
            **gate,
            "passed": bool(args.get("allow_message", True)),
            "score": max(float(gate.get("score") or 0), float(adaptive_nudge.get("learned_score") or 0)),
            "reason": f"Adaptive nudge routing chose ask. {gate.get('reason')}",
            "alternative_action": "ask",
            "next_check_minutes": 120,
        }
    elif adaptive_nudge.get("route") == "stay_quiet":
        gate = {
            **gate,
            "passed": False,
            "score": min(float(gate.get("score") or 0), float(adaptive_nudge.get("learned_score") or 0)),
            "reason": f"Adaptive nudge routing chose stay_quiet. {gate.get('reason')}",
            "alternative_action": "stay_quiet",
            "next_check_minutes": 180,
        }
    should_message = bool(gate.get("passed")) and bool(args.get("allow_message", True))
    telegram_message = _operator_render_telegram_message(
        mode=mode,
        primary_friction=primary_friction,
        risk=risk,
        top_task=top_task,
        completed_count=completed_count,
        updated_count=updated_count,
        next_action=next_action,
        noise=noise,
    )
    if top_common_sense and not bool(top_common_sense.get("original_action_valid")):
        telegram_message = str(top_common_sense.get("telegram_text") or telegram_message)
    elif adaptive_nudge.get("route") == "ask" and top_task:
        telegram_message = (
            f"Operator question: this task looks blocked instead of ignored.\n"
            f"Task: \"{top_task.get('title') or 'selected task'}\"\n"
            f"What is blocked right now? Reply with the blocker or use the buttons so I can stop repeating the wrong move."
        )
    summary = (
        f"Operator brief: mode={mode}, friction={primary_friction}, risk={risk}, "
        f"tasks={len(tasks)}, completed_recently={completed_count}, noise={noise.get('status')}."
    )
    brief = {
        "success": True,
        "action": "operator_brief",
        "mode": mode,
        "should_message": should_message,
        "confidence": gate.get("score"),
        "message_reason": gate.get("reason"),
        "primary_friction": primary_friction,
        "secondary_friction": "vague_tasks" if any(shape["shape_score"] < 0.65 for shape in shapes) else None,
        "risk": risk,
        "top_task": top_task,
        "recommended_next_action": next_action,
        "telegram_message": telegram_message,
        "summary": summary,
        "common_sense": {
            "best_decision": top_common_sense or ((common_sense.get("summary") or {}).get("best_move")),
            "late_day_salvage": common_sense.get("late_day_salvage"),
            "operating_state": common_sense.get("operating_state"),
            "core_rule": common_sense.get("core_rule"),
        },
        "adaptive_nudge": adaptive_nudge,
        "nudge_gate": gate,
        "task_shapes": shapes[:12],
        "task_avoidance_memory": list((state.get("sticky_tasks") or {}).values())[:12],
        "anti_noise": noise,
        "evidence": {
            "todoist_mcp": {
                "active_count": len(tasks),
                "completed_recently": completed_count,
                "updated_recently": updated_count,
                "stale_tasks": len([rec for rec in (state.get("sticky_tasks") or {}).values() if float(rec.get("avoidance_score") or 0) >= 0.65]),
                "noise": noise,
            },
            "focus_guard": focus_state,
            "presence": presence,
            "mood": mood,
            "recent_nudges": recent_nudges,
            "adaptive_nudge_summary": adaptive_summary,
            "live_watch": live_watch,
            "common_sense": common_sense,
        },
        "next_check": {"minutes": gate.get("next_check_minutes"), "condition": "Check whether the top task was completed, edited, rescheduled, or ignored."},
    }
    state["current_mode"] = mode
    state["last_brief_at"] = now.isoformat()
    state["last_brief"] = {k: brief.get(k) for k in ["mode", "should_message", "summary", "top_task", "nudge_gate"]}
    state = _operator_update_daily_narrative(state, brief, now)
    state = _operator_record_nudge(state, brief, now) if should_message else state
    _operator_write_state(state)
    _append_jsonl(OPERATOR_BRIEF_LOG_PATH, {"ts": now.isoformat(), **{k: brief.get(k) for k in ["mode", "should_message", "summary", "top_task", "nudge_gate"]}})
    _append_jsonl(
        TRACE_LOG_PATH,
        _build_trace_entry(
            trace_type="operator_cycle",
            trace_family="operator",
            span_name="operator_brief",
            status="success",
            tags=["operator", "adaptive_nudge", str((brief.get("adaptive_nudge") or {}).get("route") or "unknown")],
            data={
                "mode": brief.get("mode"),
                "adaptive_route": (brief.get("adaptive_nudge") or {}).get("route"),
                "should_message": brief.get("should_message"),
                "top_task_title": ((brief.get("top_task") or {}).get("title")),
                "nudge_gate_score": (brief.get("nudge_gate") or {}).get("score"),
            },
        ),
    )
    if should_message and bool(args.get("send_telegram", False)):
        send_result = _focus_guard_send_telegram_message(telegram_message, buttons=_operator_feedback_buttons(brief))
        state = _operator_read_state()
        state = _operator_attach_nudge_delivery(state, response=send_result, now=now)
        _operator_write_state(state)
        brief["sent"] = True
        brief["send_result"] = send_result
    else:
        brief["sent"] = False
    return brief


def _operator_weekly_review(args: Dict[str, Any]) -> Dict[str, Any]:
    state = _operator_read_state()
    sticky = list((state.get("sticky_tasks") or {}).values())
    briefs = _read_jsonl_recent(OPERATOR_BRIEF_LOG_PATH, limit=200)
    nudges = list(state.get("nudge_records") or [])
    noisy_briefs = [b for b in briefs if "noise=noisy" in str(b.get("summary") or "") or "noise=getting_noisy" in str(b.get("summary") or "")]
    ignored = [n for n in nudges if n.get("outcome") == "ignored"]
    completed = [n for n in nudges if n.get("outcome") == "completed_or_removed"]
    top_sticky = sorted(sticky, key=lambda rec: float(rec.get("avoidance_score") or 0), reverse=True)[:8]
    improvements = []
    if top_sticky:
        improvements.append("Repair or finish the highest-avoidance sticky tasks.")
    if noisy_briefs:
        improvements.append("Run a Todoist cleanup pass before adding more reminders.")
    if ignored:
        improvements.append("Switch ignored task nudges into Planner Mode and repair task shape first.")
    if not improvements:
        improvements.append("Keep Today limited to tasks that are actually executable today.")
    return {
        "success": True,
        "action": "weekly_review",
        "week_summary": (
            f"Operator review: {len(briefs)} brief(s), {len(nudges)} nudge record(s), "
            f"{len(top_sticky)} sticky task(s), {len(noisy_briefs)} noisy-system signal(s)."
        ),
        "sticky_tasks": top_sticky,
        "nudge_outcomes": {
            "sent": len(nudges),
            "ignored": len(ignored),
            "completed_or_removed": len(completed),
            "pending": len([n for n in nudges if n.get("outcome") == "pending"]),
        },
        "daily_narrative": state.get("daily_narrative") or {},
        "top_improvements": improvements[:5],
        "evidence_policy": "Evidence policy: lessons are based only on operator briefs, Todoist activity, and nudge outcomes stored locally.",
    }


_AGI_TOOL_ROLES = {
    "todoist": "Personal execution, today list, recurring routines, task quality, sticky task tracking.",
    "hermes": "Reasoning, judgment, conversation, orchestration, memory, approval gates, and quiet-hours policy.",
}


def _agi_default_world_model() -> Dict[str, Any]:
    return {
        "user": {
            "current_goals": [
                "Reduce personal cognitive load",
                "Make one clear next move",
                "Keep Todoist useful instead of noisy",
                "Protect attention and energy",
            ],
            "energy_patterns": [],
            "avoidance_patterns": ["Admin/tooling work can become sticky unless it has a clear next action."],
            "preferred_tones": ["direct_low_pressure", "specific", "evidence_based"],
            "known_stressors": ["vague overdue tasks", "generic nudges", "notification noise"],
            "known_productivity_traps": ["task_shuffling", "overplanning", "reference material in Today"],
        },
        "life_systems": {
            "todoist": {"role": _AGI_TOOL_ROLES["todoist"]},
            "calendar": {"role": "Time commitments and availability; observe only unless connected."},
            "email": {"role": "Inbox and correspondence; draft before sending if connected."},
            "messages": {"role": "Personal messages and reminders; external sends require approval if connected."},
            "notes": {"role": "Reference and strategy, not active task execution."},
            "health_routines": {"role": "Energy and discipline support; avoid guilt loops."},
        },
        "business_systems": {},
        "active_context": {
            "today": {},
            "this_week": {},
            "current_projects": [],
            "open_loops": [],
            "risks": [],
            "blocked_items": [],
        },
    }


def _agi_task_domain(task: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    title = str((task or {}).get("title") or "").lower()
    project = str((task or {}).get("project") or "").lower()
    text = f"{title} {project}"
    systems: List[str] = []
    supports: List[str] = []
    impact = "medium"
    category = "personal_task"
    if any(term in text for term in ["health", "gym", "movement", "walk", "sleep", "meal", "exercise"]):
        systems.extend(["todoist", "hermes"])
        supports.extend(["Protect energy", "Maintain personal routines", "Make progress visible"])
        impact = "medium"
        category = "personal_routine"
    if any(term in text for term in ["family", "handoff", "home", "laundry", "clean", "errand", "call", "message"]):
        systems.extend(["todoist", "hermes"])
        supports.extend(["Reduce home and personal open loops", "Protect relationships and follow-through"])
        category = "personal_admin"
    if any(term in text for term in ["tax", "invoice", "payment", "subscription", "admin", "paperwork"]):
        systems.extend(["todoist", "hermes"])
        supports.extend(["Reduce admin clutter", "Keep personal systems clean"])
        category = "personal_admin"
    if not systems:
        systems.extend(["todoist", "hermes"])
    if not supports:
        supports.append("Reduce personal cognitive load")
    return {
        "category": category,
        "systems": sorted(set(systems)),
        "supports": sorted(set(supports)),
        "impact": impact,
        "priority_multiplier": 1.6 if impact in {"high", "medium_high"} else 1.0,
    }


def _agi_goal_graph(brief: Dict[str, Any]) -> Dict[str, Any]:
    top_task = brief.get("top_task") if isinstance(brief.get("top_task"), dict) else None
    domain = _agi_task_domain(top_task)
    active_goal = "Make one clear personal next move" if domain["category"] in {"personal_admin", "personal_routine"} else "Reduce personal cognitive load"
    return {
        "top_level_goals": [
            {
                "goal": "Reduce personal cognitive load",
                "subgoals": [
                    "Keep Todoist clean",
                    "Avoid overdue clutter",
                    "Use fewer but better reminders",
                    "Close loops instead of carrying them",
                ],
            },
            {
                "goal": "Make one clear personal next move",
                "subgoals": [
                    "Choose one task with a visible finish line",
                    "Repair vague tasks before nudging them",
                    "Respect energy, quiet hours, and attention",
                    "Prefer silence when there is no useful intervention",
                ],
            },
        ],
        "active_goal": active_goal,
        "supporting_task": (top_task or {}).get("title"),
        "supports": domain["supports"],
        "connected_systems": domain["systems"],
        "impact": domain["impact"],
        "task_category": domain["category"],
    }


def _agi_build_beliefs(brief: Dict[str, Any], goal_graph: Dict[str, Any]) -> List[Dict[str, Any]]:
    evidence = brief.get("evidence") if isinstance(brief.get("evidence"), dict) else {}
    todoist = evidence.get("todoist_mcp") if isinstance(evidence.get("todoist_mcp"), dict) else {}
    noise = todoist.get("noise") if isinstance(todoist.get("noise"), dict) else brief.get("anti_noise") or {}
    top_task = brief.get("top_task") if isinstance(brief.get("top_task"), dict) else {}
    completed = int(todoist.get("completed_recently") or 0)
    stale = int(todoist.get("stale_tasks") or 0)
    active = int(todoist.get("active_count") or 0)
    updated = int(todoist.get("updated_recently") or 0)
    beliefs: List[Dict[str, Any]] = []
    if top_task:
        ev = [
            f"Top task selected: {top_task.get('title')}",
            f"Avoidance score: {top_task.get('avoidance_score')}",
            f"Shape score: {top_task.get('shape_score')}",
        ]
        if completed:
            ev.append(f"{completed} recent completion event(s), so the user is not globally stuck.")
        if stale:
            ev.append(f"{stale} stale task signal(s) in operator memory.")
        beliefs.append({
            "belief": f"The highest leverage current move is to close or clarify '{top_task.get('title')}'.",
            "confidence": round(max(0.45, min(0.92, float(top_task.get("avoidance_score") or 0) * 0.45 + float(top_task.get("shape_score") or 0) * 0.35 + 0.25)), 2),
            "evidence": ev,
            "counter_evidence": ["Recent completions suggest a lower-pressure tone is better."] if completed else [],
            "recommended_response": brief.get("recommended_next_action"),
        })
    beliefs.append({
        "belief": "Todoist quality should be managed as a system, not treated as a perfect source of truth.",
        "confidence": round(0.55 + min(0.35, float((noise or {}).get("todoist_noise_score") or 0) * 0.35), 2),
        "evidence": [
            f"Active task count: {active}",
            f"Updated recently: {updated}",
            f"Noise status: {(noise or {}).get('status')}",
        ],
        "counter_evidence": [],
        "recommended_response": "Prefer task repair or silence when the data is vague, repetitive, or noisy.",
    })
    if goal_graph.get("connected_systems"):
        beliefs.append({
            "belief": "Small personal tasks can carry attention cost when they stay open and vague.",
            "confidence": 0.66 if goal_graph.get("impact") in {"high", "medium_high"} else 0.58,
            "evidence": [f"Connected systems: {', '.join(goal_graph.get('connected_systems') or [])}"],
            "counter_evidence": [],
            "recommended_response": "Frame the next action by personal clarity and reduced cognitive load, not guilt.",
        })
    return beliefs


def _agi_predictions(brief: Dict[str, Any], beliefs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    gate = brief.get("nudge_gate") if isinstance(brief.get("nudge_gate"), dict) else {}
    recent = (((brief.get("evidence") or {}).get("recent_nudges") or {}) if isinstance(brief.get("evidence"), dict) else {})
    return [
        {
            "prediction": "Another generic overdue reminder will likely be ignored or create notification blindness.",
            "confidence": 0.82,
            "based_on": ["User preference for specific task names", "Nudge quality gate exists to block generic reminders"],
        },
        {
            "prediction": "A specific one-move operator note is useful only if the quality gate passes and repetition risk is low.",
            "confidence": round(float(gate.get("score") or 0.5), 2),
            "based_on": [str(gate.get("reason") or "nudge gate result"), f"Repetition risk: {recent.get('repetition_risk')}"],
        },
        {
            "prediction": "If the task stays open after the follow-up window, task repair will be more useful than another push.",
            "confidence": 0.68,
            "based_on": [beliefs[0]["belief"] if beliefs else "No strong task belief"],
        },
    ]


def _agi_cognitive_load(brief: Dict[str, Any]) -> Dict[str, Any]:
    evidence = brief.get("evidence") if isinstance(brief.get("evidence"), dict) else {}
    todoist = evidence.get("todoist_mcp") if isinstance(evidence.get("todoist_mcp"), dict) else {}
    noise = todoist.get("noise") if isinstance(todoist.get("noise"), dict) else brief.get("anti_noise") or {}
    active = int(todoist.get("active_count") or 0)
    stale = int(todoist.get("stale_tasks") or 0)
    sources = list((noise or {}).get("main_sources") or [])
    if active >= 12 or stale >= 5 or (noise or {}).get("status") == "noisy":
        level = "high"
    elif active >= 8 or stale >= 2 or (noise or {}).get("status") == "getting_noisy":
        level = "moderate_high"
    elif active:
        level = "moderate"
    else:
        level = "low"
    return {
        "level": level,
        "main_cause": ", ".join(sources[:3]) if sources else "active open loops",
        "recommended_move": "Choose one closeable task or cleanly defer one stale item before adding more work.",
    }


def _agi_tool_plan(request: str, brief: Dict[str, Any], goal_graph: Dict[str, Any]) -> Dict[str, Any]:
    text = f"{request} {(brief.get('recommended_next_action') or '')} {(goal_graph.get('supporting_task') or '')}".lower()
    tools_needed = {"todoist", "hermes"}
    keyword_map = {
        "task": ["todoist"],
        "todo": ["todoist"],
        "today": ["todoist"],
        "overdue": ["todoist"],
        "routine": ["todoist", "hermes"],
        "goal": ["todoist", "hermes"],
        "memory": ["hermes"],
        "report": ["hermes"],
        "automation": ["hermes"],
        "todoist": ["todoist"],
        "hermes": ["hermes"],
    }
    for keyword, names in keyword_map.items():
        if keyword in text:
            tools_needed.update(names)
    risky_terms = ["send", "reply", "publish", "delete", "refund", "charge", "bulk", "external"]
    approval_required = any(term in text for term in risky_terms)
    action_plan = []
    for tool in sorted(tools_needed):
        action_plan.append({"tool": tool, "purpose": _AGI_TOOL_ROLES.get(tool, "Connected tool role is not configured yet.")})
    return {
        "tools_needed": sorted(tools_needed),
        "tool_roles": {tool: _AGI_TOOL_ROLES.get(tool, "Connected tool role is not configured yet.") for tool in sorted(tools_needed)},
        "action_plan": action_plan,
        "safe_to_execute": not approval_required,
        "approval_required": approval_required,
        "reason": "External, destructive, public, financial, or bulk actions require approval." if approval_required else "Hermes/Todoist reading, analysis, drafts, and internal notes are safe inside current autonomy bounds.",
    }


def _agi_approval(tool_plan: Dict[str, Any], requested_level: int = 2) -> Dict[str, Any]:
    risky = bool(tool_plan.get("approval_required"))
    risk = "external_or_sensitive" if risky else "low_internal"
    return {
        "required": risky or requested_level >= 4,
        "risk": risk,
        "reason": tool_plan.get("reason"),
        "allowed_without_approval": [
            "Read safe connected state",
            "Analyze tasks and projects",
            "Draft internal recommendations",
            "Create operator summaries",
            "Send Telegram notes only when the nudge gate passes",
        ],
        "requires_approval": [
            "Delete or bulk edit tasks",
            "Send external messages",
            "Publish social posts",
            "Charge, refund, or alter financial records",
            "Trigger irreversible external workflows",
        ],
    }


def _agi_internal_council(brief: Dict[str, Any], goal_graph: Dict[str, Any], tool_plan: Dict[str, Any]) -> Dict[str, str]:
    top_title = ((brief.get("top_task") or {}).get("title") if isinstance(brief.get("top_task"), dict) else None) or "the current open loop"
    should_message = bool(brief.get("should_message"))
    return {
        "operator": f"Choose one concrete move: {brief.get('recommended_next_action') or 'stay quiet until evidence improves'}.",
        "strategist": f"Prioritize {top_title} because it supports {goal_graph.get('active_goal')}.",
        "auditor": f"Todoist noise is {((brief.get('anti_noise') or {}).get('status'))}; repair vague or stale items before adding more reminders.",
        "coach": "Use a direct low-pressure tone; name evidence and avoid shame.",
        "security": "No risky external action without approval." if tool_plan.get("approval_required") else "Telegram/internal analysis is inside safe bounds.",
        "toolsmith": f"Use {', '.join(tool_plan.get('tools_needed') or ['todoist'])} for this move; Hermes remains the reasoning layer.",
        "shield": "Message is justified by the gate." if should_message else "Stay quiet unless new evidence appears.",
    }


def _agi_self_audit(brief: Dict[str, Any], beliefs: List[Dict[str, Any]], approval: Dict[str, Any]) -> Dict[str, Any]:
    gate = brief.get("nudge_gate") if isinstance(brief.get("nudge_gate"), dict) else {}
    evidence_quality = "high" if beliefs and beliefs[0].get("evidence") and float(gate.get("score") or 0) >= 0.7 else ("medium" if beliefs else "low")
    annoyance = "medium" if not gate.get("passed") else "low"
    if (((brief.get("evidence") or {}).get("recent_nudges") or {}).get("similar_nudge_recently")):
        annoyance = "high"
    return {
        "overreach_risk": "medium" if approval.get("required") else "low",
        "annoyance_risk": annoyance,
        "evidence_quality": evidence_quality,
        "approval_required": bool(approval.get("required")),
        "final_decision": "ask_approval_or_draft_only" if approval.get("required") else ("send_short_operator_message" if brief.get("should_message") else "stay_quiet"),
    }


def _agi_one_move(brief: Dict[str, Any], goal_graph: Dict[str, Any]) -> Dict[str, Any]:
    top_task = brief.get("top_task") if isinstance(brief.get("top_task"), dict) else {}
    title = top_task.get("title") or "No specific task selected"
    return {
        "action": brief.get("recommended_next_action") or "Stay quiet until stronger evidence appears.",
        "task": title,
        "why_this": top_task.get("reason_selected") or f"It best supports {goal_graph.get('active_goal')}.",
        "why_not_other_tasks": "Other items are lower impact, less stale, less executable, or less supported by evidence.",
        "time_box": "10 minutes" if top_task else "none",
    }


def _agi_render_message(brief: Dict[str, Any], goal_graph: Dict[str, Any], one_move: Dict[str, Any], beliefs: List[Dict[str, Any]]) -> str:
    top_task = brief.get("top_task") if isinstance(brief.get("top_task"), dict) else None
    if not top_task:
        return "Shield mode: no Telegram message. There is no specific evidence-backed move worth interrupting you for right now."
    completed = (((brief.get("evidence") or {}).get("todoist_mcp") or {}).get("completed_recently"))
    completed_line = f"You are not stuck overall - {completed} recent completion event(s) are visible." if completed else "This is not a generic productivity push."
    belief_line = (beliefs[0].get("belief") if beliefs else "The useful move is the smallest clear action.")
    return "\n".join([
        "Operator note: evidence points to one move, not more planning.",
        completed_line,
        f"Pattern: {belief_line}",
        f"Why it matters: {top_task.get('title')} supports {goal_graph.get('active_goal')} and touches {', '.join(goal_graph.get('connected_systems') or ['todoist'])}.",
        f"Best next 5-15 minutes: {one_move.get('action')}",
        "If it is blocked, write the blocker into the task instead of carrying it forward unchanged.",
    ])


def _agi_operator_cycle(args: Dict[str, Any]) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    request = str(args.get("request") or "").strip()
    requested_level = int(args.get("autonomy_level") or 2)
    should_observe = not (request and bool(args.get("allow_message")) is False and not args.get("force_observe"))
    if should_observe:
        brief = _operator_brief({
            "filter": args.get("filter") or "today | overdue",
            "limit": int(args.get("limit") or 12),
            "project_id": args.get("project_id") or "",
            "allow_message": bool(args.get("allow_message", True)),
            "send_telegram": False,
        })
    else:
        state = _operator_read_state()
        brief = dict((state.get("last_brief") or {}) if isinstance(state.get("last_brief"), dict) else {})
        brief.update({
            "success": True,
            "action": "operator_brief",
            "mode": brief.get("mode") or "advisor",
            "should_message": False,
            "recommended_next_action": "Build an approval-safe tool plan before acting.",
            "top_task": brief.get("top_task") if isinstance(brief.get("top_task"), dict) else None,
            "nudge_gate": {"passed": False, "score": 0.0, "reason": "Request-only cycle; no Telegram nudge."},
            "evidence": {"todoist_mcp": {"active_count": 0, "completed_recently": 0, "updated_recently": 0, "stale_tasks": 0}},
            "anti_noise": {"status": "unknown", "todoist_noise_score": 0.0, "main_sources": []},
        })
    goal_graph = _agi_goal_graph(brief)
    beliefs = _agi_build_beliefs(brief, goal_graph)
    predictions = _agi_predictions(brief, beliefs)
    cognitive_load = _agi_cognitive_load(brief)
    tool_plan = _agi_tool_plan(request, brief, goal_graph)
    approval = _agi_approval(tool_plan, requested_level=requested_level)
    council = _agi_internal_council(brief, goal_graph, tool_plan)
    self_audit = _agi_self_audit(brief, beliefs, approval)
    one_move = _agi_one_move(brief, goal_graph)
    gate = brief.get("nudge_gate") if isinstance(brief.get("nudge_gate"), dict) else {}
    should_act = bool(brief.get("should_message")) and not bool(approval.get("required")) and bool(gate.get("passed"))
    best_move = "send_operator_note" if should_act else ("stay_quiet" if brief.get("mode") == "shield" or not gate.get("passed") else "log_operator_note")
    telegram_message = _agi_render_message(brief, goal_graph, one_move, beliefs)
    state = _operator_read_state()
    world_model = _agi_default_world_model()
    world_model["active_context"].update({
        "today": {"summary": brief.get("summary"), "cognitive_load": cognitive_load},
        "current_projects": [goal_graph.get("active_goal")],
        "open_loops": [one_move],
        "risks": [brief.get("risk"), cognitive_load.get("main_cause")],
        "blocked_items": [one_move.get("task")] if "blocked" in str(brief.get("recommended_next_action") or "").lower() else [],
    })
    cycle = {
        "success": True,
        "action": "agi_operator_cycle",
        "cycle_id": f"agi_cycle_{now.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}",
        "timestamp": now.isoformat(),
        "mode": brief.get("mode"),
        "autonomy_level": requested_level,
        "autonomy": {
            "level": requested_level,
            "label": "Draft Only" if requested_level == 2 else ("Safe Internal Actions" if requested_level == 3 else "Observe/Suggest"),
            "hard_guardrails": approval.get("requires_approval"),
        },
        "should_act": should_act,
        "action_type": "telegram_message" if should_act else ("approval_safe_tool_plan" if approval.get("required") else "log_only"),
        "primary_objective": "Reduce friction and avoid avoidable failures without increasing notification noise.",
        "world_model": world_model,
        "observe": {"operator_brief": brief},
        "interpret": {
            "summary": brief.get("summary"),
            "primary_friction": brief.get("primary_friction"),
            "secondary_friction": brief.get("secondary_friction"),
            "risk": brief.get("risk"),
            "cognitive_load": cognitive_load,
        },
        "current_assessment": {
            "summary": brief.get("summary"),
            "primary_friction": brief.get("primary_friction"),
            "secondary_friction": brief.get("secondary_friction"),
            "momentum": "shuffling" if brief.get("risk") == "task_shuffling" else ("partial" if (((brief.get("evidence") or {}).get("todoist_mcp") or {}).get("completed_recently")) else "weak"),
            "todoist_noise": ((brief.get("anti_noise") or {}).get("status")),
            "cognitive_load": cognitive_load.get("level"),
        },
        "goal_graph": goal_graph,
        "beliefs": beliefs,
        "top_belief": beliefs[0] if beliefs else None,
        "predictions": predictions,
        "plans": [
            {"move": "stay_quiet", "when": "Use when evidence is weak, timing is bad, or the gate fails."},
            {"move": "send_operator_note", "when": "Use when one named task has clear evidence and a specific next action."},
            {"move": "repair_task_shape", "when": "Use when a sticky task is vague or bundled."},
            {"move": "ask_approval", "when": "Use before external, destructive, financial, public, or bulk actions."},
        ],
        "decision": {
            "best_move": best_move,
            "reason": gate.get("reason") if not approval.get("required") else approval.get("reason"),
            "rejected_options": [
                {"option": "send_full_daily_brief", "reason": "Too broad when one move is available."},
                {"option": "unbounded_agent_action", "reason": "Violates autonomy and approval guardrails."},
            ],
        },
        "one_move": one_move,
        "tool_plan": tool_plan,
        "approval": approval,
        "internal_council": council,
        "self_audit": self_audit,
        "telegram_message": telegram_message,
        "nudge_quality_gate": gate,
        "stay_quiet": {
            "reason": gate.get("reason") or "No evidence-backed interruption is justified.",
            "next_check_minutes": gate.get("next_check_minutes") or 90,
        } if best_move == "stay_quiet" else None,
        "evaluation_plan": {
            "check_after_minutes": (brief.get("next_check") or {}).get("minutes") or 90,
            "success_conditions": ["task_completed", "task_rescheduled", "blocker_added", "task_repaired", "user_replied_positive"],
            "failure_conditions": ["ignored", "user_replied_negative", "similar_nudge_repeated", "task_still_vague"],
        },
        "memory_updates": [
            {
                "type": "cycle",
                "claim": "AGI operator cycle ran with evidence, one-move decision, tool plan, approval gate, and self-audit.",
                "confidence": 0.8,
                "evidence_count": len(beliefs),
            }
        ],
        "constitution": [
            "Protect attention.",
            "Reduce noise.",
            "Prefer evidence over vibes.",
            "Prefer one next action over many suggestions.",
            "Never nag without context.",
            "Never hide uncertainty.",
            "Never take risky actions without approval.",
            "Improve systems, not just reminders.",
        ],
    }
    state["last_agi_operator_cycle"] = {
        "cycle_id": cycle["cycle_id"],
        "timestamp": cycle["timestamp"],
        "mode": cycle["mode"],
        "decision": cycle["decision"],
        "one_move": cycle["one_move"],
        "approval": cycle["approval"],
    }
    memories = list(state.get("operator_memories") or [])
    for update in cycle["memory_updates"]:
        memories.append({**update, "last_confirmed": now.isoformat()})
    state["operator_memories"] = memories[-120:]
    _operator_write_state(state)
    _append_jsonl(OPERATOR_BRIEF_LOG_PATH, {"ts": now.isoformat(), "action": "agi_operator_cycle", "cycle_id": cycle["cycle_id"], "decision": cycle["decision"], "one_move": cycle["one_move"]})
    if should_act and bool(args.get("send_telegram", False)):
        _focus_guard_send_telegram_message(telegram_message)
        cycle["sent"] = True
    else:
        cycle["sent"] = False
    return cycle


def _execute_clickup(payload: Dict[str, Any]) -> Dict[str, Any]:
    action = payload.get("action")
    with _http_client() as client:
        if action == "create_task":
            list_id = str(payload.get("list_id") or _env("CLICKUP_DEFAULT_LIST_ID") or "").strip()
            if not list_id:
                raise ValueError("list_id or CLICKUP_DEFAULT_LIST_ID is required")
            body = {
                k: v
                for k, v in payload.items()
                if k
                in {
                    "name",
                    "description",
                    "markdown_description",
                    "assignees",
                    "tags",
                    "status",
                    "priority",
                    "due_date",
                    "time_estimate",
                    "start_date",
                    "notify_all",
                }
                and v not in (None, "", [])
            }
            resp = client.post(f"{CLICKUP_BASE}/list/{list_id}/task", headers=_clickup_headers(), json=body)
            resp.raise_for_status()
            return {"success": True, "action": action, "task": resp.json()}
        if action == "update_task":
            task_id = str(payload.get("task_id") or "").strip()
            if not task_id:
                raise ValueError("task_id is required")
            body = {
                k: v
                for k, v in payload.items()
                if k
                in {
                    "name",
                    "description",
                    "markdown_description",
                    "status",
                    "priority",
                    "due_date",
                    "time_estimate",
                    "assignees",
                    "archived",
                }
                and v not in (None, "", [])
            }
            resp = client.put(f"{CLICKUP_BASE}/task/{task_id}", headers=_clickup_headers(), json=body)
            resp.raise_for_status()
            return {"success": True, "action": action, "task": resp.json()}
    raise ValueError(f"Unsupported ClickUp approval action: {action}")


def _execute_twilio(payload: Dict[str, Any]) -> Dict[str, Any]:
    action = payload.get("action")
    sid, token, from_number = _twilio_auth()
    with _http_client() as client:
        if action == "send_sms":
            to = str(payload.get("to") or "").strip()
            body_text = str(payload.get("body") or "").strip()
            if not to or not body_text:
                raise ValueError("to and body are required")
            resp = client.post(
                f"{TWILIO_BASE}/{sid}/Messages.json",
                auth=(sid, token),
                data={"From": from_number, "To": to, "Body": body_text},
            )
            resp.raise_for_status()
            data = resp.json()
            return {"success": True, "action": action, "sid": data.get("sid"), "status": data.get("status"), "to": to}
    raise ValueError(f"Unsupported Twilio approval action: {action}")


def _execute_pending(item: Dict[str, Any]) -> Dict[str, Any]:
    tool_name = item.get("tool")
    payload = dict(item.get("payload") or {})
    if tool_name == "personal_todoist":
        return _execute_todoist(payload)
    if tool_name == "personal_clickup":
        return _execute_clickup(payload)
    if tool_name == "personal_twilio":
        return _execute_twilio(payload)
    if tool_name == "personal_runtime":
        action = str(payload.get("action") or "").strip()
        if action == "self_improve_apply":
            return _runtime_self_improve_run()
        if action == "self_improve_pipeline_apply":
            pipeline = dict(payload.get("pipeline") or {})
            state = _self_improve_pipelines_read()
            pipelines = list(state.get("pipelines") or [])
            approved = {
                **pipeline,
                "approved_at": datetime.now(timezone.utc).isoformat(),
                "current_stage": "approval",
                "next_stage": "patch",
                "status": "approved_ready_for_patch",
            }
            _self_improve_pipeline_write_artifacts(approved, stage_label="approved")
            replaced = False
            for idx, existing in enumerate(pipelines):
                if str(existing.get("pipeline_id") or "") == str(pipeline.get("pipeline_id") or ""):
                    pipelines[idx] = approved
                    replaced = True
                    break
            if not replaced:
                pipelines.append(approved)
            state["pipelines"] = pipelines[-100:]
            _self_improve_pipelines_write(state)
            return {"success": True, "action": action, "pipeline": approved, "summary": approved.get("summary")}
        if action == "calendar_event_commit":
            draft = dict(payload.get("draft") or {})
            state = _calendar_read_state()
            commits = list(state.get("commits") or [])
            commit = {
                **draft,
                "commit_id": f"calendar_commit_{uuid.uuid4().hex[:10]}",
                "status": "browser_handoff_ready",
                "approved_at": datetime.now(timezone.utc).isoformat(),
            }
            commits.append(commit)
            state["commits"] = commits[-100:]
            _calendar_write_state(state)
            return {"success": True, "action": action, "commit": commit, "summary": f"Calendar browser handoff ready for {draft.get('title')}"}
        if action == "todoist_repair_apply":
            return _runtime_todoist_repair_apply(payload)
        if action == "approval_bundle_apply":
            return _runtime_approval_bundle_apply(payload)
        raise ValueError(f"Unsupported runtime approval action: {action}")
    raise ValueError(f"Unsupported approval target: {tool_name}")


_SEMANTIC_GROUPS = {
    "exercise": ["exercise", "workout", "gym", "fitness", "cardio", "lift", "lifting", "run", "running", "training", "walk", "walking"],
    "workout": ["exercise", "workout", "gym", "fitness", "cardio", "lift", "lifting", "run", "running", "training", "walk", "walking"],
    "task": ["task", "todo", "reminder", "item", "follow-up", "followup"],
    "urgent": ["urgent", "critical", "asap", "blocker", "important", "priority"],
    "text": ["text", "sms", "message", "twilio", "phone"],
}


def _expand_query_terms(query: str) -> List[str]:
    q = (query or "").strip().lower()
    if not q:
        return []
    terms = [q]
    for key, synonyms in _SEMANTIC_GROUPS.items():
        if q == key or q in synonyms:
            for synonym in synonyms:
                if synonym not in terms:
                    terms.append(synonym)
    return terms


def _score_task_for_terms(task: Dict[str, Any], terms: List[str]) -> int:
    content = (task.get("content") or "").lower()
    description = (task.get("description") or "").lower()
    labels = " ".join(task.get("labels") or []).lower()
    score = 0
    for term in terms:
        if term in content:
            score += 10 if term == terms[0] else 8
        if term in labels:
            score += 6
        if term in description:
            score += 3 if term == terms[0] else 2
    if task.get("parent_id"):
        score -= 1
    return score


def _normalize_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(_normalize_text(item) for item in value)
    if isinstance(value, dict):
        return " ".join(f"{k} {_normalize_text(v)}" for k, v in value.items())
    return str(value).strip().lower()


def _rank_records(query: str, records: List[Dict[str, Any]], field_getter) -> List[Dict[str, Any]]:
    normalized_query = (query or "").strip().lower()
    terms = _expand_query_terms(normalized_query) if normalized_query else []
    ranked: List[Dict[str, Any]] = []
    for record in records:
        fields = field_getter(record)
        title = _normalize_text(fields.get("title"))
        body = _normalize_text(fields.get("body"))
        tags = _normalize_text(fields.get("tags"))
        state = _normalize_text(fields.get("state"))
        recency_hint = _normalize_text(fields.get("recency_hint"))
        why_matched: List[str] = []
        score = 0
        for idx, term in enumerate(terms):
            if not term:
                continue
            term_weight = 2 if idx == 0 else 1
            if term in title:
                score += 12 * term_weight
                why_matched.append(f"title:{term}")
            if term in tags:
                score += 8 * term_weight
                why_matched.append(f"tags:{term}")
            if term in body:
                score += 5 * term_weight
                why_matched.append(f"body:{term}")
            if term in state:
                score += 3 * term_weight
                why_matched.append(f"state:{term}")
        if normalized_query and normalized_query in recency_hint:
            score += 2
            why_matched.append(f"recency:{normalized_query}")
        if score > 0:
            ranked.append(
                {
                    "score": score,
                    "why_matched": why_matched,
                    "record": record,
                }
            )
    ranked.sort(key=lambda item: (-item["score"], _normalize_text(item["record"])))
    return ranked


def _match_mode_for_query(query: str) -> str:
    terms = _expand_query_terms(query)
    if not query:
        return "all"
    return "semantic" if terms != [query] else "literal"


def _load_recent_events(limit: int = 200) -> List[Dict[str, Any]]:
    if not EVENTS_PATH.exists():
        return []
    try:
        return [json.loads(line) for line in EVENTS_PATH.read_text(encoding="utf-8").splitlines()[-limit:] if line.strip()]
    except Exception:
        return []


def _summarize_event_match(query: str, event: Dict[str, Any], why_matched: List[str]) -> str:
    event_type = str(event.get("type") or "event")
    action = str(event.get("action") or "").strip()
    query_text = str(event.get("query") or "").strip()
    details = []
    if action:
        details.append(f"action={action}")
    if query_text:
        details.append(f"query={query_text}")
    if event.get("count") is not None:
        details.append(f"count={event.get('count')}")
    if event.get("match_mode"):
        details.append(f"match_mode={event.get('match_mode')}")
    reason_text = ", ".join(why_matched[:3]) if why_matched else "ranked event match"
    detail_text = "; ".join(details)
    if detail_text:
        return f"Best match for '{query}' was {event_type} ({detail_text}) because it matched on {reason_text}."
    return f"Best match for '{query}' was {event_type} because it matched on {reason_text}."


def _compact_record_match(item: Dict[str, Any], title_key: str, body_key: str) -> Dict[str, Any]:
    record = item["record"]
    return {
        "title": record.get(title_key, ""),
        "preview": (record.get(body_key, "") or "")[:160],
        "why_matched": item["why_matched"],
        "score": item["score"],
    }


def _summarize_record_matches(query: str, ranked: List[Dict[str, Any]], title_key: str) -> str:
    if not ranked:
        return f"No matches found for '{query}'."
    titles = [str(item["record"].get(title_key) or "").strip() for item in ranked[:3] if str(item["record"].get(title_key) or "").strip()]
    joined = ", ".join(titles)
    if len(ranked) == 1:
        return f"Best match for '{query}' was {joined}."
    return f"Closest matches for '{query}' were {joined}."


def _summarize_event_results(query: str, ranked: List[Dict[str, Any]]) -> str:
    if not ranked:
        return f"No recent events matched '{query}'."
    top = ranked[0]["record"]
    event_type = str(top.get("type") or "event")
    return f"Found {len(ranked)} recent event match(es) for '{query}'. Best match was {event_type}."


def _format_forecast(daily: Dict[str, Any], idx: int, label: str) -> Dict[str, Any]:
    return {
        "label": label,
        "date": daily.get("time", [None])[idx],
        "temperature_max_c": daily.get("temperature_2m_max", [None])[idx],
        "temperature_min_c": daily.get("temperature_2m_min", [None])[idx],
        "precipitation_probability_max": daily.get("precipitation_probability_max", [None])[idx],
        "weather_code": daily.get("weather_code", [None])[idx],
        "wind_speed_10m_max_kmh": daily.get("wind_speed_10m_max", [None])[idx],
    }


def handle_weather(args: Dict[str, Any], **_: Any) -> str:
    location = str(args.get("location") or "").strip()
    if not location:
        return _tool_error("location is required")
    try:
        with _http_client() as client:
            geo = client.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": location, "count": 1, "language": "en", "format": "json"},
            )
            geo.raise_for_status()
            results = (geo.json() or {}).get("results") or []
            if not results:
                return _tool_error(f"No location found for '{location}'")
            hit = results[0]
            lat = hit.get("latitude")
            lon = hit.get("longitude")
            tz = hit.get("timezone") or "auto"
            weather = client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "timezone": tz,
                    "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
                    "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,wind_speed_10m_max",
                    "forecast_days": 3,
                },
            )
            weather.raise_for_status()
            payload = weather.json()
        _append_event("weather_lookup", {"location": location})
        return _tool_result(
            success=True,
            action="forecast",
            location={
                "name": hit.get("name"),
                "admin1": hit.get("admin1"),
                "country": hit.get("country"),
                "timezone": tz,
                "latitude": lat,
                "longitude": lon,
            },
            current=payload.get("current", {}),
            forecast=[
                _format_forecast(payload.get("daily", {}), 0, "today"),
                _format_forecast(payload.get("daily", {}), 1, "tomorrow"),
                _format_forecast(payload.get("daily", {}), 2, "day_after_tomorrow"),
            ],
        )
    except Exception as exc:
        return _tool_error(f"Weather lookup failed: {exc}")


def handle_focus_guard(args: Dict[str, Any], **_: Any) -> str:
    action = str(args.get("action") or "status").strip().lower()
    try:
        if action == "run":
            result = _canonical_focus_guard_result(_focus_guard_run_once(filter=args.get("filter")))
            return _tool_result(success=True, action=action, summary=_summarize_focus_guard_result(result, source="run"), **result)
        if action == "status":
            state = _focus_guard_read_state()
            if not state:
                result = _canonical_focus_guard_result({
                    "status": "unknown",
                    "task_count": 0,
                    "most_important_task": None,
                    "suspicious_task_ids": [],
                    "notified_suspicious_task_ids": [],
                    "processed_suspicious_task_ids": [],
                    "generated_at": None,
                })
                summary = "No saved Focus Guard state yet."
            else:
                result = _focus_guard_result_from_state(state)
                summary = _summarize_focus_guard_result(result, source="status")
            return _tool_result(success=True, action=action, summary=summary, **result)
        return _tool_error(f"Unsupported Focus Guard action: {action}")
    except Exception as exc:
        return _tool_error(f"Focus Guard request failed: {exc}")


def handle_runtime(args: Dict[str, Any], **_: Any) -> str:
    action = str(args.get("action") or "status").strip().lower()
    try:
        if action == "status":
            service = _runtime_service_status()
            provider_chain = _runtime_provider_chain()
            incidents = _runtime_recent_incidents(limit=10)
            return _tool_result(
                success=True,
                action=action,
                service=service,
                provider_chain=provider_chain,
                recent_incidents=incidents,
                summary=_runtime_summary(service, incidents),
            )
        if action == "live_watch_status":
            status = _runtime_live_watch_status()
            return _tool_result(success=True, action=action, **status)
        if action == "presence_status":
            status = _runtime_presence_status()
            return _tool_result(success=True, action=action, **status)
        if action == "ensure_todoist_mcp":
            return _tool_result(action=action, **_runtime_ensure_todoist_mcp())
        if action == "mood_status":
            status = _mood_router_status()
            return _tool_result(success=True, action=action, **status)
        if action == "mood_route":
            mood = _mood_router_route(args)
            return _tool_result(success=True, action=action, mood=mood, model_status=_mood_router_model_status())
        if action == "live_watch":
            result = _runtime_live_watch_run(filter=args.get("filter"), always_on=bool(args.get("always_on")))
            return _tool_result(action=action, **result)
        if action == "self_improve":
            result = _runtime_self_improve_run()
            return _tool_result(action=action, **result)
        if action == "self_improve_report":
            result = _runtime_self_improve_report(
                create_approval=bool(args.get("create_approval", True)),
                send_telegram=bool(args.get("send_telegram", False)),
                force_send=bool(args.get("force_send", False)),
            )
            return _tool_result(result)
        if action == "self_improve_pipeline":
            result = _runtime_self_improve_pipeline(args)
            return _tool_result(result)
        if action == "calendar_status":
            result = _runtime_calendar_status(args)
            return _tool_result(result)
        if action == "calendar_event":
            result = _runtime_calendar_event(args)
            return _tool_result(result)
        if action == "operator_brief":
            result = _operator_brief(args)
            return _tool_result(result)
        if action == "agi_operator_cycle":
            result = _agi_operator_cycle(args)
            return _tool_result(result)
        if action == "weekly_review":
            result = _operator_weekly_review(args)
            return _tool_result(result)
        if action == "todoist_lint_report":
            result = _runtime_todoist_lint_report(args)
            return _tool_result(result)
        if action == "common_sense_decision":
            result = _runtime_common_sense_decision(args)
            return _tool_result(result)
        if action == "event_log_state":
            result = _runtime_event_log_state(args)
            return _tool_result(result)
        if action == "context_budget_audit":
            result = _runtime_context_budget_audit(args)
            return _tool_result(result)
        if action == "context_contributors_report":
            result = _runtime_context_contributors_report(args)
            return _tool_result(result)
        if action == "profile_prune_plan":
            result = _runtime_profile_prune_plan(args)
            return _tool_result(result)
        if action == "secret_inventory":
            result = _runtime_secret_inventory(args)
            return _tool_result(result)
        if action == "no_agent_cron_plan":
            result = _runtime_no_agent_cron_plan(args)
            return _tool_result(result)
        if action == "tool_router_status":
            result = _runtime_tool_router_status(args)
            return _tool_result(result)
        if action == "tool_router_simulate":
            result = _runtime_tool_router_simulate(args)
            return _tool_result(result)
        if action == "memory_tier":
            result = _runtime_memory_tier(args)
            return _tool_result(result)
        if action == "isolation_profile_plan":
            result = _runtime_isolation_profile_plan(args)
            return _tool_result(result)
        if action == "intention_gate":
            result = _runtime_intention_gate(args)
            return _tool_result(result)
        if action == "orchestration_job":
            result = _runtime_orchestration_job(args)
            return _tool_result(result)
        if action == "memory_console":
            result = _runtime_memory_console(args)
            return _tool_result(result)
        if action == "todoist_rule_store":
            result = _runtime_todoist_rule_store(args)
            return _tool_result(result)
        if action == "rollover_preview":
            result = _runtime_rollover_preview(args)
            return _tool_result(result)
        if action == "approval_bundle":
            result = _runtime_approval_bundle(args)
            return _tool_result(result)
        if action == "self_improve_proposals":
            result = _runtime_self_improve_proposals(args)
            return _tool_result(result)
        if action == "external_systems_status":
            result = _runtime_external_systems_status(args)
            return _tool_result(result)
        if action == "hermes_capabilities_dossier":
            result = _runtime_hermes_capabilities_dossier(args)
            return _tool_result(result)
        if action == "hermes_system_audit":
            result = _runtime_hermes_system_audit(args)
            return _tool_result(result)
        if action == "trace_status":
            result = _runtime_trace_status(args)
            return _tool_result(result)
        if action == "trace_event":
            result = _runtime_trace_event(args)
            return _tool_result(result)
        if action == "eval_suite_export":
            result = _runtime_eval_suite_export(args)
            return _tool_result(result)
        if action == "operating_snapshot":
            result = _operating_snapshot(args)
            return _tool_result(result)
        if action == "operating_delta":
            result = _operating_delta(args)
            return _tool_result(result)
        if action == "sensor_health":
            now_ts = int(time.time())
            operator_state = _operator_read_state()
            heartbeats = operator_state.get("last_sensor_heartbeats", {})
            sensors = {}
            for name, last_ts in heartbeats.items():
                age = now_ts - int(last_ts)
                sensors[name] = {
                    "last_seen_seconds_ago": age,
                    "status": "healthy" if age < 600 else ("stale" if age < 1800 else "dead"),
                }
            presence = _read_json(PRESENCE_STATE_PATH, {})
            return _tool_result(
                success=True,
                action=action,
                sensors=sensors,
                day_phase=operator_state.get("day_phase"),
                presence_state=presence.get("state"),
                presence_confidence=presence.get("confidence"),
                active_sprint=operator_state.get("active_sprint"),
                nudge_fatigue=operator_state.get("nudge_fatigue"),
            )
        if action == "event_ingest":
            result = _runtime_event_ingest(args)
            return _tool_result(success=True, action=action, **result)
        if action == "incidents":
            incidents = _runtime_recent_incidents(limit=int(args.get("limit") or 20))
            return _tool_result(success=True, action=action, count=len(incidents), incidents=incidents)
        if action == "provider_chain":
            provider_chain = _runtime_provider_chain()
            return _tool_result(success=True, action=action, provider_chain=provider_chain)
        if action == "upstream_status":
            status = _runtime_upstream_status(
                hours=int(args.get("hours") or 24),
                repo_path=Path(str(args.get("repo_path"))) if args.get("repo_path") else None,
            )
            return _tool_result(success=True, action=action, **status)
        if action == "watch_upstream":
            status = _runtime_upstream_status(
                hours=int(args.get("hours") or 24),
                repo_path=Path(str(args.get("repo_path"))) if args.get("repo_path") else None,
            )
            behind = (status.get("local") or {}).get("behind")
            should_send = int(status.get("recent_commit_count") or 0) > 0 or (behind is not None and int(behind) > 0)
            if not should_send and bool(args.get("quiet_if_current", True)):
                return _tool_result(success=True, action=action, sent=False, reason="current", **status)
            if not bool(args.get("send_telegram", True)):
                return _tool_result(success=True, action=action, sent=False, reason="notification_disabled", **status)
            message = _runtime_upstream_telegram_message(status)
            _focus_guard_send_telegram_message(message)
            return _tool_result(success=True, action=action, sent=True, message=message, **status)
        return _tool_error(f"Unsupported runtime action: {action}")
    except Exception as exc:
        return _tool_error(f"Runtime debugger request failed: {exc}")


def handle_adaptive_companion(args: Dict[str, Any], **_: Any) -> str:
    action = str(args.get("action") or "status").strip().lower()
    try:
        state = _adaptive_companion_read_state()
        if action == "status":
            return _tool_result(success=True, action=action, state=state)
        if action == "run":
            now_hour = _adaptive_companion_now_local_hour()
            if not _telegram_messages_allowed_now(now_hour):
                return _tool_result(success=True, action=action, sent=False, reason="outside_hours")
            now = datetime.now(timezone.utc)
            state["mood_router"] = _mood_router_status()
            focus_state = _focus_guard_read_state()
            trigger = _adaptive_companion_detect_trigger(
                user_text=_adaptive_companion_recent_user_text(),
                focus_state=focus_state,
                state=state,
            )
            if trigger["kind"] == "none":
                return _tool_result(success=True, action=action, sent=False, reason="no_trigger")
            inferred_state = _adaptive_companion_infer_user_state(trigger=trigger, now_hour=now_hour)
            pattern = _adaptive_companion_classify_pattern(
                trigger=trigger,
                inferred_state=inferred_state,
                state=state,
            )
            state = _adaptive_companion_refresh_insight_lenses(
                state=state,
                trigger=trigger,
                pattern=pattern,
                focus_state=focus_state,
                now_hour=now_hour,
            )
            presence = _runtime_presence_status(now=now)
            if presence.get("configured") and not bool(presence.get("can_proactively_message")):
                return _tool_result(
                    success=True,
                    action=action,
                    sent=False,
                    reason="presence_not_confident",
                    presence=presence,
                    state=state,
                    trigger=trigger,
                    pattern=pattern,
                )
            suppression = _adaptive_companion_should_suppress(
                state=state,
                trigger=trigger,
                pattern=pattern,
                now=now,
            )
            if suppression:
                return _tool_result(
                    success=True,
                    action=action,
                    sent=False,
                    state=state,
                    trigger=trigger,
                    pattern=pattern,
                    **suppression,
                )
            budget_suppression = _nudge_budget_check(category="pressure", now=now)
            if budget_suppression:
                return _tool_result(
                    success=True,
                    action=action,
                    sent=False,
                    state=state,
                    trigger=trigger,
                    pattern=pattern,
                    **budget_suppression,
                )
            strategy = _adaptive_companion_select_response_strategy(
                trigger=trigger,
                inferred_state=inferred_state,
                state=state,
                now_hour=now_hour,
            )
            family = _adaptive_companion_select_intervention_family(
                pattern=pattern,
                strategy=strategy,
                state=state,
            )
            message = _adaptive_companion_render_message(
                trigger=trigger,
                strategy=strategy,
                pattern=pattern,
                family=family,
                state=state,
            )
            style = _adaptive_companion_select_style(
                trigger=trigger,
                state=state,
                now_hour=now_hour,
            )
            # Read mood router status and build recommendation
            mood_status = _mood_router_status()
            local_now = datetime.now(timezone.utc).astimezone(_runtime_local_tz())
            mood_rec = _build_mood_recommendation(mood_status, local_now)

            # Escape base message to prevent Telegram HTML parse errors on raw task characters
            escaped_message = _escape_html(message)
            if mood_rec:
                escaped_message += mood_rec

            _safe_send_telegram_message(escaped_message, parse_mode="HTML")
            nudge_budget = _nudge_budget_record_sent(
                category="pressure",
                now=now,
                task_label=str(trigger.get("task_label") or ""),
                message=message,
            )
            state["mode"] = "pressure"
            state["last_pressure_style"] = style
            state["last_pattern_label"] = pattern.get("label")
            state["last_intervention_family"] = family
            state["last_intervention_at"] = now.isoformat()
            recent_interventions = list(state.get("recent_interventions") or [])
            # Fetch active task IDs to support Same Observation Suppression on subsequent runs
            try:
                current_active_tasks = _focus_guard_read_todoist_tasks()
                active_task_ids = [str(t.get("id")) for t in current_active_tasks if t.get("id")]
            except Exception:
                active_task_ids = []

            recent_interventions.append(
                {
                    "trigger": trigger["kind"],
                    "style": style,
                    "pattern": pattern,
                    "intervention_family": family,
                    "task_label": trigger.get("task_label"),
                    "task_id": trigger.get("task_id") or ((focus_state.get("most_important_task") or {}).get("id")),
                    "side_task_label": trigger.get("side_task_label"),
                    "side_task_id": trigger.get("side_task_id"),
                    "active_task_ids": active_task_ids,
                    "strategy": strategy,
                    "inferred_state": inferred_state,
                    "message": message,
                    "sent_at": now.isoformat(),
                }
            )
            state["recent_interventions"] = recent_interventions[-24:]
            state = _adaptive_companion_update_response_learning(
                state=state,
                trigger_kind=str(trigger.get("kind") or "none"),
                strategy=strategy,
                outcome="corrected",
            )
            state = _adaptive_companion_update_learning(
                state=state,
                trigger_kind=str(trigger.get("kind") or "none"),
                style=style,
                outcome="corrected",
            )
            state = _adaptive_companion_update_family_learning(
                state=state,
                pattern_label=str(pattern.get("label") or "unknown"),
                family=family,
                outcome="corrected",
            )
            _adaptive_companion_write_state(state)
            return _tool_result(
                success=True,
                action=action,
                sent=True,
                style=style,
                trigger=trigger,
                pattern=pattern,
                intervention_family=family,
                inferred_state=inferred_state,
                strategy=strategy,
                presence=presence,
                nudge_budget=nudge_budget,
                message=message,
                state=state,
            )
        if action == "explain":
            recent = list(state.get("recent_interventions") or [])
            latest = recent[-1] if recent else None
            return _tool_result(
                success=True,
                action=action,
                latest_intervention=latest,
                style_history=list(state.get("style_history") or []),
                pattern_memory=dict(state.get("pattern_memory") or {}),
            )
        return _tool_error(f"Unsupported adaptive companion action: {action}")
    except Exception as exc:
        return _tool_error(f"Adaptive companion request failed: {exc}")


def handle_todoist(args: Dict[str, Any], **_: Any) -> str:
    action = str(args.get("action") or "list_tasks").strip().lower()
    try:
        if action == "focus_guard_run":
            result = _canonical_focus_guard_result(_focus_guard_run_once(filter=args.get("filter")))
            return _tool_result(
                success=True,
                action=action,
                summary=_summarize_focus_guard_result(result, source="run"),
                connector="native",
                connector_reason="focus_guard_requires_native_shape",
                **result,
            )
        native_result: Optional[Dict[str, Any]] = None
        if action == "status":
            native_result = _todoist_native_call(args)
            native_result["connector"] = "native_api"
            native_result["connector_mode"] = _todoist_connector_mode()
            native_result["mcp_primary_configured"] = _todoist_connector_mode() == "mcp_primary"
            native_result["mcp_required"] = _env("TODOIST_MCP_REQUIRED").strip().lower() in {"1", "true", "yes", "on"}
            native_result["mcp_available"] = (
                _todoist_mcp_available()
                if native_result["mcp_primary_configured"] or native_result["mcp_required"]
                else None
            )
            native_result["mcp_probe_skipped"] = native_result["mcp_available"] is None
            return _tool_result(native_result)
        if action == "intelligence":
            return _tool_result(_todoist_intelligence(args))
        if _todoist_connector_mode() == "mcp_primary" and action in {"list_tasks", "search_tasks", "add_task", "close_task", "reopen_task"}:
            try:
                mcp_result = _todoist_mcp_call(action, args)
                mcp_result["connector"] = "mcp"
                mcp_result["fallback_used"] = False
                return _tool_result(mcp_result)
            except Exception as exc:
                native_result = _todoist_native_call(args)
                native_result["connector"] = "native_api"
                native_result["fallback_used"] = True
                native_result["primary_error"] = str(exc)
                return _tool_result(native_result)
        native_result = _todoist_native_call(args)
        native_result["connector"] = "native_api"
        native_result["fallback_used"] = False
        return _tool_result(native_result)
    except Exception as exc:
        return _tool_error(f"Todoist request failed: {exc}")


def handle_clickup(args: Dict[str, Any], **_: Any) -> str:
    action = str(args.get("action") or "status").strip().lower()
    try:
        with _http_client() as client:
            if action == "status":
                token = _env("CLICKUP_API_TOKEN")
                boundary = None
                boundary_error = None
                if token:
                    try:
                        boundary = _resolve_clickup_boundary(client)
                    except Exception as exc:
                        boundary_error = str(exc)
                return _tool_result(
                    success=True,
                    configured=bool(token),
                    token_masked=_mask(token),
                    default_list_id=_env("CLICKUP_DEFAULT_LIST_ID"),
                    allowed_space_id=_env("CLICKUP_ALLOWED_SPACE_ID"),
                    allowed_folder_name=_clickup_allowed_folder_name(),
                    boundary=_public_clickup_boundary(boundary),
                    boundary_error=boundary_error,
                )
            if action == "list_tasks":
                boundary = _resolve_clickup_boundary(client)
                requested_list_id = str(args.get("list_id") or _env("CLICKUP_DEFAULT_LIST_ID") or "").strip()
                if requested_list_id and requested_list_id not in boundary["list_ids"]:
                    return _tool_error("Requested list is outside the allowed ClickUp folder")
                params = {"archived": "false", "include_closed": str(bool(args.get("include_closed", False))).lower()}
                if args.get("subtasks") is not None:
                    params["subtasks"] = str(bool(args.get("subtasks"))).lower()
                target_lists = [item for item in boundary["lists"] if not requested_list_id or item["id"] == requested_list_id]
                tasks: List[Dict[str, Any]] = []
                for allowed in target_lists:
                    resp = client.get(f"{CLICKUP_BASE}/list/{allowed['id']}/task", headers=_clickup_headers(), params=params)
                    resp.raise_for_status()
                    tasks.extend((resp.json() or {}).get("tasks") or [])
                query = str(args.get("query") or "").strip().lower()
                match_mode = "all"
                if query:
                    ranked = _rank_records(
                        query=query,
                        records=tasks,
                        field_getter=lambda task: {
                            "title": task.get("name", ""),
                            "body": task.get("description", ""),
                            "tags": [tag.get("name", "") for tag in (task.get("tags") or [])],
                            "state": ((task.get("status") or {}).get("status")) or "",
                            "recency_hint": f"{task.get('date_created', '')} {task.get('date_updated', '')}",
                        },
                    )
                    tasks = [{**item["record"], "_why_matched": item["why_matched"], "_score": item["score"]} for item in ranked]
                    match_mode = _match_mode_for_query(query)
                    top_matches = [_compact_record_match(item, "name", "description") for item in ranked[:5]]
                    summary = _summarize_record_matches(query, ranked, "name")
                else:
                    top_matches = []
                    summary = f"Found {len(tasks)} ClickUp task(s) in allowed folder {boundary['folder']['name']}."
                _append_event("clickup_read", {"action": action, "count": len(tasks), "list_id": requested_list_id, "query": query, "match_mode": match_mode, "folder_id": boundary["folder"]["id"]})
                return _tool_result(success=True, action=action, count=len(tasks), list_id=requested_list_id, match_mode=match_mode, summary=summary, top_matches=top_matches, tasks=tasks, boundary=_public_clickup_boundary(boundary))
            if action == "get_task":
                boundary = _resolve_clickup_boundary(client)
                task_id = str(args.get("task_id") or "").strip()
                if not task_id:
                    return _tool_error("task_id is required")
                resp = client.get(f"{CLICKUP_BASE}/task/{task_id}", headers=_clickup_headers())
                resp.raise_for_status()
                task = resp.json() or {}
                task_list_id = str(((task.get("list") or {}).get("id")) or "").strip()
                if task_list_id not in boundary["list_ids"]:
                    return _tool_error("Requested task is outside the allowed ClickUp folder")
                _append_event("clickup_read", {"action": action, "task_id": task_id})
                return _tool_result(success=True, action=action, task=task, boundary=_public_clickup_boundary(boundary))
            if action == "create_task":
                boundary = _resolve_clickup_boundary(client)
                name = str(args.get("name") or "").strip()
                if not name:
                    return _tool_error("name is required for create_task")
                requested_list_id = str(args.get("list_id") or _env("CLICKUP_DEFAULT_LIST_ID") or "").strip()
                if requested_list_id and requested_list_id not in boundary["list_ids"]:
                    return _tool_error("Requested list is outside the allowed ClickUp folder")
                return _create_approval(
                    tool_name="personal_clickup",
                    action=action,
                    summary=f"create ClickUp task '{name[:80]}'",
                    reason="This creates a real task in your ClickUp workspace.",
                    benefit="Hermes can capture work immediately instead of making you re-enter it later.",
                    payload=args,
                )
            if action == "update_task":
                boundary = _resolve_clickup_boundary(client)
                task_id = str(args.get("task_id") or "").strip()
                if not task_id:
                    return _tool_error("task_id is required")
                resp = client.get(f"{CLICKUP_BASE}/task/{task_id}", headers=_clickup_headers())
                resp.raise_for_status()
                task = resp.json() or {}
                task_list_id = str(((task.get("list") or {}).get("id")) or "").strip()
                if task_list_id not in boundary["list_ids"]:
                    return _tool_error("Requested task is outside the allowed ClickUp folder")
                return _create_approval(
                    tool_name="personal_clickup",
                    action=action,
                    summary=f"update ClickUp task {task_id}",
                    reason="This changes a real ClickUp task and can affect workflow state.",
                    benefit="Hermes can keep project state current without you switching contexts.",
                    payload=args,
                )
            return _tool_error(f"Unsupported ClickUp action: {action}")
    except Exception as exc:
        return _tool_error(f"ClickUp request failed: {exc}")


def handle_twilio(args: Dict[str, Any], **_: Any) -> str:
    action = str(args.get("action") or "status").strip().lower()
    try:
        if action == "status":
            sid = _env_first("PERSONAL_TWILIO_ACCOUNT_SID", "TWILIO_ACCOUNT_SID")
            token = _env_first("PERSONAL_TWILIO_AUTH_TOKEN", "TWILIO_AUTH_TOKEN")
            from_number = _env_first("PERSONAL_TWILIO_PHONE_NUMBER", "TWILIO_PHONE_NUMBER")
            return _tool_result(
                success=True,
                configured=bool(sid and token and from_number),
                account_sid_masked=_mask(sid),
                from_number=from_number,
            )
        if action == "send_sms":
            to = str(args.get("to") or "").strip()
            body_text = str(args.get("body") or "").strip()
            if not to or not body_text:
                return _tool_error("to and body are required for send_sms")
            return _create_approval(
                tool_name="personal_twilio",
                action=action,
                summary=f"send SMS to {to}",
                reason="This sends a real outbound text message to another phone number.",
                benefit="Hermes can reach you or someone else immediately when speed matters.",
                payload=args,
            )
        return _tool_error(f"Unsupported Twilio action: {action}")
    except Exception as exc:
        return _tool_error(f"Twilio request failed: {exc}")


def handle_security(args: Dict[str, Any], **_: Any) -> str:
    action = str(args.get("action") or "status").strip().lower()
    approvals = _load_approvals()
    if action == "status":
        recent = _load_recent_events(limit=10)
        return _tool_result(
            success=True,
            pending_count=len(approvals.get("pending", {})),
            pending=list(approvals.get("pending", {}).values()),
            recent_events=recent,
            approvals_path=str(APPROVALS_PATH),
            events_path=str(EVENTS_PATH),
        )
    if action == "search_events":
        query = str(args.get("query") or "").strip().lower()
        if not query:
            return _tool_error("query is required")
        ranked = _rank_records(
            query=query,
            records=_load_recent_events(),
            field_getter=lambda event: {
                "title": event.get("type", ""),
                "body": event,
                "tags": [event.get("tool", ""), event.get("action", ""), event.get("surface", "")],
                "state": event.get("choice", "") or event.get("status", ""),
                "recency_hint": str(event.get("ts", "")),
            },
        )
        return _tool_result(
            success=True,
            action=action,
            count=len(ranked),
            match_mode=_match_mode_for_query(query),
            summary=_summarize_event_results(query, ranked),
            results=[
                {
                    "score": item["score"],
                    "why_matched": item["why_matched"],
                    "event": item["record"],
                }
                for item in ranked[:20]
            ],
        )
    if action == "explain_recent_action":
        query = str(args.get("query") or "").strip().lower()
        if not query:
            return _tool_error("query is required")
        ranked = _rank_records(
            query=query,
            records=_load_recent_events(),
            field_getter=lambda event: {
                "title": event.get("type", ""),
                "body": event,
                "tags": [event.get("tool", ""), event.get("action", ""), event.get("surface", "")],
                "state": event.get("choice", "") or event.get("status", ""),
                "recency_hint": str(event.get("ts", "")),
            },
        )
        if not ranked:
            return _tool_error(f"No recent event matched '{query}'")
        best = ranked[0]
        return _tool_result(
            success=True,
            action=action,
            query=query,
            event=best["record"],
            why_matched=best["why_matched"],
            score=best["score"],
            summary=_summarize_event_match(query, best["record"], best["why_matched"]),
        )
    if action == "list_pending":
        return _tool_result(success=True, pending=list(approvals.get("pending", {}).values()))
    if action == "deny_request":
        request_id = str(args.get("request_id") or "").strip()
        if not request_id:
            return _tool_error("request_id is required")
        pending = _pop_pending(request_id)
        if pending is None:
            return _tool_error(f"No pending request found for {request_id}")
        _append_event("approval_denied", {"request_id": request_id, "tool": pending.get("tool"), "action": pending.get("action")})
        return _tool_result(success=True, denied=True, request_id=request_id)
    if action == "approve_request":
        request_id = str(args.get("request_id") or "").strip()
        if not request_id:
            return _tool_error("request_id is required")
        approvals = _load_approvals()
        pending = approvals.get("pending", {}).get(request_id)
        if pending is None:
            return _tool_error(f"No pending request found for {request_id}")
        try:
            result = _execute_pending(pending)
        except Exception as exc:
            _append_event("approval_execute_failed", {"request_id": request_id, "error": str(exc)})
            return _tool_error(f"Approved request failed during execution: {exc}")
        _pop_pending(request_id)
        _append_event("approval_executed", {"request_id": request_id, "tool": pending.get("tool"), "action": pending.get("action")})
        return _tool_result(success=True, approved=True, request_id=request_id, result=result)
    return _tool_error(f"Unsupported security action: {action}")


def on_pre_approval_request(**kwargs: Any) -> None:
    _append_event(
        "dangerous_command_approval_requested",
        {
            "command": kwargs.get("command", ""),
            "description": kwargs.get("description", ""),
            "pattern_key": kwargs.get("pattern_key", ""),
            "pattern_keys": kwargs.get("pattern_keys", []),
            "session_key": kwargs.get("session_key", ""),
            "surface": kwargs.get("surface", ""),
        },
    )


def on_post_approval_response(**kwargs: Any) -> None:
    _append_event(
        "dangerous_command_approval_resolved",
        {
            "command": kwargs.get("command", ""),
            "description": kwargs.get("description", ""),
            "pattern_key": kwargs.get("pattern_key", ""),
            "pattern_keys": kwargs.get("pattern_keys", []),
            "session_key": kwargs.get("session_key", ""),
            "surface": kwargs.get("surface", ""),
            "choice": kwargs.get("choice", ""),
        },
    )


TODOIST_SCHEMA = {
    "name": "personal_todoist",
    "description": "Native Todoist integration for reading tasks, running Focus Guard, and proposing real Todoist writes through an approval queue.",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["status", "list_tasks", "search_tasks", "focus_guard_run", "add_task", "close_task", "reopen_task", "update_task", "intelligence"]},
            "query": {"type": "string"},
            "filter": {"type": "string"},
            "project_id": {"type": ["string", "integer"]},
            "section_id": {"type": ["string", "integer"]},
            "label": {"type": "string"},
            "task_id": {"type": ["string", "integer"]},
            "content": {"type": "string"},
            "description": {"type": "string"},
            "labels": {"type": "array", "items": {"type": "string"}},
            "priority": {"type": "integer"},
            "due_string": {"type": "string"},
            "due_date": {"type": "string"},
            "due_datetime": {"type": "string"},
            "limit": {"type": "integer"},
            "include_context": {"type": "boolean"}
        },
        "required": ["action"]
    }
}


FOCUS_GUARD_SCHEMA = {
    "name": "personal_focus_guard",
    "description": "Native Focus Guard surface for scheduled runs and local state inspection.",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["run", "status"]},
            "filter": {"type": "string"},
        },
        "required": ["action"],
    },
}


RUNTIME_SCHEMA = {
    "name": "personal_runtime",
    "description": "Native Hermes runtime debugger for gateway status, provider chain, recent incidents, upstream update watch, live personal bot watch cycles, and event-triggered workflows like wake, unlock, outings, and voice capture.",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["status", "incidents", "provider_chain", "context_budget_audit", "context_contributors_report", "profile_prune_plan", "secret_inventory", "no_agent_cron_plan", "tool_router_status", "tool_router_simulate", "memory_tier", "isolation_profile_plan", "intention_gate", "orchestration_job", "upstream_status", "watch_upstream", "live_watch", "live_watch_status", "presence_status", "ensure_todoist_mcp", "mood_status", "mood_route", "event_ingest", "self_improve", "self_improve_report", "self_improve_pipeline", "calendar_status", "calendar_event", "operator_brief", "agi_operator_cycle", "weekly_review", "todoist_lint_report", "common_sense_decision", "event_log_state", "memory_console", "todoist_rule_store", "rollover_preview", "approval_bundle", "self_improve_proposals", "external_systems_status", "hermes_capabilities_dossier", "hermes_system_audit", "trace_status", "trace_event", "eval_suite_export", "operating_snapshot", "operating_delta"]},
            "limit": {"type": "integer"},
            "hours": {"type": "integer"},
            "repo_path": {"type": "string"},
            "quiet_if_current": {"type": "boolean"},
            "filter": {"type": "string"},
            "always_on": {"type": "boolean"},
            "event_type": {"type": "string", "enum": ["wake", "desktop_unlocked", "leaving_house", "outing_request", "voice_memo_received", "telegram_feedback", "activitywatch_heartbeat"]},
            "send_telegram": {"type": "boolean"},
            "force_send": {"type": "boolean"},
            "source": {"type": "string"},
            "budget": {"type": "string"},
            "time_window": {"type": "string"},
            "energy": {"type": "string"},
            "auto_create_todoist": {"type": "boolean"},
            "transcript": {"type": "string"},
            "text": {"type": "string"},
            "audio_emotions": {"type": "object"},
            "voice_emotions": {"type": "object"},
            "allow_message": {"type": "boolean"},
            "request": {"type": "string"},
            "autonomy_level": {"type": "integer"},
            "force_observe": {"type": "boolean"},
            "create_approval": {"type": "boolean"},
            "project_id": {"type": ["string", "integer"]},
            "include_context": {"type": "boolean"},
            "write_event": {"type": "boolean"},
            "keep_plugins": {"type": ["array", "string"], "items": {"type": "string"}},
            "memory_type": {"type": "string"},
            "content": {"type": "string"},
            "profile_name": {"type": "string"},
            "profile": {"type": "string"},
            "intent": {"type": "string"},
            "explicit_intent": {"type": "string"},
            "tool_name": {"type": "string"},
            "tool": {"type": "string"},
            "title": {"type": "string"},
            "mode": {"type": "string"},
        },
        "required": ["action"],
    },
}


ADAPTIVE_COMPANION_SCHEMA = {
    "name": "personal_adaptive_companion",
    "description": "Adaptive companion layer for proactive task pressure, pattern tracking, and explanation.",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["status", "run", "explain"]},
            "query": {"type": "string"},
        },
        "required": ["action"],
    },
}


CLICKUP_SCHEMA = {
    "name": "personal_clickup",
    "description": "Native ClickUp integration for reading tasks and proposing ClickUp writes through an approval queue.",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["status", "list_tasks", "get_task", "create_task", "update_task"]},
            "list_id": {"type": ["string", "integer"]},
            "task_id": {"type": ["string", "integer"]},
            "query": {"type": "string"},
            "include_closed": {"type": "boolean"},
            "subtasks": {"type": "boolean"},
            "name": {"type": "string"},
            "description": {"type": "string"},
            "markdown_description": {"type": "string"},
            "status": {"type": "string"},
            "priority": {"type": "integer"},
            "due_date": {"type": ["string", "integer"]},
            "time_estimate": {"type": "integer"},
            "assignees": {"type": "array", "items": {"type": ["string", "integer"]}},
            "tags": {"type": "array", "items": {"type": "string"}},
            "notify_all": {"type": "boolean"},
            "archived": {"type": "boolean"}
        },
        "required": ["action"]
    }
}


TWILIO_SCHEMA = {
    "name": "personal_twilio",
    "description": "Native Twilio SMS integration for status checks and approval-gated outbound SMS sends.",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["status", "send_sms"]},
            "to": {"type": "string"},
            "body": {"type": "string"}
        },
        "required": ["action"]
    }
}


WEATHER_SCHEMA = {
    "name": "personal_weather",
    "description": "Native weather lookup using Open-Meteo geocoding and forecast APIs. Use for current conditions and tomorrow forecasts.",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["forecast"]},
            "location": {"type": "string"}
        },
        "required": ["action", "location"]
    }
}


SECURITY_SCHEMA = {
    "name": "personal_security",
    "description": "Inspect security alerts and resolve pending approval-gated app actions created by Hermes native integrations.",
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["status", "search_events", "explain_recent_action", "list_pending", "approve_request", "deny_request"]},
            "request_id": {"type": "string"},
            "query": {"type": "string"}
        },
        "required": ["action"]
    }
}


def _runtime_build_arrive_briefing(tasks: List[Dict[str, Any]], projects_map: Dict[str, str]) -> str:
    local_now = datetime.now(timezone.utc).astimezone(_runtime_local_tz())
    time_str = local_now.strftime('%I:%M %p').lstrip('0')

    personal_tasks = []
    for t in tasks:
        proj_id = t.get("project_id")
        proj_name = projects_map.get(proj_id, "").lower()
        if "work" in proj_name or "business" in proj_name:
            continue
        personal_tasks.append(t)

    overdue = []
    today = []
    for t in personal_tasks:
        due_info = t.get("due") or {}
        due_date = due_info.get("date", "")
        if due_date and due_date < local_now.strftime('%Y-%m-%d'):
            overdue.append(t)
        else:
            today.append(t)

    def _format_todoist_due_status(task: Dict[str, Any]) -> str:
        due_info = task.get("due") or {}
        due_val = due_info.get("datetime") or due_info.get("date") or due_info.get("string", "")
        due_dt = _operator_parse_task_due(task)
        if due_dt is None:
            return ""
        delta = due_dt.astimezone(_runtime_local_tz()) - local_now
        seconds = int(delta.total_seconds())
        if seconds < 0:
            seconds = abs(seconds)
            if seconds < 60:
                return "started <1m ago"
            minutes = seconds // 60
            if minutes < 60:
                return f"started {minutes}m ago"
            hours = minutes // 60
            return f"started {hours}h {minutes % 60:02d}m ago"
        if seconds < 60:
            return "starts in <1m"
        minutes = seconds // 60
        if minutes < 60:
            return f"starts in {minutes}m"
        hours = minutes // 60
        return f"starts in {hours}h {minutes % 60:02d}m"

    lines = [
        f"🏡 <b>Welcome Home!</b>",
        f"I received your arrival signal at {time_str}. Here is your custom evening digest alongside the <b>Hermes Dock</b>:",
        "",
    ]

    if overdue:
        lines.append(f"\u23f0 You have {len(overdue)} overdue task{'s' if len(overdue) != 1 else ''} that need{'s' if len(overdue) == 1 else ''} attention:")
        for t in overdue[:5]:
            t_id = t.get("id")
            content = t.get("content", "").strip()
            escaped_content = _escape_html(content)
            due_info = t.get("due") or {}
            due_val = due_info.get('string', due_info.get('date', ''))
            due_str = f" (due {due_val})" if due_val else ""
            escaped_due_str = _escape_html(due_str)
            if t_id:
                lines.append(f"  \u2022 <a href=\"https://app.todoist.com/app/task/{t_id}\">{escaped_content}</a>{escaped_due_str}")
            else:
                lines.append(f"  \u2022 {escaped_content}{escaped_due_str}")
        lines.append("")

    if today:
        lines.append(f"\U0001f4cb On your plate for today ({len(today)} task{'s' if len(today) != 1 else ''}):")
        for t in today[:7]:
            t_id = t.get("id")
            content = t.get("content", "").strip()
            escaped_content = _escape_html(content)
            due_info = t.get("due") or {}
            due_val = due_info.get('string', due_info.get('datetime', due_info.get('date', '')))
            due_str = f" ({due_val})" if due_val else ""
            due_status = _format_todoist_due_status(t)
            if due_status:
                due_str += f" [{due_status}]"
            escaped_due_str = _escape_html(due_str)
            if t_id:
                lines.append(f"  \u2022 <a href=\"https://app.todoist.com/app/task/{t_id}\">{escaped_content}</a>{escaped_due_str}")
            else:
                lines.append(f"  \u2022 {escaped_content}{escaped_due_str}")
    elif not overdue:
        lines.append("\u2705 No personal tasks due today \u2014 enjoy the free evening!")

    if personal_tasks:
        lines.append(f"\n\U0001f449 Pick one small action that fits being home now, or leave the list alone if this is family/recovery time.")

    lines.append(f"\n\U0001f552 {time_str}")
    return "\n".join(lines)


def _runtime_build_leave_briefing(tasks: List[Dict[str, Any]]) -> str:
    local_now = datetime.now(timezone.utc).astimezone(_runtime_local_tz())
    time_str = local_now.strftime('%I:%M %p').lstrip('0')

    errand_tasks = []
    for t in tasks:
        labels = [str(l).lower() for l in (t.get("labels") or [])]
        if "errands" in labels or "errand" in labels:
            errand_tasks.append(t)

    lines = [
        f"I received an away/leaving signal at {time_str}.",
        "I am only surfacing tasks that plausibly fit being out.",
        "",
    ]

    if errand_tasks:
        lines.append(f"\U0001f4dd You have {len(errand_tasks)} errand{'s' if len(errand_tasks) != 1 else ''} you could tackle while you're out:")
        for t in errand_tasks[:10]:
            t_id = t.get("id")
            content = t.get("content", "").strip()
            escaped_content = _escape_html(content)
            due_info = t.get("due") or {}
            due_val = due_info.get('string', due_info.get('date', ''))
            due_str = f" (due {due_val})" if due_val else ""
            escaped_due_str = _escape_html(due_str)
            if t_id:
                lines.append(f"  \u2022 <a href=\"https://app.todoist.com/app/task/{t_id}\">{escaped_content}</a>{escaped_due_str}")
            else:
                lines.append(f"  \u2022 {escaped_content}{escaped_due_str}")
        lines.append("\nIf one errand naturally fits the trip, do it. If not, ignore this until you are back.")
    else:
        lines.append("No errands on the list \u2014 enjoy being out! \U0001f324\ufe0f")

    lines.append(f"\n\U0001f552 {time_str}")
    return "\n".join(lines)


def _handle_location_update(args: Dict[str, Any]) -> None:
    location = args.get("location", "").strip().lower()
    if not location:
        return
    now = datetime.now(timezone.utc).isoformat()
    state = _read_json(PRESENCE_STATE_PATH, {})
    old_location = state.get("location", "").strip().lower()

    state["location"] = location
    state["last_location_update"] = now
    state["confidence"] = 1.0
    state["source"] = args.get("source", "telegram-bot")
    state["label"] = f"Location update: {location}"
    state["timestamp"] = now
    _write_json(PRESENCE_STATE_PATH, state)

    # Trigger briefings on transitions
    time_since_last_update = 999999.0
    if state.get("last_location_update"):
        try:
            last_ts = datetime.fromisoformat(state["last_location_update"])
            now_ts = datetime.fromisoformat(now)
            time_since_last_update = (now_ts - last_ts).total_seconds()
        except Exception:
            pass

    should_trigger_arrival = False
    if location in {"home", "desk"}:
        if old_location == "away" or old_location in {"", "unknown"}:
            should_trigger_arrival = True
        elif old_location == location and time_since_last_update > 1800:
            should_trigger_arrival = True
        elif old_location == "desk" and location == "home" and time_since_last_update > 1800:
            should_trigger_arrival = True

    if should_trigger_arrival:
        try:
            tasks = _focus_guard_read_todoist_tasks(filter="today | overdue")
            projects_map = {}
            with _http_client() as client:
                resp = client.get(f"{TODOIST_BASE}/projects", headers=_todoist_headers())
                if resp.status_code == 200:
                    results = resp.json().get("results") or []
                    for p in results:
                        projects_map[p["id"]] = p["name"]
            message = _runtime_build_arrive_briefing(tasks, projects_map)
            dock_buttons = _build_hermes_dock(location)
            try:
                top_tasks = _get_top_high_priority_tasks(tasks, 3)
                for t in top_tasks:
                    dock_buttons.append({
                        "text": f"✅ {t.get('content')[:20]}...",
                        "callback_data": f"po:task_complete:{t.get('id')}"
                    })
            except Exception:
                pass
            _safe_send_telegram_message(message, force=True, parse_mode="HTML", buttons=dock_buttons)
        except Exception as e:
            pass
    elif old_location in {"home", "desk"} and location == "away":
        try:
            tasks = _focus_guard_read_todoist_tasks()
            message = _runtime_build_leave_briefing(tasks)
            dock_buttons = _build_hermes_dock(location)
            try:
                top_tasks = _get_top_high_priority_tasks(tasks, 3)
                for t in top_tasks:
                    dock_buttons.append({
                        "text": f"✅ {t.get('content')[:20]}...",
                        "callback_data": f"po:task_complete:{t.get('id')}"
                    })
            except Exception:
                pass
            _safe_send_telegram_message(message, force=True, parse_mode="HTML", buttons=dock_buttons)
        except Exception as e:
            pass

def handle_location_slash_command(raw_args: str) -> str:
    location = raw_args.strip()
    if not location:
        return "Usage: /location <state> (e.g. /location away, /location focus, /location desk)"

    _handle_location_update({"location": location, "source": "telegram-bot"})
    cleanup_res = _run_auto_cleanup_routines()
    logs = cleanup_res.get("logs", [])

    msg = f"📍 Location updated to: {location}"
    if logs:
        msg += "\n\n🧹 Auto-Cleanup triggered:\n" + "\n".join([f"• {l}" for l in logs])

    return msg



def handle_briefing_slash_command(command: str, args_str: str) -> str:
    from datetime import datetime, date
    tz = _runtime_local_tz()
    local_now = datetime.now(tz)
    today_date = local_now.date()
    tomorrow_date = today_date + timedelta(days=1)

    # Read all tasks
    try:
        all_tasks = _focus_guard_read_todoist_tasks()
    except Exception as e:
        return f"❌ Failed to fetch Todoist tasks: {e}"

    cmd = command.strip().lower().replace("/", "")

    if cmd == "show_hidden_tomorrow":
        hidden_tasks = []
        for t in all_tasks:
            due_info = t.get("due") or {}
            due_date_str = due_info.get("date")
            if not due_date_str:
                continue
            try:
                date_part = due_date_str.split("T")[0]
                task_due_date = date.fromisoformat(date_part)
                if task_due_date == tomorrow_date:
                    lbls = [str(l).lower() for l in t.get("labels") or []]
                    role = _classify_task_role(t)
                    is_sub = t.get("parent_id") or t.get("parentId")
                    if role in ("reference", "checklist_item", "exclude_workload", "hermes_hidden") or is_sub or any(l in {"exclude_workload", "reference", "hermes_hidden", "checklist_item", "duplicate"} for l in lbls):
                        hidden_tasks.append(t)
            except Exception:
                pass

        if not hidden_tasks:
            return "🔍 <b>Hidden/Excluded Tasks for Tomorrow:</b>\n\nNo hidden or excluded items found for tomorrow!"

        lines = ["🔍 <b>Hidden/Excluded Tasks for Tomorrow:</b>", "These items are excluded from your active workload count:", ""]
        for idx, t in enumerate(hidden_tasks, 1):
            escaped_content = _escape_html(t.get("content", "").strip())
            t_id = t.get("id")
            lbls = [l for l in t.get("labels") or []]
            lbl_str = f" [@{', @'.join(lbls)}]" if lbls else ""
            if t_id:
                lines.append(f"  {idx}. <a href=\"https://app.todoist.com/app/task/{t_id}\">{escaped_content}</a>{lbl_str}")
            else:
                lines.append(f"  {idx}. {escaped_content}{lbl_str}")
        return "\n".join(lines)

    elif cmd == "show_task_debt":
        debt_tasks = []
        stale_tasks = []
        for t in all_tasks:
            due_info = t.get("due") or {}
            due_date_str = due_info.get("date")
            if not due_date_str:
                continue
            try:
                date_part = due_date_str.split("T")[0]
                task_due_date = date.fromisoformat(date_part)
                if task_due_date < today_date:
                    overdue_days = (today_date - task_due_date).days
                    priority = int(t.get("priority") or 1)
                    if overdue_days >= 7 and priority < 4:
                        stale_tasks.append((t, overdue_days))
                    else:
                        debt_tasks.append((t, overdue_days))
            except Exception:
                pass

        lines = []
        if debt_tasks:
            lines.append("⏳ <b>Active Overdue Task Debt:</b>")
            for idx, (t, days) in enumerate(debt_tasks, 1):
                escaped_content = _escape_html(t.get("content", "").strip())
                t_id = t.get("id")
                days_str = f"({days} days overdue)"
                if t_id:
                    lines.append(f"  • <a href=\"https://app.todoist.com/app/task/{t_id}\">{escaped_content}</a> {days_str}")
                else:
                    lines.append(f"  • {escaped_content} {days_str}")
            lines.append("")
        else:
            lines.append("⏳ <b>Active Overdue Task Debt:</b>\nNo active overdue task debt! Excellent.")
            lines.append("")

        if stale_tasks:
            lines.append("🗄️ <b>Stale Backlog (Decayed Overdue):</b>")
            lines.append("These low-priority items have been overdue for 7+ days and are quarantined:")
            for idx, (t, days) in enumerate(stale_tasks, 1):
                escaped_content = _escape_html(t.get("content", "").strip())
                t_id = t.get("id")
                days_str = f"({days} days overdue)"
                if t_id:
                    lines.append(f"  • <a href=\"https://app.todoist.com/app/task/{t_id}\">{escaped_content}</a> {days_str}")
                else:
                    lines.append(f"  • {escaped_content} {days_str}")
        else:
            lines.append("🗄️ <b>Stale Backlog:</b>\nNo stale backlog items found.")

        return "\n".join(lines)

    elif cmd == "why_suppressed":
        hidden_counts = {
            "reference": 0,
            "checklist": 0,
            "routine": 0,
            "exclude_workload": 0,
            "stale": 0
        }

        for t in all_tasks:
            labels = [str(l).lower() for l in t.get("labels") or []]
            role = _classify_task_role(t)
            is_sub = t.get("parent_id") or t.get("parentId")

            due_info = t.get("due") or {}
            due_date_str = due_info.get("date")
            is_overdue = False
            overdue_days = 0
            if due_date_str:
                try:
                    date_part = due_date_str.split("T")[0]
                    task_due_date = date.fromisoformat(date_part)
                    if task_due_date < today_date:
                        is_overdue = True
                        overdue_days = (today_date - task_due_date).days
                except Exception:
                    pass

            if is_overdue and overdue_days >= 7 and int(t.get("priority") or 1) < 4:
                hidden_counts["stale"] += 1
            elif "reference" in labels:
                hidden_counts["reference"] += 1
            elif "checklist_item" in labels or is_sub:
                hidden_counts["checklist"] += 1
            elif "routine" in labels:
                hidden_counts["routine"] += 1
            elif "exclude_workload" in labels:
                hidden_counts["exclude_workload"] += 1

        total = sum(hidden_counts.values())

        report = (
            f"🛡️ <b>Why Suppressed Explanation</b>\n\n"
            f"I filtered out <b>{total} total items</b> from your active briefing counts to protect your focus and keep your workspace clean:\n\n"
            f"• <b>{hidden_counts['reference']} Reference Notes</b> (rules, principles, or templates)\n"
            f"• <b>{hidden_counts['checklist']} Subtasks/Checklist items</b> (nested under parent actions)\n"
            f"• <b>{hidden_counts['routine']} Routines/Habits</b> (standard daily/weekly repeats)\n"
            f"• <b>{hidden_counts['exclude_workload']} Excluded Workload</b> (explicitly marked to bypass count)\n"
            f"• <b>{hidden_counts['stale']} Decayed Overdue Items</b> (overdue 7+ days without priority)\n\n"
            f"<i>By isolating these layers, Hermes ensures you are presented with a calm, highly-actionable tomorrow preview with zero noise!</i>"
        )
        return report

    elif cmd == "health_score":
        active_count = len(all_tasks)
        tomorrow_count = 0
        debt_count = 0
        stale_count = 0
        reference_count = 0
        high_priority_count = 0
        inbox_leakage_count = 0
        unscheduled_count = 0

        from collections import defaultdict
        name_groups = defaultdict(list)

        for t in all_tasks:
            content = str(t.get("content") or "").strip()
            content_clean = content.lower()
            name_groups[content_clean].append(t)

            labels = [str(l).lower() for l in t.get("labels") or []]
            priority = int(t.get("priority") or 1)
            project_id = str(t.get("project_id") or "").strip()

            is_ref = "reference" in labels
            is_family = "family_anchor" in labels
            is_fitness = "fitness_anchor" in labels

            if priority >= 3:
                high_priority_count += 1

            if not project_id:
                inbox_leakage_count += 1

            if is_ref:
                reference_count += 1

            due_info = t.get("due") or {}
            due_date_str = due_info.get("date")
            if due_date_str:
                try:
                    date_part = due_date_str.split("T")[0]
                    task_due_date = date.fromisoformat(date_part)
                    if task_due_date == tomorrow_date:
                        if not is_ref and not is_family and not is_fitness:
                            tomorrow_count += 1
                    elif task_due_date < today_date:
                        overdue_days = (today_date - task_due_date).days
                        if overdue_days >= 7 and priority < 4:
                            stale_count += 1
                        else:
                            debt_count += 1
                except Exception:
                    pass
            else:
                if not is_ref:
                    unscheduled_count += 1

        duplicate_groups = [g for name, g in name_groups.items() if len(g) > 1]
        duplicate_candidates_count = sum(len(g) for g in duplicate_groups)

        deductions = 0
        deductions += min(15, debt_count * 1)
        deductions += min(20, stale_count * 2)
        deductions += min(15, reference_count * 2)
        deductions += min(15, len(duplicate_groups) * 3)

        priority_inflation = max(0, high_priority_count - 10)
        deductions += min(15, priority_inflation * 1)
        deductions += min(10, inbox_leakage_count * 2)
        deductions += min(10, unscheduled_count * 1)

        score = max(0, 100 - deductions)

        issues = []
        if stale_count >= 5:
            issues.append("stale backlog")
        if priority_inflation >= 5:
            issues.append("priority inflation")
        if inbox_leakage_count >= 5:
            issues.append("inbox leakage")

        main_issue = " + ".join(issues) if issues else "priority inflation + stale backlog"

        report = (
            f"📊 <b>Todoist Workspace Clarity: {score}/100</b>\n\n"
            f"• Active Tasks: {active_count}\n"
            f"• True Scheduled Tomorrow: {tomorrow_count}\n"
            f"• Overdue Task Debt: {debt_count}\n"
            f"• Quiet Backlog (Stale): {stale_count}\n"
            f"• Reference Tasks in Active List: {reference_count}\n"
            f"• Duplicate Candidates: {duplicate_candidates_count}\n"
            f"• High-Priority Tasks: {high_priority_count}\n"
            f"• Inbox Leakage: {inbox_leakage_count}\n\n"
            f"Main Issue: <b>{main_issue.capitalize()}</b>.\n"
            f"Recommended Step: A gentle 15-minute cleanup sweep, not more planning."
        )
        return report

    elif cmd == "entropy_check":
        stale_list = []
        duplicate_list = []
        no_project_list = []
        unscheduled_list = []
        postponed_list = []

        from collections import defaultdict
        name_groups = defaultdict(list)

        operator_state = _operator_read_state()
        due_shifts = operator_state.get("task_due_shifts", {})

        for t in all_tasks:
            content = str(t.get("content") or "").strip()
            content_clean = content.lower()
            name_groups[content_clean].append(t)

            project_id = str(t.get("project_id") or "").strip()
            t_id = t.get("id")

            if t_id and t_id in due_shifts and due_shifts[t_id].get("shifts", 0) >= 3:
                postponed_list.append((t, due_shifts[t_id]["shifts"]))

            if not project_id:
                no_project_list.append(t)

            due_info = t.get("due") or {}
            due_date_str = due_info.get("date")
            if due_date_str:
                try:
                    date_part = due_date_str.split("T")[0]
                    task_due_date = date.fromisoformat(date_part)
                    if task_due_date < today_date:
                        overdue_days = (today_date - task_due_date).days
                        priority = int(t.get("priority") or 1)
                        if overdue_days >= 7 and priority < 4:
                            stale_list.append((t, overdue_days))
                except Exception:
                    pass
            else:
                if "reference" not in [l.lower() for l in t.get("labels") or []]:
                    unscheduled_list.append(t)

        for name, group in name_groups.items():
            if len(group) > 1:
                duplicate_list.extend(group)

        lines = ["🧹 <b>Weekly Workspace Simplicity Sweep</b>", "A gentle review to keep your lists fresh, clean, and simple:", ""]

        if duplicate_list:
            lines.append("<b>• Possible Duplicates:</b>")
            for t in duplicate_list[:5]:
                escaped = _escape_html(t.get("content", ""))
                lines.append(f"  - {escaped} (ID: {t.get('id')})")
            if len(duplicate_list) > 5:
                lines.append(f"  ... and {len(duplicate_list) - 5} more duplicate(s)")
            lines.append("")

        if stale_list:
            lines.append("<b>• Quiet Backlog (Overdue 7+ days):</b>")
            for t, days in stale_list[:5]:
                escaped = _escape_html(t.get("content", ""))
                lines.append(f"  - {escaped} ({days} days overdue)")
            if len(stale_list) > 5:
                lines.append(f"  ... and {len(stale_list) - 5} more stale task(s)")
            lines.append("")

        if postponed_list:
            lines.append("<b>• Tasks that Keep Moving (3+ reschedules):</b>")
            for t, shifts in postponed_list[:5]:
                escaped = _escape_html(t.get("content", ""))
                lines.append(f"  - {escaped} (postponed {shifts} times)")
            if len(postponed_list) > 5:
                lines.append(f"  ... and {len(postponed_list) - 5} more postponed task(s)")
            lines.append("")

        if no_project_list:
            lines.append("<b>• Unfiled Tasks (Inbox):</b>")
            for t in no_project_list[:5]:
                escaped = _escape_html(t.get("content", ""))
                lines.append(f"  - {escaped}")
            if len(no_project_list) > 5:
                lines.append(f"  ... and {len(no_project_list) - 5} more inbox item(s)")
            lines.append("")

        if unscheduled_list:
            lines.append("<b>• Tasks Waiting for a Time (No Due Date):</b>")
            for t in unscheduled_list[:5]:
                escaped = _escape_html(t.get("content", ""))
                lines.append(f"  - {escaped}")
            if len(unscheduled_list) > 5:
                lines.append(f"  ... and {len(unscheduled_list) - 5} more unscheduled item(s)")
            lines.append("")

        if len(lines) <= 3:
            lines.append("✨ <b>Everything is perfectly clear! Your workspace is beautifully organized.</b>")

        return "\n".join(lines)

    return f"Unknown command: /{cmd}"


def _auto_cleanup_stale_tasks(tasks: List[Dict[str, Any]]) -> List[str]:
    logs = []
    now = datetime.now(timezone.utc)
    for t in tasks:
        # Check for carry_until_done metadata
        metadata_str = t.get("description", "")
        if "carry_until_done" in metadata_str or "stale" in metadata_str:
            created = t.get("created_at")
            if created:
                try:
                    dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    if (now - dt).days >= 3 and t.get("due"):
                        # Demote task
                        with _http_client() as client:
                            url = f"{TODOIST_BASE}/tasks/{t['id']}"
                            labels = t.get("labels", [])
                            if "stale" not in labels:
                                labels.append("stale")
                            # Removing due date and adding label
                            payload = {"due_string": "no date", "labels": labels}
                            client.post(url, headers=_todoist_headers(), json=payload)
                        logs.append(f"Demoted stale task: {t.get('content')}")
                except Exception:
                    pass
    return logs

def _auto_cleanup_location_away(tasks: List[Dict[str, Any]]) -> List[str]:
    logs = []
    state = _read_json(PRESENCE_STATE_PATH, {})
    if state.get("location") != "away":
        return logs

    for t in tasks:
        # Here we look for skip_if_away rule or metadata
        if "skip_if_away" in t.get("description", "") and t.get("due"):
            with _http_client() as client:
                url = f"{TODOIST_BASE}/tasks/{t['id']}/close"
                client.post(url, headers=_todoist_headers())
            logs.append(f"Skipped task due to away location: {t.get('content')}")
    return logs

def _auto_cleanup_friday_purge(tasks: List[Dict[str, Any]]) -> List[str]:
    logs = []
    now = datetime.now(_runtime_local_tz())
    if now.weekday() == 4 and now.hour >= 17:
        for t in tasks:
            # Check inbox, no due date
            if not t.get("due") and not t.get("project_id"): # inbox
                # Assume parking lot is a specific project or just add label
                with _http_client() as client:
                    url = f"{TODOIST_BASE}/tasks/{t['id']}"
                    labels = t.get("labels", [])
                    if "parking_lot" not in labels:
                        labels.append("parking_lot")
                    client.post(url, headers=_todoist_headers(), json={"labels": labels})
                logs.append(f"Friday purge applied to: {t.get('content')}")
    return logs

def _auto_cleanup_quiet_hours(tasks: List[Dict[str, Any]]) -> List[str]:
    logs = []
    now = datetime.now(_runtime_local_tz())
    if now.hour >= 18:
        for t in tasks:
            # Check if business task due today
            if t.get("due") and ("business" in t.get("labels", []) or "work" in t.get("labels", [])):
                due_date = t["due"].get("date")
                if due_date and due_date.startswith(now.strftime("%Y-%m-%d")):
                    with _http_client() as client:
                        url = f"{TODOIST_BASE}/tasks/{t['id']}"
                        client.post(url, headers=_todoist_headers(), json={"due_string": "tomorrow morning"})
                    logs.append(f"Quiet hours deferral for: {t.get('content')}")
    return logs

def _run_auto_cleanup_routines() -> Dict[str, Any]:
    logs = []
    try:
        tasks = _focus_guard_read_todoist_tasks()
        logs.extend(_auto_cleanup_stale_tasks(tasks))
        logs.extend(_auto_cleanup_location_away(tasks))
        logs.extend(_auto_cleanup_friday_purge(tasks))
        logs.extend(_auto_cleanup_quiet_hours(tasks))
        logs.extend(_run_system_cleanliness_audit())
    except Exception as e:
        logs.append(f"Error running cleanup routines: {e}")
    return {"status": "success", "logs": logs}

_DAILY_THEMES = {
    0: "Strategic Planning & Clean Slate",
    1: "Deep Work Focus",
    2: "Deep Work Focus",
    3: "Deep Work Focus",
    4: "Clean Up & Friday Purge",
    5: "Rest, Recharge & Personal Habits",
    6: "Rest, Recharge & Personal Habits",
}


def _escape_html(text: str) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _safe_send_telegram_message(text: str, **kwargs: Any) -> Dict[str, Any]:
    import inspect
    try:
        sig = inspect.signature(_focus_guard_send_telegram_message)
        has_var_keyword = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
        if has_var_keyword:
            return _focus_guard_send_telegram_message(text, **kwargs)
        valid_kwargs = {}
        for k, v in kwargs.items():
            if k in sig.parameters:
                valid_kwargs[k] = v
        return _focus_guard_send_telegram_message(text, **valid_kwargs)
    except Exception:
        return _focus_guard_send_telegram_message(text)


def _get_projects_map() -> Dict[str, str]:
    projects_map = {}
    try:
        with _http_client() as client:
            resp = client.get(f"{TODOIST_BASE}/projects", headers=_todoist_headers())
            if resp.status_code == 200:
                results = resp.json().get("results") or []
                for p in results:
                    projects_map[p["id"]] = p["name"]
    except Exception:
        pass
    return projects_map

def _get_top_high_priority_tasks(tasks: List[Dict[str, Any]], limit: int = 3) -> List[Dict[str, Any]]:
    # Filter out completed or invalid tasks
    active = [t for t in tasks if not t.get("completed") and t.get("id") and t.get("content")]
    # Sort descending by priority (Todoist priority: 4 is highest, 1 is lowest)
    active.sort(key=lambda t: int(t.get("priority", 1)), reverse=True)
    return active[:limit]


def _build_hermes_dock(location: str, local_now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    if local_now is None:
        local_now = datetime.now(timezone.utc).astimezone(_runtime_local_tz())

    hour = local_now.hour
    location = str(location or "").strip().lower()

    # Fetch projects map to find specific project links
    projects_map = _get_projects_map()

    work_proj_id = None
    personal_proj_id = None
    for pid, name in projects_map.items():
        name_lower = name.lower()
        if not work_proj_id and ("work" in name_lower or "business" in name_lower):
            work_proj_id = pid
        if not personal_proj_id and "personal" in name_lower:
            personal_proj_id = pid

    # Decide context
    is_work_hours = (9 <= hour < 17)

    buttons = []
    if location == "desk" or (location != "away" and is_work_hours):
        # Desk / Work context
        work_url = f"https://todoist.com/app/project/{work_proj_id}" if work_proj_id else "https://todoist.com/app/today"
        buttons.append({"text": "💼 Work App", "url": work_url})
        buttons.append({"text": "💼 Work (Watch)", "callback_data": f"po:show_list:work:{work_proj_id or 'none'}"})
        buttons.append({"text": "📥 Inbox App", "url": "https://todoist.com/app/inbox"})
        buttons.append({"text": "📥 Inbox (Watch)", "callback_data": "po:show_list:inbox"})
    elif location == "away":
        # Away context
        buttons.append({"text": "🏃 Errands App", "url": "https://todoist.com/app/label/errands"})
        buttons.append({"text": "🏃 Errands (Watch)", "callback_data": "po:show_list:errands"})
        buttons.append({"text": "📅 Today App", "url": "https://todoist.com/app/today"})
        buttons.append({"text": "📅 Today (Watch)", "callback_data": "po:show_list:today"})
    else:
        # Home / Evening context
        personal_url = f"https://todoist.com/app/project/{personal_proj_id}" if personal_proj_id else "https://todoist.com/app/today"
        buttons.append({"text": "⚓ Review Anchors", "callback_data": "po:review_anchors"})
        buttons.append({"text": "📅 Today (Watch)", "callback_data": "po:show_list:today"})
        buttons.append({"text": "🏠 Personal App", "url": personal_url})
        buttons.append({"text": "📥 Inbox App", "url": "https://todoist.com/app/inbox"})

    return buttons


def _parse_todoist_datetime(dt_str: str) -> datetime:
    if not dt_str:
        return datetime.min.replace(tzinfo=timezone.utc)
    cleaned = dt_str.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(cleaned)
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)


def _get_recent_completions() -> List[Dict[str, Any]]:
    completed = []
    try:
        completed_activity_result = safe_call("completed_activity", "mcp_todoist_find_activity", {"objectType": "task", "eventType": "completed", "limit": 50})
        if completed_activity_result:
            completed = _todoist_activity_items(completed_activity_result)
    except Exception:
        pass

    if not completed:
        try:
            token = _env("TODOIST_API_TOKEN")
            if token:
                headers = {"Authorization": f"Bearer {token}"}
                with _http_client() as client:
                    resp = client.get("https://api.todoist.com/sync/v9/completed/get_all", headers=headers)
                    if resp.status_code == 200:
                        items = resp.json().get("items") or []
                        for item in items:
                            completed.append({
                                "task_id": item.get("task_id"),
                                "project_id": item.get("project_id"),
                                "content": item.get("content"),
                                "completed_at": item.get("completed_at"),
                            })
        except Exception:
            pass

    return completed


def _run_system_cleanliness_audit(now: Optional[datetime] = None) -> List[str]:
    logs = []
    if now is None:
        now = datetime.now(timezone.utc).astimezone(_runtime_local_tz())

    state = _operator_read_state()
    last_inbox_zero = state.get("last_inbox_zero_nudge_at")
    last_stale_project = state.get("last_stale_project_audit_at")

    inbox_audit_due = True
    project_audit_due = True

    if last_inbox_zero:
        try:
            last_inbox_dt = datetime.fromisoformat(last_inbox_zero)
            if (now - last_inbox_dt).total_seconds() < 24 * 3600:
                inbox_audit_due = False
        except Exception:
            pass

    if last_stale_project:
        try:
            last_proj_dt = datetime.fromisoformat(last_stale_project)
            if (now - last_proj_dt).total_seconds() < 24 * 3600:
                project_audit_due = False
        except Exception:
            pass

    if not inbox_audit_due and not project_audit_due:
        return logs

    try:
        tasks = _focus_guard_read_todoist_tasks()
    except Exception as e:
        logs.append(f"Audit failed to read Todoist tasks: {e}")
        return logs

    projects_map = _get_projects_map()
    inbox_project_id = None
    for pid, name in projects_map.items():
        if name.lower() == "inbox":
            inbox_project_id = pid
            break

    # 1. Inbox Zero Nudges
    if inbox_audit_due and inbox_project_id:
        lingering = []
        for t in tasks:
            if t.get("project_id") == inbox_project_id:
                created_at_str = t.get("created_at")
                if created_at_str:
                    created_at = _parse_todoist_datetime(created_at_str)
                    age_seconds = (now - created_at).total_seconds()
                    if age_seconds > 48 * 3600:
                        days = int(age_seconds / 86400)
                        lingering.append((t, days))

        if lingering:
            msg_lines = [
                "\U0001f4e5 <b>Inbox Cleanliness Nudge</b>",
                "You have tasks lingering in your Inbox for over 48 hours:",
            ]
            for idx, (t, days) in enumerate(lingering[:3], 1):
                t_id = t.get("id")
                escaped_content = _escape_html(t.get("content", ""))
                if t_id:
                    msg_lines.append(f"  {idx}️⃣ <a href=\"https://app.todoist.com/app/task/{t_id}\">{escaped_content}</a> (added {days} days ago)")
                else:
                    msg_lines.append(f"  {idx}️⃣ {escaped_content} (added {days} days ago)")
            if len(lingering) > 3:
                for t, days in lingering[3:5]:
                    t_id = t.get("id")
                    escaped_content = _escape_html(t.get("content", ""))
                    if t_id:
                        msg_lines.append(f"  • <a href=\"https://app.todoist.com/app/task/{t_id}\">{escaped_content}</a> (added {days} days ago)")
                    else:
                        msg_lines.append(f"  • {escaped_content} (added {days} days ago)")
            msg_lines.append("\nConsider moving them to appropriate projects or processing them now!")

            sweep_buttons = []
            for idx, (t, _) in enumerate(lingering[:3], 1):
                t_id = t.get("id")
                if t_id:
                    sweep_buttons.append([
                        {"text": f"✅ {idx}", "callback_data": f"po:task_complete:{t_id}"},
                        {"text": f"📅 {idx}", "callback_data": f"po:task_defer:{t_id}"},
                        {"text": f"🗑️ {idx}", "callback_data": f"po:task_delete:{t_id}"}
                    ])

            try:
                _safe_send_telegram_message("\n".join(msg_lines), force=True, parse_mode="HTML", buttons=sweep_buttons)
                state["last_inbox_zero_nudge_at"] = now.isoformat()
                _operator_write_state(state)
                logs.append("Sent Inbox Zero audit nudge.")
            except Exception as e:
                logs.append(f"Failed to send Inbox Zero nudge: {e}")

    # 2. Stale Project Audits
    if project_audit_due:
        proj_tasks = {}
        for t in tasks:
            pid = t.get("project_id")
            if pid:
                proj_tasks.setdefault(pid, []).append(t)

        completions = _get_recent_completions()

        proj_completions = {}
        for c in completions:
            pid = c.get("project_id")
            if pid:
                proj_completions.setdefault(pid, []).append(c)

        stale_projects = []
        for pid, name in projects_map.items():
            if name.lower() == "inbox":
                continue
            active = proj_tasks.get(pid, [])
            if not active:
                continue

            oldest_age_days = 0
            for t in active:
                created_at_str = t.get("created_at")
                if created_at_str:
                    created_at = _parse_todoist_datetime(created_at_str)
                    age_days = (now - created_at).total_seconds() / 86400
                    if age_days > oldest_age_days:
                        oldest_age_days = age_days

            if oldest_age_days > 14:
                has_recent_completion = False
                for c in proj_completions.get(pid, []):
                    comp_at_str = c.get("completed_at")
                    if comp_at_str:
                        comp_at = _parse_todoist_datetime(comp_at_str)
                        if (now - comp_at).total_seconds() < 14 * 24 * 3600:
                            has_recent_completion = True
                            break
                if not has_recent_completion:
                    stale_projects.append((pid, name, int(oldest_age_days)))

        if stale_projects:
            msg_lines = [
                "\U0001f5c2\ufe0f <b>Stale Project Audit Alert</b>",
                "The following projects have active tasks but have seen no completion activity in over 14 days:",
            ]
            for pid, name, days in stale_projects[:5]:
                escaped_name = _escape_html(name)
                msg_lines.append(f"  \u2022 <a href=\"https://todoist.com/app/project/{pid}\">{escaped_name}</a> (oldest task is {days} days old)")
            msg_lines.append("\nConsider reviewing these projects to keep your workspace fresh and lightweight!")

            project_buttons = []
            for pid, name, _ in stale_projects[:5]:
                project_buttons.append({
                    "text": f"📁 {name}",
                    "callback_data": f"po:show_list:project:{pid}"
                })

            try:
                _safe_send_telegram_message("\n".join(msg_lines), force=True, parse_mode="HTML", buttons=project_buttons)
                state["last_stale_project_audit_at"] = now.isoformat()
                _operator_write_state(state)
                logs.append("Sent Stale Project audit nudge.")
            except Exception as e:
                logs.append(f"Failed to send Stale Project audit: {e}")

    return logs


def _build_mood_recommendation(mood_state: Dict[str, Any], local_now: datetime) -> str:
    mood_label = str((mood_state.get("last_mood") or {}).get("label") or "").lower()
    hour = local_now.hour

    is_morning = (5 <= hour < 12)
    is_low_energy = mood_label in {"low_energy", "frustrated", "confused", "tired", "stressed"}

    if is_low_energy:
        label_url = "https://todoist.com/app/label/low_energy"
        return f"\n\n\u2616 <b>Mood Match:</b> Feeling low on battery? No pressure. Let's make progress easy by starting a task under the <b><a href=\"{label_url}\">@low_energy</a></b> label."
    elif is_morning or mood_label in {"focused", "motivated", "productive"}:
        label_url = "https://todoist.com/app/label/deep_work"
        return f"\n\n\u2616 <b>Mood Match:</b> A fresh window is open. Ready for deep focus? Tackling a task with the <b><a href=\"{label_url}\">@deep_work</a></b> label is a great momentum builder."

    return ""
