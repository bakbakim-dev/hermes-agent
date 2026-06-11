from __future__ import annotations

from . import legacy_shared as _legacy_shared

globals().update({
    name: value
    for name, value in _legacy_shared.__dict__.items()
    if not name.startswith("__")
})

# This module was mechanically extracted from temp_personal_ops_tools.py.
# The compatibility wrapper injects cross-domain legacy globals after import.

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
    return _export_promptfoo_suite(
        proposals_path=SELF_IMPROVE_PROPOSALS_PATH,
        trace_log_path=TRACE_LOG_PATH,
        config_path=PROMPTFOO_CONFIG_PATH,
        evals_path=PROMPTFOO_EVALS_PATH,
    )


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
