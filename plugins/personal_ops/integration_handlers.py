from __future__ import annotations

from . import legacy_shared as _legacy_shared

globals().update({
    name: value
    for name, value in _legacy_shared.__dict__.items()
    if not name.startswith("__")
})

# This module was mechanically extracted from temp_personal_ops_tools.py.
# The compatibility wrapper injects cross-domain legacy globals after import.

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
            connector_mode = _todoist_connector_mode()
            mcp_primary_configured = connector_mode == "mcp_primary"
            mcp_required = _env("TODOIST_MCP_REQUIRED").strip().lower() in {"1", "true", "yes", "on"}
            mcp_available = (
                _todoist_mcp_available()
                if mcp_primary_configured or mcp_required
                else None
            )
            native_status_connector = native_result.get("connector") or "native_api"
            if mcp_primary_configured and mcp_available:
                active_primary_connector = "mcp"
            elif mcp_primary_configured and mcp_required:
                active_primary_connector = "mcp_unavailable"
            else:
                active_primary_connector = "native_api"
            native_result["connector"] = active_primary_connector
            native_result["active_primary_connector"] = active_primary_connector
            native_result["native_status_connector"] = native_status_connector
            native_result["connector_mode"] = connector_mode
            native_result["mcp_primary_configured"] = mcp_primary_configured
            native_result["mcp_required"] = mcp_required
            native_result["mcp_available"] = mcp_available
            native_result["mcp_probe_skipped"] = mcp_available is None
            return _tool_result(native_result)
        if action == "intelligence":
            return _tool_result(_todoist_intelligence(args))
        if _todoist_connector_mode() == "mcp_primary" and action in {"list_tasks", "search_tasks"}:
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
