from __future__ import annotations

from . import legacy_shared as _legacy_shared

globals().update({
    name: value
    for name, value in _legacy_shared.__dict__.items()
    if not name.startswith("__")
})

# This module was mechanically extracted from temp_personal_ops_tools.py.
# The compatibility wrapper injects cross-domain legacy globals after import.


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
