from __future__ import annotations

from . import legacy_shared as _legacy_shared

globals().update({
    name: value
    for name, value in _legacy_shared.__dict__.items()
    if not name.startswith("__")
})

# This module was mechanically extracted from temp_personal_ops_tools.py.
# The compatibility wrapper injects cross-domain legacy globals after import.

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

    def _record_callback_outcome(metadata: Optional[Dict[str, Any]] = None) -> None:
        try:
            from plugins.personal_ops.nudge_receipts import record_outcome

            message = getattr(query, "message", None)
            chat = getattr(message, "chat", None)
            chat_id = getattr(message, "chat_id", None) or getattr(chat, "id", None)
            message_id = getattr(message, "message_id", None)
            user = getattr(query, "from_user", None)
            user_id = getattr(user, "id", None)
            record_outcome(
                callback_data=data,
                chat_id=chat_id,
                message_id=message_id,
                user_id=user_id,
                metadata=metadata,
            )
        except Exception:
            pass

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

    elif action == "gym":
        if len(parts) < 3:
            await query.answer()
            return

        gym_action = parts[2]
        task_id = parts[3] if len(parts) >= 4 else ""
        if gym_action == "complete" and task_id:
            try:
                with _http_client() as client:
                    url = f"{TODOIST_BASE}/tasks/{task_id}/close"
                    resp = client.post(url, headers=_todoist_headers())
                    resp.raise_for_status()

                _record_callback_outcome({"gym_action": "complete", "task_id": task_id})
                await query.answer(text="Workout confirmed and completed.")
                text = query.message.text or ""
                new_text = text + "\n\n<b>Workout confirmed. Todoist task completed.</b>"
                await query.edit_message_text(new_text, parse_mode="HTML", reply_markup=None)
            except Exception as e:
                await query.answer(text=f"Failed to complete workout task: {e}")
        elif gym_action == "partial":
            _record_callback_outcome({"gym_action": "partial", "task_id": task_id})
            await query.answer(text="Logged as partial.")
            text = query.message.text or ""
            new_text = text + "\n\n<b>Logged as partial. Todoist was not auto-completed.</b>"
            await query.edit_message_text(new_text, parse_mode="HTML", reply_markup=None)
        elif gym_action == "mistake":
            _record_callback_outcome({"gym_action": "mistake"})
            await query.answer(text="Marked as a mistaken gym event.")
            text = query.message.text or ""
            new_text = text + "\n\n<b>Marked as a mistaken gym event. No Todoist task was completed.</b>"
            await query.edit_message_text(new_text, parse_mode="HTML", reply_markup=None)
        else:
            await query.answer(text="Unknown gym action.")

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
