from __future__ import annotations

import json
import sys
import types
from datetime import datetime as real_datetime
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_DIR = REPO_ROOT / "plugins" / "personal_ops"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from plugins.personal_ops import temp_personal_ops_tools as tools


class _FakeResponse:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    def __init__(self, payload: dict):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get(self, url: str, headers=None, params=None):
        assert url.endswith("/tasks")
        return _FakeResponse(self._payload)


async def _async_true(*args, **kwargs):
    del args, kwargs
    return True


async def _async_reply(*args, **kwargs):
    del args, kwargs
    return None


class _FakeEventClient(_FakeClient):
    pass


def _decode(result: str) -> dict:
    return json.loads(result)


def test_runtime_tool_router_simulate_action():
    result = _decode(
        tools.handle_runtime(
            {
                "action": "tool_router_simulate",
                "tool_name": "browser_click",
                "request": "show my Todoist tasks",
            }
        )
    )

    assert result["success"] is True
    assert result["action"] == "tool_router_simulate"
    assert result["decision"]["approval_required"] is True


def test_runtime_context_contributors_report_action():
    result = _decode(tools.handle_runtime({"action": "context_contributors_report"}))

    assert result["success"] is True
    assert result["action"] == "context_contributors_report"
    assert "event_path" in result


@pytest.fixture(autouse=True)
def _isolated_hermes_home(tmp_path, monkeypatch):
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setenv("TODOIST_API_TOKEN", "dummy_token")
    monkeypatch.setenv("TODOIST_CONNECTOR_MODE", "native_primary")
    monkeypatch.setenv("TODOIST_MCP_REQUIRED", "false")
    monkeypatch.setenv("CLICKUP_API_TOKEN", "dummy_token")
    monkeypatch.setattr(tools, "HERMES_HOME", hermes_home)
    monkeypatch.setattr(tools, "APPROVALS_PATH", hermes_home / "personal_ops_approvals.json")
    monkeypatch.setattr(tools, "EVENTS_PATH", hermes_home / "personal_ops_events.jsonl")
    monkeypatch.setattr(tools, "FOCUS_GUARD_STATE_PATH", hermes_home / "focus_guard_state.json")
    monkeypatch.setattr(tools, "FOCUS_GUARD_EVENT_LOG_PATH", hermes_home / "focus_guard_events.jsonl")
    monkeypatch.setattr(tools, "ADAPTIVE_COMPANION_STATE_PATH", hermes_home / "adaptive_companion_state.json")
    monkeypatch.setattr(tools, "ADAPTIVE_COMPANION_EVENTS_PATH", hermes_home / "adaptive_companion_events.jsonl")
    monkeypatch.setattr(tools, "LIVE_WATCH_STATE_PATH", hermes_home / "live_watch_state.json")
    monkeypatch.setattr(tools, "EVENT_ROUTER_STATE_PATH", hermes_home / "event_router_state.json")
    monkeypatch.setattr(tools, "VOICE_CAPTURE_LOG_PATH", hermes_home / "voice_capture_log.jsonl")
    monkeypatch.setattr(tools, "WORK_LOG_PATH", hermes_home / "work_log.jsonl")
    monkeypatch.setattr(tools, "SELF_IMPROVE_STATE_PATH", hermes_home / "self_improve_state.json")
    monkeypatch.setattr(tools, "OPERATOR_STATE_PATH", hermes_home / "operator_state.json")
    monkeypatch.setattr(tools, "OPERATOR_BRIEF_LOG_PATH", hermes_home / "operator_briefs.jsonl")
    monkeypatch.setattr(tools, "TODOIST_REPAIR_QUEUE_PATH", hermes_home / "todoist_repair_queue.json", raising=False)
    monkeypatch.setattr(tools, "OPERATOR_MEMORY_PATH", hermes_home / "operator_memory.json", raising=False)
    monkeypatch.setattr(tools, "TODOIST_RULES_PATH", hermes_home / "todoist_rules.json", raising=False)
    monkeypatch.setattr(tools, "SELF_IMPROVE_PROPOSALS_PATH", hermes_home / "self_improve_proposals.json", raising=False)
    monkeypatch.setattr(tools, "SELF_IMPROVE_PIPELINES_PATH", hermes_home / "self_improve_pipelines.json", raising=False)
    monkeypatch.setattr(tools, "TRACE_LOG_PATH", hermes_home / "runtime_traces.jsonl", raising=False)
    monkeypatch.setattr(tools, "PROMPTFOO_EVALS_PATH", hermes_home / "promptfoo_eval_cases.json", raising=False)
    monkeypatch.setattr(tools, "PROMPTFOO_CONFIG_PATH", hermes_home / "promptfoo_config.json", raising=False)
    monkeypatch.setattr(tools, "CALENDAR_STATE_PATH", hermes_home / "calendar_state.json", raising=False)
    monkeypatch.setattr(tools, "PRESENCE_STATE_PATH", hermes_home / "presence_state.json")
    monkeypatch.setattr(tools, "NUDGE_BUDGET_STATE_PATH", hermes_home / "nudge_budget_state.json")
    monkeypatch.setattr(tools, "MOOD_ROUTER_STATE_PATH", hermes_home / "mood_router_state.json")
    monkeypatch.setattr(tools, "CRON_JOBS_PATH", hermes_home / "cron" / "jobs.json")
    monkeypatch.setattr(tools, "_append_event", lambda *args, **kwargs: None)


def test_semantic_search_finds_exercise_related_tasks(monkeypatch):
    payload = {
        "results": [
            {
                "id": "1",
                "content": "Gym session",
                "description": "Leg day after work.",
                "labels": ["health"],
            },
            {
                "id": "2",
                "content": "Family handoff",
                "description": "Non-workout evening default; gym conflict if timing slips.",
                "labels": [],
            },
            {
                "id": "3",
                "content": "Buy groceries",
                "description": "Eggs and fruit.",
                "labels": [],
            },
        ]
    }
    monkeypatch.setattr(tools, "_http_client", lambda: _FakeClient(payload))
    monkeypatch.setattr(tools, "_todoist_headers", lambda: {"Authorization": "Bearer test"})

    result = _decode(tools.handle_todoist({"action": "list_tasks", "query": "exercise"}))

    assert result["success"] is True
    assert result["match_mode"] == "semantic"
    assert [task["content"] for task in result["tasks"]] == ["Gym session", "Family handoff"]


def test_semantic_search_keeps_literal_matches_ranked_first(monkeypatch):
    payload = {
        "results": [
            {
                "id": "1",
                "content": "Exercise block",
                "description": "Mobility and cardio.",
                "labels": [],
            },
            {
                "id": "2",
                "content": "Gym session",
                "description": "Upper body day.",
                "labels": [],
            },
        ]
    }
    monkeypatch.setattr(tools, "_http_client", lambda: _FakeClient(payload))
    monkeypatch.setattr(tools, "_todoist_headers", lambda: {"Authorization": "Bearer test"})

    result = _decode(tools.handle_todoist({"action": "list_tasks", "query": "exercise"}))

    assert result["success"] is True
    assert result["tasks"][0]["content"] == "Exercise block"
    assert result["tasks"][1]["content"] == "Gym session"
    assert "Exercise block" in result["summary"]


def test_query_expansion_supports_related_home_terms():
    terms = tools._expand_query_terms("exercise")

    assert "gym" in terms
    assert "walking" in terms


def test_ranked_task_matches_include_match_reasons():
    tasks = [
        {
            "content": "Exercise block",
            "description": "Mobility and cardio.",
            "labels": ["health"],
        },
        {
            "content": "Dad block: no phone",
            "description": "Outside walk with your son after dinner.",
            "labels": [],
        },
    ]

    ranked = tools._rank_records(
        query="exercise",
        records=tasks,
        field_getter=lambda record: {
            "title": record.get("content", ""),
            "body": record.get("description", ""),
            "tags": record.get("labels", []),
            "state": "",
            "recency_hint": "",
        },
    )

    assert ranked[0]["record"]["content"] == "Exercise block"
    assert ranked[0]["why_matched"]
    assert ranked[1]["record"]["content"] == "Dad block: no phone"


def test_security_search_uses_ranked_event_lookup(monkeypatch):
    events = [
        {"ts": 1, "type": "todoist_read", "query": "exercise", "count": 2},
        {"ts": 2, "type": "twilio_send", "to": "+15555555555", "status": "queued"},
    ]
    monkeypatch.setattr(tools, "_load_recent_events", lambda limit=200: events[-limit:])

    result = _decode(tools.handle_security({"action": "search_events", "query": "exercise"}))

    assert result["success"] is True
    assert result["count"] == 1
    assert result["results"][0]["event"]["type"] == "todoist_read"
    assert result["results"][0]["why_matched"]


def test_clickup_ranking_prefers_exact_and_status_matches():
    tasks = [
        {
            "name": "Check ClickUp blockers",
            "description": "Review urgent dependencies before handoff.",
            "tags": [{"name": "ops"}],
            "status": {"status": "blocked"},
            "date_created": "2026-05-16",
            "date_updated": "2026-05-16",
        },
        {
            "name": "Weekly planning",
            "description": "General status review.",
            "tags": [],
            "status": {"status": "open"},
            "date_created": "2026-05-16",
            "date_updated": "2026-05-16",
        },
    ]

    ranked = tools._rank_records(
        query="blocker",
        records=tasks,
        field_getter=lambda task: {
            "title": task.get("name", ""),
            "body": task.get("description", ""),
            "tags": [tag.get("name", "") for tag in task.get("tags", [])],
            "state": (task.get("status") or {}).get("status", ""),
            "recency_hint": f"{task.get('date_created', '')} {task.get('date_updated', '')}",
        },
    )

    assert ranked[0]["record"]["name"] == "Check ClickUp blockers"
    assert "title:blocker" in ranked[0]["why_matched"] or "body:blocker" in ranked[0]["why_matched"]


def test_clickup_allowed_boundary_discovers_matching_folder_and_lists(monkeypatch):
    env_map = {
        "CLICKUP_ALLOWED_SPACE_ID": "90030081815",
        "CLICKUP_ALLOWED_FOLDER_NAME": "my stuff",
        "CLICKUP_API_TOKEN": "token",
    }
    original_env = tools._env
    monkeypatch.setattr(tools, "_env", lambda key: env_map.get(key, original_env(key)))

    class FakeClient:
        def get(self, url, headers=None, params=None):
            class Resp:
                def __init__(self, payload):
                    self._payload = payload

                def raise_for_status(self):
                    return None

                def json(self):
                    return self._payload

            if url.endswith("/space/90030081815/folder"):
                return Resp({"folders": [{"id": "f1", "name": "My Stuff"}, {"id": "f2", "name": "Work"}]})
            if url.endswith("/folder/f1/list"):
                return Resp({"lists": [{"id": "l1", "name": "Errands"}, {"id": "l2", "name": "Health"}]})
            raise AssertionError(url)

    boundary = tools._resolve_clickup_boundary(FakeClient())

    assert boundary["folder"]["id"] == "f1"
    assert {item["id"] for item in boundary["lists"]} == {"l1", "l2"}


def test_clickup_list_tasks_rejects_disallowed_list(monkeypatch):
    monkeypatch.setattr(
        tools,
        "_resolve_clickup_boundary",
        lambda client: {
            "space_id": "90030081815",
            "folder": {"id": "f1", "name": "My Stuff"},
            "lists": [{"id": "l1", "name": "Health"}],
            "list_ids": {"l1"},
        },
    )

    result = _decode(tools.handle_clickup({"action": "list_tasks", "list_id": "outside"}))

    assert "error" in result
    assert "outside the allowed clickup folder" in result["error"].lower()


def test_clickup_get_task_rejects_task_outside_allowed_folder(monkeypatch):
    monkeypatch.setattr(
        tools,
        "_resolve_clickup_boundary",
        lambda client: {
            "space_id": "90030081815",
            "folder": {"id": "f1", "name": "My Stuff"},
            "lists": [{"id": "l1", "name": "Health"}],
            "list_ids": {"l1"},
        },
    )

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def get(self, url, headers=None, params=None):
            class Resp:
                def raise_for_status(self):
                    return None

                def json(self):
                    return {"id": "t1", "list": {"id": "outside"}}

            return Resp()

    monkeypatch.setattr(tools, "_http_client", lambda: FakeClient())
    monkeypatch.setattr(tools, "_clickup_headers", lambda: {"Authorization": "token", "Content-Type": "application/json"})

    result = _decode(tools.handle_clickup({"action": "get_task", "task_id": "t1"}))

    assert "error" in result
    assert "outside the allowed clickup folder" in result["error"].lower()


def test_clickup_status_boundary_is_json_serializable(monkeypatch):
    monkeypatch.setattr(tools, "_env", lambda key: {"CLICKUP_API_TOKEN": "token", "CLICKUP_ALLOWED_SPACE_ID": "90030081815", "CLICKUP_ALLOWED_FOLDER_NAME": "Personal Life"}.get(key, ""))
    monkeypatch.setattr(
        tools,
        "_resolve_clickup_boundary",
        lambda client: {
            "space_id": "90030081815",
            "folder": {"id": "f1", "name": "Personal Life"},
            "lists": [{"id": "l1", "name": "Health"}],
            "list_ids": {"l1"},
        },
    )

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    monkeypatch.setattr(tools, "_http_client", lambda: FakeClient())

    result = _decode(tools.handle_clickup({"action": "status"}))

    assert result["success"] is True
    assert result["boundary"]["list_ids"] == ["l1"]


def test_security_explain_recent_action_summarizes_best_match(monkeypatch):
    events = [
        {"ts": 1, "type": "todoist_read", "action": "list_tasks", "query": "exercise", "count": 2, "match_mode": "semantic"},
        {"ts": 2, "type": "dangerous_command_approval_requested", "command": "cat ~/.hermes/.env", "description": "inspect env"},
    ]
    monkeypatch.setattr(tools, "_load_recent_events", lambda limit=200: events[-limit:])

    result = _decode(tools.handle_security({"action": "explain_recent_action", "query": "exercise"}))

    assert result["success"] is True
    assert result["event"]["type"] == "todoist_read"
    assert result["why_matched"]
    assert "exercise" in result["summary"].lower()


def test_todoist_response_includes_human_facing_match_summary(monkeypatch):
    payload = {
        "results": [
            {
                "id": "1",
                "content": "Family handoff",
                "description": "Non-workout evening default with gym conflict.",
                "labels": [],
            },
            {
                "id": "2",
                "content": "Dad block: no phone",
                "description": "Outside walk with your son after dinner.",
                "labels": [],
            },
        ]
    }
    monkeypatch.setattr(tools, "_http_client", lambda: _FakeClient(payload))
    monkeypatch.setattr(tools, "_todoist_headers", lambda: {"Authorization": "Bearer test"})

    result = _decode(tools.handle_todoist({"action": "list_tasks", "query": "exercise"}))

    assert result["success"] is True
    assert result["top_matches"][0]["title"] == "Family handoff"
    assert "closest" in result["summary"].lower() or "matched" in result["summary"].lower()


def test_security_search_includes_human_facing_summary(monkeypatch):
    events = [
        {"ts": 1, "type": "todoist_read", "action": "list_tasks", "query": "exercise", "count": 2},
        {"ts": 2, "type": "twilio_send", "to": "+15555555555", "status": "queued"},
    ]
    monkeypatch.setattr(tools, "_load_recent_events", lambda limit=200: events[-limit:])

    result = _decode(tools.handle_security({"action": "search_events", "query": "exercise"}))

    assert result["success"] is True
    assert result["summary"]
    assert "todoist_read" in result["summary"]


def test_focus_guard_pick_most_important_task_prefers_highest_todoist_priority_then_earliest_due():
    tasks = [
        {
            "id": "later-p4",
            "content": "Priority 4 but due later",
            "priority": 4,
            "due": {"date": "2026-05-20"},
        },
        {
            "id": "earlier-p4",
            "content": "Priority 4 and due earlier",
            "priority": 4,
            "due": {"date": "2026-05-18"},
        },
        {
            "id": "earliest-lower-priority",
            "content": "Priority 3 but due earliest",
            "priority": 3,
            "due": {"date": "2026-05-17"},
        },
    ]

    picked = tools._focus_guard_pick_most_important_task(tasks)

    assert picked["id"] == "earlier-p4"


def test_focus_guard_state_payload_surfaces_priority_pick_and_suspicious_tasks():
    tasks = [
        {
            "id": "ship",
            "content": "Ship draft",
            "priority": 4,
            "due": {"date": "2026-05-18"},
        },
        {
            "id": "avoidance",
            "content": "Research the perfect productivity app for three hours",
            "description": "Avoid the actual hard thing by endlessly optimizing the system.",
            "priority": 1,
            "due": {"date": "2026-05-19"},
        },
        {
            "id": "ambiguous",
            "content": "Organize notes for next week",
            "description": "Could be useful prep, could be a softer substitute for harder work.",
            "priority": 2,
            "due": {"date": "2026-05-20"},
        },
    ]

    payload = tools._focus_guard_state_payload(tasks=tasks, status="needs_focus")

    assert payload["most_important_task"]["id"] == "ship"
    assert payload["status"] == "needs_focus"
    assert isinstance(payload["suspicious_tasks"], list)

    def _task_id(item):
        task = item.get("task", item)
        return task["id"]

    def _classification(item):
        return item.get("classification", item)

    suspicious_by_id = {_task_id(item): _classification(item) for item in payload["suspicious_tasks"]}

    assert suspicious_by_id["avoidance"]["should_postpone"] is True
    assert "avoidance" in suspicious_by_id["avoidance"]["reason"].lower()
    assert suspicious_by_id["ambiguous"]["should_postpone"] is False
    assert suspicious_by_id["ambiguous"]["label"] == "suspicious"


def test_focus_guard_run_once_writes_state_logs_event_and_sends_telegram(monkeypatch):
    tasks = [
        {
            "id": "ship",
            "content": "Ship the draft",
            "priority": 4,
            "due": {"date": "2026-05-18"},
        },
        {
            "id": "avoidance",
            "content": "Research the perfect productivity app",
            "description": "Avoid the actual hard thing by endlessly optimizing the system.",
            "priority": 1,
            "due": {"date": "2026-05-19"},
        },
    ]
    writes = []
    events = []
    telegram_messages = []

    monkeypatch.setattr(tools, "_focus_guard_read_todoist_tasks", lambda **kwargs: tasks)
    monkeypatch.setattr(tools, "_focus_guard_write_state", lambda payload, path=tools.FOCUS_GUARD_STATE_PATH: writes.append(payload))
    monkeypatch.setattr(
        tools,
        "_focus_guard_append_event",
        lambda event_type, data, path=tools.FOCUS_GUARD_EVENT_LOG_PATH: events.append((event_type, data)),
    )
    monkeypatch.setattr(
        tools,
        "_focus_guard_send_telegram_message",
        lambda text, **kwargs: telegram_messages.append(text) or {"ok": True, "text": text},
    )

    result = tools._focus_guard_run_once()

    assert result["status"] == "needs_focus"
    assert result["most_important_task"]["id"] == "ship"
    assert result["suspicious_task_ids"] == ["avoidance"]
    assert result["notified_suspicious_task_ids"] == ["avoidance"]
    assert result["processed_suspicious_task_ids"] == ["avoidance"]
    assert result["generated_at"]
    assert writes and writes[0]["status"] == "needs_focus"
    assert writes[0]["most_important_task"]["id"] == "ship"
    assert writes[0]["processed_suspicious_task_ids"] == ["avoidance"]
    assert events == [
        (
            "focus_guard_run",
            {
                "status": "needs_focus",
                "task_count": 2,
                "most_important_task_id": "ship",
                "notified_suspicious_task_ids": ["avoidance"],
            },
        )
    ]
    assert len(telegram_messages) == 1
    assert "Ship the draft" in telegram_messages[0]
    assert "Research the perfect productivity app" in telegram_messages[0]


def test_focus_guard_run_once_persists_processed_ids_before_telegram(monkeypatch):
    tasks = [
        {
            "id": "ship",
            "content": "Ship the draft",
            "priority": 4,
            "due": {"date": "2026-05-18"},
        },
        {
            "id": "avoidance",
            "content": "Research the perfect productivity app",
            "description": "Avoid the actual hard thing by endlessly optimizing the system.",
            "priority": 1,
            "due": {"date": "2026-05-19"},
        },
    ]
    call_order = []

    monkeypatch.setattr(tools, "_focus_guard_read_todoist_tasks", lambda **kwargs: tasks)
    monkeypatch.setattr(
        tools,
        "_focus_guard_write_state",
        lambda payload, path=tools.FOCUS_GUARD_STATE_PATH: call_order.append(("write_state", payload["processed_suspicious_task_ids"])),
    )
    monkeypatch.setattr(
        tools,
        "_focus_guard_send_telegram_message",
        lambda text, **kwargs: call_order.append(("send_telegram", text)) or {"ok": True, "text": text},
    )
    monkeypatch.setattr(tools, "_focus_guard_append_event", lambda *args, **kwargs: None)

    tools._focus_guard_run_once()

    assert call_order[0] == ("write_state", [])
    assert call_order[1][0] == "send_telegram"
    assert call_order[2] == ("write_state", ["avoidance"])


def test_focus_guard_run_once_does_not_mark_processed_ids_when_telegram_fails(monkeypatch):
    tasks = [
        {
            "id": "ship",
            "content": "Ship the draft",
            "priority": 4,
            "due": {"date": "2026-05-18"},
        },
        {
            "id": "avoidance",
            "content": "Research the perfect productivity app",
            "description": "Avoid the actual hard thing by endlessly optimizing the system.",
            "priority": 1,
            "due": {"date": "2026-05-19"},
        },
    ]
    writes = []

    monkeypatch.setattr(tools, "_focus_guard_read_todoist_tasks", lambda **kwargs: tasks)
    monkeypatch.setattr(
        tools,
        "_focus_guard_write_state",
        lambda payload, path=tools.FOCUS_GUARD_STATE_PATH: writes.append(payload.copy()),
    )
    monkeypatch.setattr(
        tools,
        "_focus_guard_send_telegram_message",
        lambda text, **kwargs: (_ for _ in ()).throw(RuntimeError("telegram down")),
    )
    monkeypatch.setattr(tools, "_focus_guard_append_event", lambda *args, **kwargs: None)

    with pytest.raises(RuntimeError, match="telegram down"):
        tools._focus_guard_run_once()

    assert len(writes) == 1
    assert writes[0]["processed_suspicious_task_ids"] == []


def test_focus_guard_run_once_skips_already_processed_suspicious_tasks(monkeypatch):
    tasks = [
        {
            "id": "ship",
            "content": "Ship the draft",
            "priority": 4,
            "due": {"date": "2026-05-18"},
        },
        {
            "id": "avoidance",
            "content": "Research the perfect productivity app",
            "description": "Avoid the actual hard thing by endlessly optimizing the system.",
            "priority": 1,
            "due": {"date": "2026-05-19"},
        },
    ]
    writes = []
    events = []
    telegram_messages = []

    monkeypatch.setattr(tools, "_focus_guard_read_todoist_tasks", lambda **kwargs: tasks)
    monkeypatch.setattr(
        tools,
        "_focus_guard_read_state",
        lambda path=tools.FOCUS_GUARD_STATE_PATH: {"processed_suspicious_task_ids": ["avoidance"]},
    )
    monkeypatch.setattr(tools, "_focus_guard_write_state", lambda payload, path=tools.FOCUS_GUARD_STATE_PATH: writes.append(payload))
    monkeypatch.setattr(
        tools,
        "_focus_guard_append_event",
        lambda event_type, data, path=tools.FOCUS_GUARD_EVENT_LOG_PATH: events.append((event_type, data)),
    )
    monkeypatch.setattr(
        tools,
        "_focus_guard_send_telegram_message",
        lambda text, **kwargs: telegram_messages.append(text) or {"ok": True, "text": text},
    )

    result = tools._focus_guard_run_once()

    assert result["suspicious_task_ids"] == ["avoidance"]
    assert result["notified_suspicious_task_ids"] == []
    assert result["processed_suspicious_task_ids"] == ["avoidance"]
    assert result["generated_at"]
    assert writes and writes[0]["processed_suspicious_task_ids"] == ["avoidance"]
    assert events == [
        (
            "focus_guard_run",
            {
                "status": "needs_focus",
                "task_count": 2,
                "most_important_task_id": "ship",
                "notified_suspicious_task_ids": [],
            },
        )
    ]
    assert telegram_messages == []


def test_todoist_focus_guard_run_exposes_public_action_with_summary(monkeypatch):
    focus_guard_result = {
        "status": "needs_focus",
        "task_count": 2,
        "most_important_task": {
            "id": "ship",
            "content": "Ship the draft",
            "priority": 4,
        },
        "suspicious_task_ids": ["avoidance"],
        "notified_suspicious_task_ids": ["avoidance"],
    }
    seen = {}

    def fake_focus_guard_run_once(**kwargs):
        seen["filter"] = kwargs.get("filter")
        return focus_guard_result

    monkeypatch.setattr(tools, "_focus_guard_run_once", fake_focus_guard_run_once)

    result = _decode(tools.handle_todoist({"action": "focus_guard_run", "filter": "today"}))

    assert result["success"] is True
    assert result["action"] == "focus_guard_run"
    assert result["status"] == "needs_focus"
    assert result["task_count"] == 2
    assert result["most_important_task"]["id"] == "ship"
    assert result["suspicious_task_ids"] == ["avoidance"]
    assert "Ship the draft" in result["summary"]
    assert "2" in result["summary"]
    assert "1 suspicious" in result["summary"]
    assert seen["filter"] == "today"


def test_todoist_focus_guard_summary_counts_all_suspicious_tasks_found(monkeypatch):
    monkeypatch.setattr(
        tools,
        "_focus_guard_run_once",
        lambda **kwargs: {
            "status": "needs_focus",
            "task_count": 2,
            "most_important_task": {
                "id": "ship",
                "content": "Ship the draft",
                "priority": 4,
            },
            "suspicious_task_ids": ["avoidance"],
            "notified_suspicious_task_ids": [],
        },
    )

    result = _decode(tools.handle_todoist({"action": "focus_guard_run"}))

    assert result["suspicious_task_ids"] == ["avoidance"]
    assert result["notified_suspicious_task_ids"] == []
    assert "1 suspicious" in result["summary"]


def test_todoist_router_prefers_mcp_for_list_tasks(monkeypatch):
    calls = []
    monkeypatch.setenv("TODOIST_CONNECTOR_MODE", "mcp_primary")
    monkeypatch.setattr(tools, "_todoist_mcp_available", lambda: True)
    monkeypatch.setattr(
        tools,
        "_todoist_mcp_call",
        lambda action, payload: calls.append((action, payload)) or {
            "success": True,
            "tasks": [{"id": "mcp-1", "content": "MCP task"}],
            "summary": "MCP returned 1 task.",
        },
    )
    monkeypatch.setattr(
        tools,
        "_todoist_native_call",
        lambda args: (_ for _ in ()).throw(AssertionError("native should not be used")),
    )

    result = _decode(tools.handle_todoist({"action": "list_tasks", "filter": "today"}))

    assert result["success"] is True
    assert result["connector"] == "mcp"
    assert result["fallback_used"] is False
    assert result["tasks"][0]["content"] == "MCP task"
    assert calls == [("list_tasks", {"action": "list_tasks", "filter": "today"})]


def test_todoist_router_falls_back_to_native_when_mcp_fails(monkeypatch):
    monkeypatch.setenv("TODOIST_CONNECTOR_MODE", "mcp_primary")
    monkeypatch.setenv("TODOIST_MCP_REQUIRED", "false")
    monkeypatch.setattr(tools, "_todoist_mcp_available", lambda: True)
    monkeypatch.setattr(
        tools,
        "_todoist_mcp_call",
        lambda action, payload: (_ for _ in ()).throw(RuntimeError("mcp auth expired")),
    )
    monkeypatch.setattr(
        tools,
        "_todoist_native_call",
        lambda args: {
            "success": True,
            "action": args["action"],
            "count": 1,
            "tasks": [{"id": "native-1", "content": "Native task"}],
            "summary": "Native returned 1 task.",
        },
    )

    result = _decode(tools.handle_todoist({"action": "list_tasks", "filter": "today"}))

    assert result["success"] is True
    assert result["connector"] == "native_api"
    assert result["fallback_used"] is True
    assert "mcp auth expired" in result["primary_error"]
    assert result["tasks"][0]["content"] == "Native task"


def test_todoist_router_fails_closed_when_mcp_required_and_mcp_fails(monkeypatch):
    monkeypatch.setenv("TODOIST_CONNECTOR_MODE", "mcp_primary")
    monkeypatch.setenv("TODOIST_MCP_REQUIRED", "true")
    monkeypatch.setattr(tools, "_todoist_mcp_available", lambda: True)
    monkeypatch.setattr(
        tools,
        "_todoist_mcp_call",
        lambda action, payload: (_ for _ in ()).throw(RuntimeError("mcp auth expired")),
    )
    monkeypatch.setattr(
        tools,
        "_todoist_native_call",
        lambda args: (_ for _ in ()).throw(AssertionError("native fallback must be blocked when MCP is required")),
    )

    result = _decode(tools.handle_todoist({"action": "list_tasks", "filter": "today"}))

    assert result["success"] is False
    assert "mcp auth expired" in result["error"]


def test_todoist_mcp_primary_write_actions_still_require_approval(monkeypatch):
    monkeypatch.setenv("TODOIST_CONNECTOR_MODE", "mcp_primary")
    monkeypatch.setattr(tools, "_todoist_mcp_available", lambda: True)
    monkeypatch.setattr(
        tools,
        "_todoist_mcp_call",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("write actions must not bypass approvals through MCP")),
    )

    result = _decode(tools.handle_todoist({"action": "add_task", "content": "Review one admin loop"}))

    assert result["approval_required"] is True
    assert result["action"] == "add_task"
    assert result["connector"] == "native_api"


def test_focus_guard_uses_native_when_mcp_primary_is_enabled(monkeypatch):
    seen = {}
    monkeypatch.setenv("TODOIST_CONNECTOR_MODE", "mcp_primary")
    monkeypatch.setattr(tools, "_todoist_mcp_call", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("focus guard should not use MCP")))

    def fake_focus_guard_run_once(**kwargs):
        seen["filter"] = kwargs.get("filter")
        return {
            "status": "needs_focus",
            "task_count": 1,
            "most_important_task": {"id": "ship", "content": "Ship"},
            "suspicious_task_ids": [],
            "notified_suspicious_task_ids": [],
        }

    monkeypatch.setattr(tools, "_focus_guard_run_once", fake_focus_guard_run_once)

    result = _decode(tools.handle_todoist({"action": "focus_guard_run", "filter": "today"}))

    assert result["success"] is True
    assert result["connector"] == "native"
    assert result["connector_reason"] == "focus_guard_requires_native_shape"
    assert seen["filter"] == "today"


def test_todoist_mcp_payload_matches_actual_todoist_tools():
    assert tools._todoist_mcp_tool_candidates("list_tasks")[0] == "mcp_todoist_find_tasks"
    assert tools._todoist_mcp_payload(
        "list_tasks",
        {"filter": "today | overdue", "limit": 20},
        "mcp_todoist_find_tasks",
    ) == {"filter": "today | overdue", "limit": 20}
    assert tools._todoist_mcp_payload(
        "search_tasks",
        {"query": "invoice"},
        "mcp_todoist_find_tasks",
    ) == {"searchText": "invoice", "limit": 50}
    assert tools._todoist_mcp_payload(
        "add_task",
        {"content": "Ship thing", "description": "Context", "due_string": "tomorrow", "priority": 4},
        "mcp_todoist_add_tasks",
    ) == {"tasks": [{"content": "Ship thing", "description": "Context", "dueString": "tomorrow", "priority": "p1"}]}
    assert tools._todoist_mcp_payload("close_task", {"task_id": "abc"}, "mcp_todoist_complete_tasks") == {"ids": ["abc"]}


def test_todoist_mcp_call_normalizes_structured_content(monkeypatch):
    class FakeRegistry:
        def get_entry(self, name):
            return object() if name == "mcp_todoist_find_tasks" else None

        def dispatch(self, name, payload):
            assert payload == {"filter": "today", "limit": 50}
            return json.dumps({
                "structuredContent": {
                    "tasks": [{"id": "mcp-1", "content": "MCP task"}],
                    "totalCount": 1,
                    "hasMore": False,
                }
            })

    monkeypatch.setitem(sys.modules, "tools.registry", types.SimpleNamespace(registry=FakeRegistry()))

    result = tools._todoist_mcp_call("list_tasks", {"filter": "today"})

    assert result["success"] is True
    assert result["tasks"] == [{"id": "mcp-1", "content": "MCP task"}]
    assert result["count"] == 1
    assert result["total_count"] == 1
    assert result["mcp_tool"] == "mcp_todoist_find_tasks"


def test_todoist_mcp_call_discovers_tools_when_registry_is_cold(monkeypatch):
    class FakeRegistry:
        discovered = False

        def get_entry(self, name):
            return object() if self.discovered and name == "mcp_todoist_find_tasks" else None

        def dispatch(self, name, payload):
            return json.dumps({"structuredContent": {"tasks": []}})

    fake_registry = FakeRegistry()

    def fake_discover():
        fake_registry.discovered = True

    monkeypatch.setitem(sys.modules, "tools.registry", types.SimpleNamespace(registry=fake_registry))
    monkeypatch.setitem(sys.modules, "tools.mcp_tool", types.SimpleNamespace(discover_mcp_tools=fake_discover))

    result = tools._todoist_mcp_call("list_tasks", {"filter": "today"})

    assert result["success"] is True
    assert result["mcp_tool"] == "mcp_todoist_find_tasks"


def test_todoist_intelligence_uses_mcp_signals(monkeypatch):
    calls = []
    monkeypatch.setattr(tools, "_todoist_mcp_available", lambda: True)

    def fake_call(tool_name, payload=None):
        calls.append((tool_name, payload or {}))
        if tool_name == "mcp_todoist_find_tasks":
            return {
                "success": True,
                "structuredContent": {
                    "tasks": [
                        {"id": "t1", "content": "Ship invoice fix"},
                        {"id": "t2", "content": "Clear laundry"},
                    ]
                },
            }
        if tool_name == "mcp_todoist_find_activity" and (payload or {}).get("eventType") == "completed":
            return {"success": True, "structuredContent": {"events": [{"id": "a1", "eventType": "completed"}]}}
        if tool_name == "mcp_todoist_find_activity":
            return {"success": True, "structuredContent": {"events": [{"id": "a2", "eventType": "updated"}]}}
        if tool_name == "mcp_todoist_get_project_health":
            return {"success": True, "structuredContent": {"healthStatus": "AT_RISK"}}
        return {"success": True, "structuredContent": {}}

    monkeypatch.setattr(tools, "_todoist_mcp_tool_call", fake_call)

    result = _decode(tools.handle_todoist({
        "action": "intelligence",
        "filter": "today | overdue",
        "limit": 2,
        "project_id": "project-1",
    }))

    assert result["success"] is True
    assert result["connector"] == "mcp"
    assert result["active_tasks"]["count"] == 2
    assert result["activity"]["completed_count"] == 1
    assert result["activity"]["updated_count"] == 1
    assert result["project_health"]["structuredContent"]["healthStatus"] == "AT_RISK"
    assert "Ship invoice fix" in result["summary"]
    assert result["recommendations"]
    assert ("mcp_todoist_get_project_health", {"projectId": "project-1", "includeContext": False}) in calls


def test_todoist_intelligence_falls_back_to_native_when_mcp_unavailable(monkeypatch):
    monkeypatch.setenv("TODOIST_CONNECTOR_MODE", "mcp_primary")
    monkeypatch.setenv("TODOIST_MCP_REQUIRED", "false")
    monkeypatch.setattr(tools, "_todoist_mcp_intelligence", lambda args: (_ for _ in ()).throw(RuntimeError("mcp offline")))
    monkeypatch.setattr(
        tools,
        "_todoist_native_call",
        lambda args: {
            "success": True,
            "action": "list_tasks",
            "count": 1,
            "tasks": [{"id": "native-1", "content": "Native task"}],
            "summary": "Found 1 Todoist task(s).",
        },
    )

    result = _decode(tools.handle_todoist({"action": "intelligence", "filter": "today"}))

    assert result["success"] is True
    assert result["connector"] == "native_api"
    assert result["fallback_used"] is True
    assert result["primary_error"] == "mcp offline"
    assert "stable API-token path" in result["summary"]


def test_todoist_intelligence_uses_native_api_primary_without_touching_mcp(monkeypatch):
    monkeypatch.delenv("TODOIST_CONNECTOR_MODE", raising=False)
    monkeypatch.setattr(
        tools,
        "_todoist_mcp_intelligence",
        lambda args: (_ for _ in ()).throw(AssertionError("native primary should not touch hosted MCP")),
    )
    monkeypatch.setattr(
        tools,
        "_todoist_native_call",
        lambda args: {
            "success": True,
            "action": "list_tasks",
            "count": 1,
            "tasks": [{"id": "native-1", "content": "Native task"}],
            "summary": "Found 1 Todoist task(s).",
        },
    )

    result = _decode(tools.handle_todoist({"action": "intelligence", "filter": "today"}))

    assert result["success"] is True
    assert result["connector"] == "native_api"
    assert result["auth_model"] == "personal_api_token"
    assert result["fallback_used"] is False
    assert result["active_tasks"]["tasks"][0]["content"] == "Native task"


def test_todoist_status_native_primary_does_not_probe_mcp(monkeypatch):
    monkeypatch.delenv("TODOIST_CONNECTOR_MODE", raising=False)
    monkeypatch.setenv("TODOIST_MCP_REQUIRED", "false")
    monkeypatch.setattr(
        tools,
        "_todoist_native_call",
        lambda args: {
            "success": True,
            "configured": True,
            "token_masked": "abc...xyz",
            "connector": "native_api",
            "stable_primary": True,
            "auth_model": "personal_api_token",
        },
    )
    monkeypatch.setattr(
        tools,
        "_todoist_mcp_available",
        lambda: (_ for _ in ()).throw(AssertionError("status should not wake hosted MCP in native-primary mode")),
    )

    result = _decode(tools.handle_todoist({"action": "status"}))

    assert result["success"] is True
    assert result["connector_mode"] == "native_primary"
    assert result["mcp_available"] is None
    assert result["mcp_probe_skipped"] is True


def test_todoist_status_reports_mcp_as_active_primary_when_available(monkeypatch):
    monkeypatch.setenv("TODOIST_CONNECTOR_MODE", "mcp_primary")
    monkeypatch.setenv("TODOIST_MCP_REQUIRED", "true")
    monkeypatch.setattr(
        tools,
        "_todoist_native_call",
        lambda args: {
            "success": True,
            "configured": True,
            "token_masked": "abc...xyz",
            "connector": "native_api",
            "stable_primary": False,
            "auth_model": "personal_api_token",
        },
    )
    monkeypatch.setattr(tools, "_todoist_mcp_available", lambda: True)

    result = _decode(tools.handle_todoist({"action": "status"}))

    assert result["success"] is True
    assert result["connector_mode"] == "mcp_primary"
    assert result["mcp_primary_configured"] is True
    assert result["mcp_required"] is True
    assert result["mcp_available"] is True
    assert result["connector"] == "mcp"
    assert result["active_primary_connector"] == "mcp"
    assert result["native_status_connector"] == "native_api"


def _fake_operator_intelligence():
    return {
        "success": True,
        "action": "intelligence",
        "connector": "mcp",
        "active_tasks": {
            "count": 3,
            "tasks": [
                {
                    "id": "outing",
                    "content": "Plan simple outing",
                    "description": "",
                    "dueDate": "2026-05-01",
                    "priority": "p1",
                    "projectId": "personal",
                    "labels": [],
                },
                {
                    "id": "junk",
                    "content": "Do as soon as possible",
                    "description": "- Decrease costs\n- Pay taxes",
                    "dueDate": "2026-05-01",
                    "priority": "p4",
                    "projectId": "admin",
                    "labels": [],
                },
            ],
        },
        "activity": {
            "completed_count": 1,
            "updated_count": 4,
            "completed": [{"id": "done"}],
            "updated": [{"id": "up1"}, {"id": "up2"}, {"id": "up3"}, {"id": "up4"}],
        },
        "recommendations": ["Pick one visible task."],
        "errors": {},
    }


def test_operator_task_shape_detects_junk_drawer_task():
    shape = tools._operator_task_shape({
        "id": "junk",
        "content": "Do as soon as possible",
        "description": "- Pay taxes\n- Move number\n- Cancel software",
    })

    assert shape["shape_score"] < 0.65
    assert "vague_or_junk_drawer_title" in shape["issues"]
    assert "description_hides_subtasks" in shape["issues"]
    assert shape["repair_options"]


def test_runtime_operator_brief_builds_grounded_decision(monkeypatch):
    monkeypatch.setattr(tools, "_todoist_mcp_intelligence", lambda args: _fake_operator_intelligence())
    monkeypatch.setattr(tools, "_runtime_presence_status", lambda now=None: {
        "configured": True,
        "can_proactively_message": True,
        "confidence": 0.8,
        "summary": "present",
    })
    monkeypatch.setattr(tools, "_mood_router_status", lambda: {"last_mood": {"label": "neutral"}, "model_status": {}})
    monkeypatch.setattr(tools, "_focus_guard_read_state", lambda: {"status": "available"})
    monkeypatch.setattr(tools, "_runtime_live_watch_status", lambda: {"configured": True})
    monkeypatch.setattr(tools, "_adaptive_companion_now_local_hour", lambda: 13)
    monkeypatch.setattr(tools, "_common_sense_now", lambda: real_datetime.fromisoformat("2026-05-19T13:00:00-06:00"))

    result = _decode(tools.handle_runtime({"action": "operator_brief", "allow_message": True}))

    assert result["success"] is True
    assert result["mode"] in {"operator", "auditor"}
    assert result["should_message"] is True
    assert result["top_task"]["title"] == "Plan simple outing"
    assert "Plan simple outing" in result["telegram_message"]
    assert result["nudge_gate"]["passed"] is True
    assert result["anti_noise"]["todoist_noise_score"] > 0
    assert result["task_shapes"]


def test_operator_brief_suppresses_repeat_bad_nudge_for_same_task(monkeypatch):
    class _FixedDatetime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return real_datetime(2026, 5, 19, 19, 0, tzinfo=tz)

    monkeypatch.setattr(tools, "datetime", _FixedDatetime)
    monkeypatch.setattr(tools, "_todoist_mcp_intelligence", lambda args: _fake_operator_intelligence())
    monkeypatch.setattr(tools, "_runtime_presence_status", lambda now=None: {
        "configured": True,
        "can_proactively_message": True,
        "confidence": 0.8,
        "summary": "present",
    })
    monkeypatch.setattr(tools, "_mood_router_status", lambda: {"last_mood": {"label": "neutral"}, "model_status": {}})
    monkeypatch.setattr(tools, "_focus_guard_read_state", lambda: {"status": "available"})
    monkeypatch.setattr(tools, "_runtime_live_watch_status", lambda: {"configured": True})
    monkeypatch.setattr(tools, "_adaptive_companion_now_local_hour", lambda: 13)
    monkeypatch.setattr(tools, "_common_sense_now", lambda: real_datetime.fromisoformat("2026-05-19T13:00:00-06:00"))
    tools._operator_write_state(
        {
            "nudge_records": [
                {
                    "id": "nudge_recent_bad",
                    "task_id": "outing",
                    "task_title": "Plan simple outing",
                    "sent_at": "2026-05-19T18:15:00+00:00",
                    "outcome": "bad_nudge",
                    "user_action": "bad_nudge",
                }
            ]
        }
    )

    result = _decode(tools.handle_runtime({"action": "operator_brief", "allow_message": True}))

    assert result["success"] is True
    assert result["should_message"] is False
    assert result["nudge_gate"]["passed"] is False
    assert "bad nudge" in result["nudge_gate"]["reason"].lower()


def test_operator_brief_routes_low_value_repeated_evening_task_to_digest(monkeypatch):
    monkeypatch.setattr(tools, "_todoist_mcp_intelligence", lambda args: {
        **_fake_operator_intelligence(),
        "active_tasks": {
            "count": 1,
            "tasks": [
                {
                    "id": "outing",
                    "content": "Plan simple outing",
                    "description": "",
                    "dueDate": "2026-05-19",
                    "priority": "p2",
                    "projectId": "personal",
                    "labels": [],
                }
            ],
        },
    })
    monkeypatch.setattr(tools, "_runtime_presence_status", lambda now=None: {
        "configured": True,
        "can_proactively_message": True,
        "confidence": 0.88,
        "summary": "present",
    })
    monkeypatch.setattr(tools, "_mood_router_status", lambda: {"last_mood": {"label": "neutral"}, "model_status": {}})
    monkeypatch.setattr(tools, "_focus_guard_read_state", lambda: {"status": "available"})
    monkeypatch.setattr(tools, "_runtime_live_watch_status", lambda: {"configured": True})
    monkeypatch.setattr(tools, "_adaptive_companion_now_local_hour", lambda: 20)
    monkeypatch.setattr(tools, "_common_sense_now", lambda: real_datetime.fromisoformat("2026-05-19T20:15:00-06:00"))
    tools._operator_write_state({
        "nudge_records": [
            {
                "id": "n1",
                "task_id": "outing",
                "task_title": "Plan simple outing",
                "sent_at": "2026-05-19T23:40:00+00:00",
                "outcome": "defer_tomorrow",
                "user_action": "defer_tomorrow",
                "feedback_at": "2026-05-19T23:45:00+00:00",
                "message_class": "operator_brief",
            },
            {
                "id": "n2",
                "task_id": "outing",
                "task_title": "Plan simple outing",
                "sent_at": "2026-05-18T23:35:00+00:00",
                "outcome": "defer_tomorrow",
                "user_action": "defer_tomorrow",
                "feedback_at": "2026-05-18T23:40:00+00:00",
                "message_class": "operator_brief",
            },
        ]
    })

    result = _decode(tools.handle_runtime({"action": "operator_brief", "allow_message": True}))

    assert result["success"] is True
    assert result["adaptive_nudge"]["route"] == "digest"
    assert result["should_message"] is False
    assert result["adaptive_nudge"]["learned_score"] < 0.62
    assert "defer" in " ".join(result["adaptive_nudge"]["reasons"]).lower()


def test_operator_brief_prefers_ask_after_blocked_history(monkeypatch):
    monkeypatch.setattr(tools, "_todoist_mcp_intelligence", lambda args: {
        **_fake_operator_intelligence(),
        "active_tasks": {
            "count": 1,
            "tasks": [
                {
                    "id": "outing",
                    "content": "Plan simple outing",
                    "description": "",
                    "dueDate": "2026-05-19",
                    "priority": "p2",
                    "projectId": "personal",
                    "labels": [],
                }
            ],
        },
    })
    monkeypatch.setattr(tools, "_runtime_presence_status", lambda now=None: {
        "configured": True,
        "can_proactively_message": True,
        "confidence": 0.88,
        "summary": "present",
    })
    monkeypatch.setattr(tools, "_mood_router_status", lambda: {"last_mood": {"label": "neutral"}, "model_status": {}})
    monkeypatch.setattr(tools, "_focus_guard_read_state", lambda: {"status": "available"})
    monkeypatch.setattr(tools, "_runtime_live_watch_status", lambda: {"configured": True})
    monkeypatch.setattr(tools, "_adaptive_companion_now_local_hour", lambda: 14)
    monkeypatch.setattr(tools, "_common_sense_now", lambda: real_datetime.fromisoformat("2026-05-19T14:00:00-06:00"))
    tools._operator_write_state({
        "nudge_records": [
            {
                "id": "n1",
                "task_id": "outing",
                "task_title": "Plan simple outing",
                "sent_at": "2026-05-19T18:20:00+00:00",
                "outcome": "blocked",
                "user_action": "blocked",
                "feedback_at": "2026-05-19T18:25:00+00:00",
                "message_class": "operator_brief",
            },
            {
                "id": "n2",
                "task_id": "outing",
                "task_title": "Plan simple outing",
                "sent_at": "2026-05-18T18:20:00+00:00",
                "outcome": "blocked",
                "user_action": "blocked",
                "feedback_at": "2026-05-18T18:25:00+00:00",
                "message_class": "operator_brief",
            },
        ]
    })

    result = _decode(tools.handle_runtime({"action": "operator_brief", "allow_message": True}))

    assert result["success"] is True
    assert result["adaptive_nudge"]["route"] == "ask"
    assert result["should_message"] is True
    assert result["adaptive_nudge"]["learned_score"] >= 0.4
    assert "blocked" in " ".join(result["adaptive_nudge"]["reasons"]).lower()
    assert "what is blocked" in result["telegram_message"].lower()


def test_operator_brief_keeps_instruct_route_for_clean_high_value_case(monkeypatch):
    monkeypatch.setattr(tools, "_todoist_mcp_intelligence", lambda args: _fake_operator_intelligence())
    monkeypatch.setattr(tools, "_runtime_presence_status", lambda now=None: {
        "configured": True,
        "can_proactively_message": True,
        "confidence": 0.9,
        "summary": "present",
    })
    monkeypatch.setattr(tools, "_mood_router_status", lambda: {"last_mood": {"label": "neutral"}, "model_status": {}})
    monkeypatch.setattr(tools, "_focus_guard_read_state", lambda: {"status": "available"})
    monkeypatch.setattr(tools, "_runtime_live_watch_status", lambda: {"configured": True})
    monkeypatch.setattr(tools, "_adaptive_companion_now_local_hour", lambda: 10)
    monkeypatch.setattr(tools, "_common_sense_now", lambda: real_datetime.fromisoformat("2026-05-19T10:00:00-06:00"))

    result = _decode(tools.handle_runtime({"action": "operator_brief", "allow_message": True}))

    assert result["success"] is True
    assert result["adaptive_nudge"]["route"] == "instruct"
    assert result["should_message"] is True
    assert result["adaptive_nudge"]["learned_score"] >= 0.62


def test_operating_snapshot_exposes_adaptive_nudge_learning_slice():
    tools._operator_write_state({
        "nudge_records": [
            {
                "id": "n1",
                "task_id": "outing",
                "task_title": "Plan simple outing",
                "sent_at": "2026-05-19T18:20:00+00:00",
                "outcome": "blocked",
                "user_action": "blocked",
                "feedback_at": "2026-05-19T18:25:00+00:00",
                "message_class": "operator_brief",
            },
            {
                "id": "n2",
                "task_id": "laundry",
                "task_title": "Laundry check",
                "sent_at": "2026-05-19T02:20:00+00:00",
                "outcome": "defer_tomorrow",
                "user_action": "defer_tomorrow",
                "feedback_at": "2026-05-19T02:25:00+00:00",
                "message_class": "operator_brief",
            },
        ]
    })

    result = _decode(tools.handle_runtime({"action": "operating_snapshot"}))

    assert result["success"] is True
    assert result["snapshot"]["adaptive_nudge"]["record_count"] == 2
    assert result["snapshot"]["adaptive_nudge"]["outcome_counts"]["blocked"] == 1
    assert result["snapshot"]["adaptive_nudge"]["outcome_counts"]["defer_tomorrow"] == 1
    assert "time_buckets" in result["snapshot"]["adaptive_nudge"]


def test_runtime_agi_operator_cycle_builds_evidence_backed_one_move(monkeypatch):
    monkeypatch.setattr(tools, "_todoist_mcp_intelligence", lambda args: _fake_operator_intelligence())
    monkeypatch.setattr(tools, "_runtime_presence_status", lambda now=None: {
        "configured": True,
        "can_proactively_message": True,
        "confidence": 0.8,
        "summary": "present",
    })
    monkeypatch.setattr(tools, "_mood_router_status", lambda: {"last_mood": {"label": "neutral"}, "model_status": {}})
    monkeypatch.setattr(tools, "_focus_guard_read_state", lambda: {"status": "available"})
    monkeypatch.setattr(tools, "_runtime_live_watch_status", lambda: {"configured": True})
    monkeypatch.setattr(tools, "_adaptive_companion_now_local_hour", lambda: 13)
    monkeypatch.setattr(tools, "_common_sense_now", lambda: real_datetime.fromisoformat("2026-05-19T13:00:00-06:00"))

    result = _decode(tools.handle_runtime({"action": "agi_operator_cycle", "allow_message": True}))

    assert result["success"] is True
    assert result["action"] == "agi_operator_cycle"
    assert result["autonomy"]["level"] == 2
    assert result["decision"]["best_move"] in {"send_operator_note", "log_operator_note"}
    assert result["one_move"]["task"] == "Plan simple outing"
    assert result["one_move"]["time_box"] == "10 minutes"
    assert result["beliefs"][0]["confidence"] > 0
    assert result["beliefs"][0]["evidence"]
    assert result["goal_graph"]["active_goal"]
    assert "todoist" in result["tool_plan"]["tools_needed"]
    assert result["self_audit"]["evidence_quality"] in {"medium", "high"}
    assert set(result["internal_council"]) >= {"operator", "strategist", "auditor", "coach", "security", "shield", "toolsmith"}
    assert "Plan simple outing" in result["telegram_message"]


def test_agi_operator_cycle_stays_quiet_when_evidence_or_presence_is_weak(monkeypatch):
    monkeypatch.setattr(tools, "_todoist_mcp_intelligence", lambda args: _fake_operator_intelligence())
    monkeypatch.setattr(tools, "_runtime_presence_status", lambda now=None: {
        "configured": True,
        "can_proactively_message": False,
        "confidence": 0.15,
    })
    monkeypatch.setattr(tools, "_mood_router_status", lambda: {"last_mood": {"label": "neutral"}, "model_status": {}})
    monkeypatch.setattr(tools, "_focus_guard_read_state", lambda: {"status": "available"})
    monkeypatch.setattr(tools, "_runtime_live_watch_status", lambda: {"configured": True})
    monkeypatch.setattr(tools, "_adaptive_companion_now_local_hour", lambda: 13)

    result = _decode(tools.handle_runtime({"action": "agi_operator_cycle", "allow_message": True}))

    assert result["success"] is True
    assert result["mode"] == "shield"
    assert result["decision"]["best_move"] == "stay_quiet"
    assert result["should_act"] is False
    assert result["approval"]["required"] is False
    assert result["stay_quiet"]["reason"]


def test_agi_tool_plan_stays_hermes_todoist_personal_without_business_assumptions():
    result = _decode(tools.handle_runtime({
        "action": "agi_operator_cycle",
        "request": "Help me decide what personal task to do next without making business assumptions",
        "allow_message": False,
    }))

    assert result["success"] is True
    serialized = json.dumps(result).lower()
    forbidden_terms = [
        "dialpad",
        "gohighlevel",
        "bookingkoala",
        "missive",
        "nuelink",
        "marky",
        "duty cleaners",
        "customer-facing",
        "crm",
    ]
    assert result["tool_plan"]["tools_needed"] == ["hermes", "todoist"]
    assert result["goal_graph"]["active_goal"] in {"Reduce personal cognitive load", "Make one clear personal next move"}
    assert not any(term in serialized for term in forbidden_terms)


def test_operator_brief_shield_stays_quiet_when_presence_is_weak(monkeypatch):
    monkeypatch.setattr(tools, "_todoist_mcp_intelligence", lambda args: _fake_operator_intelligence())
    monkeypatch.setattr(tools, "_runtime_presence_status", lambda now=None: {
        "configured": True,
        "can_proactively_message": False,
        "confidence": 0.2,
    })
    monkeypatch.setattr(tools, "_mood_router_status", lambda: {"last_mood": {"label": "neutral"}, "model_status": {}})
    monkeypatch.setattr(tools, "_focus_guard_read_state", lambda: {"status": "available"})
    monkeypatch.setattr(tools, "_runtime_live_watch_status", lambda: {"configured": True})
    monkeypatch.setattr(tools, "_adaptive_companion_now_local_hour", lambda: 13)

    result = _decode(tools.handle_runtime({"action": "operator_brief", "allow_message": True}))

    assert result["mode"] == "shield"
    assert result["should_message"] is False
    assert result["nudge_gate"]["passed"] is False


def test_operator_weekly_review_uses_evidence_only():
    state = {
        "sticky_tasks": {
            "outing": {"task_id": "outing", "title": "Plan simple outing", "avoidance_score": 0.9}
        },
        "nudge_records": [
            {"task_id": "outing", "outcome": "ignored"},
            {"task_id": "taxes", "outcome": "completed_or_removed"},
        ],
        "daily_narrative": {"2026-05-18": {"main_lesson": "Admin needs repair"}},
    }
    tools._operator_write_state(state)
    tools._append_jsonl(tools.OPERATOR_BRIEF_LOG_PATH, {"summary": "Operator brief: noise=getting_noisy"})

    result = _decode(tools.handle_runtime({"action": "weekly_review"}))

    assert result["success"] is True
    assert result["sticky_tasks"][0]["title"] == "Plan simple outing"
    assert result["nudge_outcomes"]["ignored"] == 1
    assert result["top_improvements"]
    assert "evidence" in result["evidence_policy"].lower()


def _fake_lint_intelligence():
    return {
        "success": True,
        "action": "intelligence",
        "connector": "mcp",
        "active_tasks": {
            "count": 7,
            "tasks": [
                {
                    "id": "launch-1",
                    "content": "Life OS Morning Launch",
                    "description": "No phone first. Open Today and start the first real task.",
                    "due": {"date": "2026-05-19", "is_recurring": True},
                    "priority": "p1",
                    "labels": ["life_os"],
                },
                {
                    "id": "launch-2",
                    "content": "Life OS Morning Launch",
                    "description": "Duplicate morning routine.",
                    "due": {"date": "2026-05-19", "is_recurring": True},
                    "priority": "p1",
                    "labels": ["life_os"],
                },
                {
                    "id": "junk",
                    "content": "Do as soon as possible",
                    "description": "- Decrease Dialpad costs\n- Move QUO number to Dialpad\n- Pay remaining taxes",
                    "due": {"date": "2026-05-16"},
                    "priority": "p4",
                    "labels": [],
                },
                {
                    "id": "reference",
                    "content": "Read Life OS identity statement",
                    "description": "Reference material, not a next action.",
                    "due": {"date": "2026-05-19"},
                    "priority": "p2",
                    "labels": ["reference"],
                },
                {
                    "id": "incomplete",
                    "content": "Pay remaining taxes for business within",
                    "description": "",
                    "due": {"date": "2026-05-18"},
                    "priority": "p3",
                    "labels": [],
                },
                {
                    "id": "laundry",
                    "content": "Laundry check",
                    "description": "",
                    "due": {"date": "2026-05-19"},
                    "priority": "p2",
                    "labels": [],
                },
                {
                    "id": "workout",
                    "content": "Finish lower A workout",
                    "description": "",
                    "due": {"date": "2026-05-19"},
                    "priority": "p2",
                    "labels": [],
                },
            ],
        },
        "activity": {"completed_count": 0, "updated_count": 0, "completed": [], "updated": []},
        "recommendations": [],
        "errors": {},
    }


def test_runtime_todoist_lint_report_detects_repair_queue_issues(monkeypatch):
    monkeypatch.setattr(tools, "_todoist_mcp_intelligence", lambda args: _fake_lint_intelligence())

    result = _decode(tools.handle_runtime({"action": "todoist_lint_report", "create_approval": False}))

    assert result["success"] is True
    assert result["action"] == "todoist_lint_report"
    kinds = {proposal["kind"] for proposal in result["proposals"]}
    assert {
        "duplicate_recurring_task",
        "junk_drawer_task",
        "reference_as_task",
        "incomplete_title",
        "vague_task",
    }.issubset(kinds)
    assert result["counts"]["proposals"] >= 5
    assert result["source"]["connector"] == "mcp"
    assert "Todoist repair report" in result["telegram_message"]

    for proposal in result["proposals"]:
        assert proposal["problem"]
        assert proposal["evidence"]
        assert proposal["suggested_title"]
        assert "due_date_change" in proposal
        assert proposal["risk"]
        assert proposal["approval_needed"] is True
        assert proposal["actions"] == ["approve", "edit", "skip", "explain"]


def test_runtime_todoist_lint_report_creates_draft_only_approval(monkeypatch):
    monkeypatch.setattr(tools, "_todoist_mcp_intelligence", lambda args: _fake_lint_intelligence())

    result = _decode(tools.handle_runtime({"action": "todoist_lint_report", "create_approval": True}))

    assert result["approval_required"] is True
    assert result["action"] == "todoist_lint_report"
    assert result["report"]["counts"]["proposals"] >= 5
    assert result["request_id"]
    pending = _decode(tools.handle_security({"action": "list_pending"}))["pending"]
    assert pending[0]["tool"] == "personal_runtime"
    assert pending[0]["action"] == "apply_todoist_repair_report"
    assert pending[0]["payload"]["action"] == "todoist_repair_apply"


def test_todoist_repair_approval_records_queue_without_editing_todoist(monkeypatch):
    monkeypatch.setattr(tools, "_todoist_mcp_intelligence", lambda args: _fake_lint_intelligence())
    edits = []
    monkeypatch.setattr(tools, "_execute_todoist", lambda payload: edits.append(payload) or {"success": True})

    created = _decode(tools.handle_runtime({"action": "todoist_lint_report", "create_approval": True}))
    approved = _decode(tools.handle_security({"action": "approve_request", "request_id": created["request_id"]}))

    assert approved["success"] is True
    assert approved["result"]["success"] is True
    assert approved["result"]["applied"] is False
    assert approved["result"]["report"]["counts"]["proposals"] >= 5
    assert edits == []
    saved = json.loads(tools.TODOIST_REPAIR_QUEUE_PATH.read_text(encoding="utf-8"))
    assert saved["approved_at"]
    assert saved["status"] == "approved_draft_only"
    assert saved["report"]["proposals"]


def test_common_sense_marks_breakfast_missed_at_night():
    now = real_datetime.fromisoformat("2026-05-19T19:00:00-06:00")
    decision = tools._common_sense_task_decision(
        {
            "id": "breakfast",
            "content": "Eat eggs and vegetables for breakfast",
            "description": "",
            "labels": [],
        },
        now=now,
    )

    assert decision["task_type"] == "meal_breakfast"
    assert decision["original_action_valid"] is False
    assert decision["current_status"] == "missed_window"
    assert decision["best_mode"] == "log_or_recover"
    assert "Breakfast window passed" in decision["telegram_text"]
    assert "eat breakfast now" not in decision["telegram_text"].lower()
    assert decision["buttons"] == ["Ate it", "Ate something else", "Skipped", "Prep tomorrow", "Change task"]
    assert decision["assumption_ledger"]
    assert decision["known_unknowns"]


def test_common_sense_converts_business_contact_after_hours_to_draft_or_schedule():
    now = real_datetime.fromisoformat("2026-05-18T20:45:00-06:00")
    decision = tools._common_sense_task_decision(
        {
            "id": "va",
            "content": "Follow up with VA and cleaners",
            "description": "Ask staff what is still open.",
            "labels": [],
        },
        now=now,
    )

    assert decision["task_type"] == "business_contact"
    assert decision["original_action_valid"] is False
    assert decision["current_status"] == "external_contact_window_closed"
    assert decision["best_mode"] == "draft_or_schedule"
    assert "Business contact window is closed" in decision["telegram_text"]
    assert "message the va now" not in decision["telegram_text"].lower()
    assert "Draft tomorrow" in decision["buttons"]
    assert decision["business_hours"]["open_now"] is False
    assert decision["business_hours"]["next_open_local"].startswith("2026-05-19T08:00")


def test_common_sense_converts_morning_launch_at_night_to_tomorrow_setup():
    now = real_datetime.fromisoformat("2026-05-19T21:00:00-06:00")
    decision = tools._common_sense_task_decision(
        {
            "id": "launch",
            "content": "Life OS Morning Launch",
            "description": "Open Today and start first real task.",
            "labels": ["life_os"],
        },
        now=now,
    )

    assert decision["task_type"] == "morning_routine"
    assert decision["original_action_valid"] is False
    assert decision["best_mode"] == "tomorrow_setup"
    assert "Morning Launch is no longer useful as a morning routine tonight" in decision["telegram_text"]
    assert "do morning launch" not in decision["telegram_text"].lower()
    assert "Set tomorrow" in decision["buttons"]


def test_common_sense_keeps_laundry_recoverable_in_evening():
    now = real_datetime.fromisoformat("2026-05-19T20:40:00-06:00")
    decision = tools._common_sense_task_decision(
        {
            "id": "laundry",
            "content": "Laundry check",
            "description": "",
            "labels": [],
        },
        now=now,
    )

    assert decision["task_type"] == "laundry_home"
    assert decision["original_action_valid"] is True
    assert decision["current_status"] == "actionable_now"
    assert decision["best_mode"] == "small_home_action"
    assert "if you're home" in decision["telegram_text"]
    assert decision["buttons"] == ["Done", "Not home", "Defer", "No laundry"]


def test_common_sense_blocks_family_transition_during_quiet_hours():
    now = real_datetime.fromisoformat("2026-05-19T02:35:00-06:00")
    decision = tools._common_sense_task_decision(
        {
            "id": "dad",
            "content": "Dad block: no phone",
            "description": "Be present with family.",
            "labels": [],
        },
        now=now,
    )

    assert decision["task_type"] == "family_transition"
    assert decision["original_action_valid"] is False
    assert decision["current_status"] == "quiet_hours_or_sleep_likely"
    assert decision["best_mode"] == "quiet_or_tomorrow"
    assert decision["should_message"] is False
    assert "quiet hours" in decision["telegram_text"].lower()
    assert "actionable now" not in decision["telegram_text"].lower()


def test_common_sense_repairs_junk_drawer_instead_of_nudging():
    now = real_datetime.fromisoformat("2026-05-19T14:00:00-06:00")
    decision = tools._common_sense_task_decision(
        {
            "id": "junk",
            "content": "Do as soon as possible",
            "description": "- Trim costs\n- Move phone number\n- Pay remaining taxes",
            "labels": [],
        },
        now=now,
    )

    assert decision["task_type"] == "junk_drawer"
    assert decision["original_action_valid"] is False
    assert decision["current_status"] == "needs_task_repair"
    assert decision["best_mode"] == "repair_missing_info"
    assert decision["message_type"] == "repair_request"
    assert "not executable" in decision["telegram_text"]
    assert "spend 10 minutes" not in decision["telegram_text"].lower()


def test_common_sense_reference_task_is_not_an_expired_execution_task():
    now = real_datetime.fromisoformat("2026-05-19T20:45:00-06:00")
    decision = tools._common_sense_task_decision(
        {
            "id": "rules",
            "content": "Read final program rules",
            "description": "",
            "labels": ["reference"],
        },
        now=now,
    )

    assert decision["task_type"] == "reference"
    assert decision["original_action_valid"] is False
    assert decision["current_status"] == "probably_irrelevant_now"
    assert decision["message_type"] == "log_only"
    assert decision["should_message"] is False
    assert "reference/setup material" in decision["telegram_text"]


def test_common_sense_reference_title_wins_over_workout_description():
    now = real_datetime.fromisoformat("2026-05-19T20:45:00-06:00")
    decision = tools._common_sense_task_decision(
        {
            "id": "rules",
            "content": "Read final program rules",
            "description": "Lower A workout rules and upper/lower program notes.",
            "labels": [],
        },
        now=now,
    )

    assert decision["task_type"] == "reference"
    assert decision["current_status"] == "probably_irrelevant_now"
    assert decision["message_type"] == "log_only"


def test_arrive_briefing_labels_future_timed_tasks_as_upcoming(monkeypatch):
    fixed_now = real_datetime.fromisoformat("2026-05-21T16:37:00-06:00")

    class _FixedDatetime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return fixed_now.replace(tzinfo=None)
            return fixed_now.astimezone(tz)

    monkeypatch.setattr(tools, "datetime", _FixedDatetime)
    monkeypatch.setattr(tools, "_runtime_local_tz", lambda: fixed_now.tzinfo)

    briefing = tools._runtime_build_arrive_briefing(
        [
            {
                "id": "workout",
                "content": "Upper B workout (Thursday)",
                "description": "",
                "labels": [],
                "due": {"datetime": "2026-05-21T18:00:00-06:00", "string": "Thu 6:00 PM"},
            }
        ],
        {},
    )

    assert "Upper B workout" in briefing
    assert "starts in" in briefing
    assert "passed" not in briefing.lower()
    assert "knock it out before you get comfortable" not in briefing
    assert "Welcome Home!" in briefing


def test_leave_briefing_uses_policy_copy_not_old_small_wins(monkeypatch):
    fixed_now = real_datetime.fromisoformat("2026-05-21T18:15:00-06:00")

    class _FixedDatetime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return fixed_now.replace(tzinfo=None)
            return fixed_now.astimezone(tz)

    monkeypatch.setattr(tools, "datetime", _FixedDatetime)
    monkeypatch.setattr(tools, "_runtime_local_tz", lambda: fixed_now.tzinfo)

    briefing = tools._runtime_build_leave_briefing([
        {
            "id": "errand",
            "content": "Pick up eggs",
            "description": "",
            "labels": ["errands"],
            "due": {"date": "2026-05-21", "string": "today"},
        }
    ])

    assert "I received an away/leaving signal" in briefing
    assert "Pick up eggs" in briefing
    assert "small wins add up" not in briefing


def _fake_common_sense_intelligence():
    return {
        "success": True,
        "action": "intelligence",
        "connector": "mcp",
        "active_tasks": {
            "count": 7,
            "tasks": [
                {"id": "launch", "content": "Life OS Morning Launch", "description": "", "labels": ["life_os"]},
                {"id": "breakfast", "content": "Eat eggs and vegetables for breakfast", "description": "", "labels": []},
                {"id": "biz", "content": "Follow up with VA and cleaners", "description": "", "labels": []},
                {"id": "laundry", "content": "Laundry check", "description": "", "labels": []},
                {"id": "reset", "content": "Evening visible reset", "description": "", "labels": []},
                {"id": "rules", "content": "Read final program rules", "description": "", "labels": ["reference"]},
                {"id": "tax", "content": "Pay remaining taxes for business within", "description": "", "labels": []},
            ],
        },
        "activity": {"completed_count": 0, "updated_count": 0, "completed": [], "updated": []},
        "recommendations": [],
        "errors": {},
    }


def test_runtime_common_sense_decision_builds_late_day_salvage(monkeypatch):
    monkeypatch.setattr(tools, "_todoist_mcp_intelligence", lambda args: _fake_common_sense_intelligence())
    monkeypatch.setattr(tools, "_common_sense_now", lambda: real_datetime.fromisoformat("2026-05-19T20:45:00-06:00"))

    result = _decode(tools.handle_runtime({"action": "common_sense_decision", "limit": 20}))

    assert result["success"] is True
    assert result["action"] == "common_sense_decision"
    assert result["operating_state"]["time"]["local"].startswith("2026-05-19T20:45")
    assert result["summary"]["best_move"]["task_title"] in {"Laundry check", "Evening visible reset"}
    assert "Life OS Morning Launch" in result["late_day_salvage"]["expired"]
    assert "Eat eggs and vegetables for breakfast" in result["late_day_salvage"]["expired"]
    assert "Follow up with VA and cleaners" in result["late_day_salvage"]["closed"]
    assert "Read final program rules" in result["late_day_salvage"]["not_worth_interrupting"]
    assert result["summary"]["should_message"] is True
    assert result["summary"]["message_type"] in {"execution_nudge", "day_salvage"}


def test_runtime_operator_brief_includes_common_sense_and_blocks_expired_task(monkeypatch):
    monkeypatch.setattr(
        tools,
        "_todoist_mcp_intelligence",
        lambda args: {
            **_fake_operator_intelligence(),
            "active_tasks": {
                "count": 1,
                "tasks": [
                    {
                        "id": "breakfast",
                        "content": "Eat eggs and vegetables for breakfast",
                        "description": "",
                        "dueDate": "2026-05-19",
                        "priority": "p1",
                        "labels": [],
                    }
                ],
            },
        },
    )
    monkeypatch.setattr(tools, "_runtime_presence_status", lambda now=None: {
        "configured": True,
        "can_proactively_message": True,
        "confidence": 0.8,
        "summary": "present",
    })
    monkeypatch.setattr(tools, "_mood_router_status", lambda: {"last_mood": {"label": "neutral"}, "model_status": {}})
    monkeypatch.setattr(tools, "_focus_guard_read_state", lambda: {"status": "available"})
    monkeypatch.setattr(tools, "_runtime_live_watch_status", lambda: {"configured": True})
    monkeypatch.setattr(tools, "_adaptive_companion_now_local_hour", lambda: 19)
    monkeypatch.setattr(tools, "_common_sense_now", lambda: real_datetime.fromisoformat("2026-05-19T19:00:00-06:00"))

    result = _decode(tools.handle_runtime({"action": "operator_brief", "allow_message": True}))

    assert result["success"] is True
    assert result["common_sense"]["best_decision"]["task_type"] == "meal_breakfast"
    assert result["common_sense"]["best_decision"]["original_action_valid"] is False
    assert result["should_message"] is False
    assert "Common sense blocked original task" in result["nudge_gate"]["reason"]
    assert "Breakfast window passed" in result["telegram_message"]


def test_runtime_operator_brief_send_telegram_records_nudge_receipt_with_buttons(monkeypatch):
    monkeypatch.setattr(tools, "_todoist_mcp_intelligence", lambda args: _fake_operator_intelligence())
    monkeypatch.setattr(tools, "_runtime_presence_status", lambda now=None: {
        "configured": True,
        "can_proactively_message": True,
        "confidence": 0.8,
        "summary": "present",
    })
    monkeypatch.setattr(tools, "_mood_router_status", lambda: {"last_mood": {"label": "neutral"}, "model_status": {}})
    monkeypatch.setattr(tools, "_focus_guard_read_state", lambda: {"status": "available"})
    monkeypatch.setattr(tools, "_runtime_live_watch_status", lambda: {"configured": True})
    monkeypatch.setattr(tools, "_adaptive_companion_now_local_hour", lambda: 13)
    monkeypatch.setattr(tools, "_common_sense_now", lambda: real_datetime.fromisoformat("2026-05-19T13:00:00-06:00"))
    monkeypatch.setattr(tools, "_telegram_messages_allowed_now", lambda now_hour=None: True)
    monkeypatch.setattr(
        tools,
        "_focus_guard_send_telegram_message",
        lambda text, **kwargs: {"ok": True, "result": {"message_id": 99}, "text": text, "buttons": kwargs.get("buttons")},
    )

    result = _decode(tools.handle_runtime({"action": "operator_brief", "allow_message": True, "send_telegram": True}))
    state = tools._read_json(tools.OPERATOR_STATE_PATH, {})
    receipt = state["nudge_records"][-1]

    assert result["sent"] is True
    assert receipt["message_id"] == "99"
    assert receipt["buttons"]
    assert "Done" in receipt["buttons"]
    assert receipt["message_class"] == "operator_brief"
    assert receipt["user_action"] is None


def test_runtime_live_watch_includes_operator_brief(monkeypatch):
    monkeypatch.setattr(tools, "_focus_guard_run_once", lambda filter=None: {
        "status": "needs_focus",
        "task_count": 1,
        "most_important_task": {"id": "outing", "content": "Plan simple outing"},
        "suspicious_task_ids": [],
        "notified_suspicious_task_ids": [],
    })
    monkeypatch.setattr(tools, "handle_adaptive_companion", lambda args: json.dumps({"success": True, "sent": False, "reason": "no_trigger"}))
    monkeypatch.setattr(tools, "_runtime_live_watch_update_status_message", lambda payload: {"ok": True})
    monkeypatch.setattr(tools, "_operator_brief", lambda args: {"success": True, "action": "operator_brief", "mode": "operator"})
    monkeypatch.setattr(tools, "_agi_operator_cycle", lambda args: {
        "success": True,
        "action": "agi_operator_cycle",
        "mode": "operator",
        "decision": {"best_move": "log_operator_note"},
    })

    result = _decode(tools.handle_runtime({"action": "live_watch", "filter": "today | overdue"}))

    assert result["success"] is True
    assert result["operator_brief"]["mode"] == "operator"
    assert result["agi_operator_cycle"]["decision"]["best_move"] == "log_operator_note"


def test_runtime_live_watch_status_exposes_agi_cycle():
    tools._write_json(tools.LIVE_WATCH_STATE_PATH, {
        "ran_at": "2026-05-19T12:00:00+00:00",
        "filter": "today | overdue",
        "focus_guard": {"status": "available"},
        "adaptive_companion": {"success": True, "sent": False, "reason": "no_trigger"},
        "operator_brief": {"success": True, "mode": "operator"},
        "agi_operator_cycle": {
            "success": True,
            "mode": "operator",
            "decision": {"best_move": "stay_quiet"},
        },
        "status_message": {"ok": True},
    })

    result = _decode(tools.handle_runtime({"action": "live_watch_status"}))

    assert result["success"] is True
    assert result["configured"] is True
    assert result["operator_brief"]["mode"] == "operator"
    assert result["agi_operator_cycle"]["decision"]["best_move"] == "stay_quiet"


def test_runtime_ensure_todoist_mcp_adds_config(monkeypatch, tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("mcp_servers:\n  playwright-live:\n    command: /bin/true\n", encoding="utf-8")
    monkeypatch.setattr(tools, "HERMES_CONFIG_PATH", config_path)
    fake_home = tmp_path / "home"
    monkeypatch.setattr(tools.Path, "home", lambda: fake_home)

    result = _decode(tools.handle_runtime({"action": "ensure_todoist_mcp"}))
    written = config_path.read_text(encoding="utf-8")

    assert result["success"] is True
    assert result["changed"] is True
    assert "todoist" in result["mcp_servers"]
    assert result["todoist"]["command"] == "node"
    assert result["todoist"]["enabled"] is True
    assert result["todoist"]["env"]["TODOIST_API_KEY"] == "${TODOIST_API_KEY}"
    assert "https://ai.todoist.net/mcp" not in written
    assert "auth: oauth" not in written
    assert "enabled: true" in written
    assert "playwright-live" in written


def test_personal_focus_guard_run_delegates_and_returns_summary(monkeypatch):
    focus_guard_result = {
        "status": "needs_focus",
        "task_count": 3,
        "most_important_task": {
            "id": "ship",
            "content": "Ship the draft",
            "priority": 4,
        },
        "suspicious_task_ids": ["avoidance", "prep"],
        "notified_suspicious_task_ids": ["avoidance"],
    }
    seen = {}

    def fake_focus_guard_run_once(**kwargs):
        seen["filter"] = kwargs.get("filter")
        return focus_guard_result

    monkeypatch.setattr(tools, "_focus_guard_run_once", fake_focus_guard_run_once)

    result = _decode(tools.handle_focus_guard({"action": "run", "filter": "today"}))

    assert result["success"] is True
    assert result["action"] == "run"
    assert result["status"] == "needs_focus"
    assert result["task_count"] == 3
    assert result["suspicious_task_ids"] == ["avoidance", "prep"]
    assert result["notified_suspicious_task_ids"] == ["avoidance"]
    assert "Ship the draft" in result["summary"]
    assert "2 suspicious" in result["summary"]
    assert seen["filter"] == "today"


def test_personal_focus_guard_status_reads_saved_state_and_summarizes_without_todoist(monkeypatch):
    monkeypatch.setattr(
        tools,
        "_focus_guard_read_todoist_tasks",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("status should not hit Todoist")),
    )
    monkeypatch.setattr(
        tools,
        "_focus_guard_read_state",
        lambda path=tools.FOCUS_GUARD_STATE_PATH: {
            "status": "needs_focus",
            "task_count": 2,
            "most_important_task": {
                "id": "ship",
                "content": "Ship the draft",
                "priority": 4,
            },
            "suspicious_tasks": [
                {"task": {"id": "avoidance", "content": "Research the perfect productivity app"}},
            ],
            "processed_suspicious_task_ids": ["avoidance"],
        },
    )

    result = _decode(tools.handle_focus_guard({"action": "status"}))

    assert result["success"] is True
    assert result["action"] == "status"
    assert result["status"] == "needs_focus"
    assert result["task_count"] == 2
    assert result["suspicious_task_ids"] == ["avoidance"]
    assert result["notified_suspicious_task_ids"] == []
    assert result["processed_suspicious_task_ids"] == ["avoidance"]
    assert "Ship the draft" in result["summary"]
    assert "saved state" in result["summary"].lower() or "last known" in result["summary"].lower()
    assert "scanned" not in result["summary"].lower()
    assert "1 suspicious" in result["summary"]


def test_personal_focus_guard_run_and_status_use_same_canonical_result_keys(monkeypatch):
    run_result = {
        "status": "needs_focus",
        "task_count": 3,
        "most_important_task": {"id": "ship", "content": "Ship the draft", "priority": 4},
        "suspicious_task_ids": ["avoidance", "prep"],
        "notified_suspicious_task_ids": ["avoidance"],
        "processed_suspicious_task_ids": ["avoidance"],
        "generated_at": "2026-05-17T12:00:00+00:00",
    }
    status_state = {
        "status": "needs_focus",
        "task_count": 2,
        "most_important_task": {"id": "ship", "content": "Ship the draft", "priority": 4},
        "suspicious_tasks": [{"task": {"id": "avoidance", "content": "Research the perfect productivity app"}}],
        "processed_suspicious_task_ids": ["avoidance"],
        "generated_at": "2026-05-17T11:00:00+00:00",
    }
    expected_keys = {
        "success",
        "action",
        "summary",
        "status",
        "task_count",
        "most_important_task",
        "suspicious_tasks",
        "suspicious_task_ids",
        "notified_suspicious_task_ids",
        "processed_suspicious_task_ids",
        "generated_at",
    }

    monkeypatch.setattr(tools, "_focus_guard_run_once", lambda **kwargs: run_result)
    monkeypatch.setattr(tools, "_focus_guard_read_state", lambda path=tools.FOCUS_GUARD_STATE_PATH: status_state)

    run_payload = _decode(tools.handle_focus_guard({"action": "run"}))
    status_payload = _decode(tools.handle_focus_guard({"action": "status"}))

    assert set(run_payload) == expected_keys
    assert set(status_payload) == expected_keys


def test_runtime_status_reports_provider_chain_and_incidents(monkeypatch):
    monkeypatch.setattr(
        tools,
        "_runtime_service_status",
        lambda: {
            "service": "hermes-gateway.service",
            "active": True,
            "active_since": "Sun 2026-05-17 19:10:45 UTC",
        },
    )
    monkeypatch.setattr(
        tools,
        "_runtime_provider_chain",
        lambda: {
            "primary": {"provider": "custom:cerebras", "model": "gpt-oss-120b"},
            "fallbacks": [
                {"provider": "openrouter", "model": "deepseek/deepseek-v4-flash"},
                {"provider": "custom:groq", "model": "meta-llama/llama-4-scout-17b-16e-instruct"},
            ],
            "compression": {"protect_last_n": 8, "hygiene_hard_message_limit": 250},
            "plugins_enabled": ["personal-ops"],
        },
    )
    monkeypatch.setattr(
        tools,
        "_runtime_recent_incidents",
        lambda limit=20: [
            {"kind": "rate_limit", "summary": "Cerebras 429", "raw": "HTTP 429"},
            {"kind": "request_too_large", "summary": "Groq 413", "raw": "HTTP 413"},
        ],
    )

    result = _decode(tools.handle_runtime({"action": "status"}))

    assert result["success"] is True
    assert result["action"] == "status"
    assert result["service"]["active"] is True
    assert result["provider_chain"]["primary"]["provider"] == "custom:cerebras"
    assert len(result["recent_incidents"]) == 2
    assert "active" in result["summary"].lower()
    assert "2 current incident" in result["summary"].lower()


def test_runtime_incidents_classifies_known_failure_patterns():
    incidents = tools._runtime_incidents_from_lines(
        [
            "WARNING run_agent: API call failed summary=HTTP 429: Tokens per minute limit exceeded",
            "WARNING run_agent: API call failed summary=HTTP 413: Request too large for model",
            "ERROR gateway.platforms.sms: [sms] Refusing to start: SMS_WEBHOOK_URL is required",
            "ERROR root: 413 payload too large. Cannot compress further.",
        ]
    )

    kinds = [item["kind"] for item in incidents]
    assert "rate_limit" in kinds
    assert "request_too_large" in kinds
    assert "sms_misconfigured" in kinds
    assert "compression_failed" in kinds


def test_runtime_upstream_status_summarizes_commits_and_local_behind(monkeypatch):
    monkeypatch.setattr(
        tools,
        "_runtime_fetch_recent_commits",
        lambda **kwargs: [
            {
                "sha": "abcdef123456",
                "message": "feat: improve cron reliability",
                "author": "alice",
                "date": "2026-05-17T12:00:00Z",
                "url": "https://github.com/NousResearch/hermes-agent/commit/abcdef123456",
            }
        ],
    )
    monkeypatch.setattr(
        tools,
        "_runtime_local_git_status",
        lambda repo_path: {
            "repo_path": str(repo_path),
            "behind": 2,
            "head": "1111111",
            "origin_branch": "hermes/update-upstream-2026-06-18",
            "origin_ref": "origin/hermes/update-upstream-2026-06-18",
            "origin": "2222222",
            "fetch_ok": True,
        },
    )

    status = tools._runtime_upstream_status(hours=24, repo_path=Path("C:/hermes-agent"))

    assert status["recent_commit_count"] == 1
    assert status["local"]["behind"] == 2
    assert "improve cron reliability" in status["summary"]


def test_runtime_watch_upstream_sends_telegram_when_changes_exist(monkeypatch):
    sent = []
    monkeypatch.setattr(
        tools,
        "_runtime_upstream_status",
        lambda **kwargs: {
            "repo": "NousResearch/hermes-agent",
            "hours": 24,
            "recent_commit_count": 1,
            "recent_commits": [
                {"sha": "abcdef123456", "message": "feat: improve cron reliability", "author": "alice"},
            ],
            "local": {
                "behind": 1,
                "repo_path": "/home/ubuntu/hermes-agent",
                "origin_ref": "origin/hermes/update-upstream-2026-06-18",
            },
            "summary": "Hermes upstream changed: 1 commit in the last 24h. Local checkout is 1 commit behind origin/hermes/update-upstream-2026-06-18.",
        },
    )
    monkeypatch.setattr(tools, "_focus_guard_send_telegram_message", lambda text, **kwargs: sent.append(text) or {"ok": True})

    result = _decode(tools.handle_runtime({"action": "watch_upstream", "hours": 24}))

    assert result["success"] is True
    assert result["sent"] is True
    assert sent
    assert "improve cron reliability" in sent[0]


def test_runtime_watch_upstream_stays_quiet_when_current(monkeypatch):
    monkeypatch.setattr(
        tools,
        "_runtime_upstream_status",
        lambda **kwargs: {
            "repo": "NousResearch/hermes-agent",
            "hours": 24,
            "recent_commit_count": 0,
            "recent_commits": [],
            "local": {
                "behind": 0,
                "repo_path": "/home/ubuntu/hermes-agent",
                "origin_ref": "origin/hermes/update-upstream-2026-06-18",
            },
            "summary": "No Hermes upstream commits in the last 24h. Local checkout is current with origin/hermes/update-upstream-2026-06-18.",
        },
    )
    monkeypatch.setattr(
        tools,
        "_focus_guard_send_telegram_message",
        lambda text, **kwargs: (_ for _ in ()).throw(AssertionError("should not send")),
    )

    result = _decode(tools.handle_runtime({"action": "watch_upstream"}))

    assert result["success"] is True
    assert result["sent"] is False
    assert result["reason"] == "current"


def test_runtime_watch_upstream_can_disable_telegram_notification(monkeypatch):
    sent = []
    monkeypatch.setattr(
        tools,
        "_runtime_upstream_status",
        lambda **kwargs: {
            "repo": "NousResearch/hermes-agent",
            "hours": 24,
            "recent_commit_count": 3,
            "recent_commits": [],
            "local": {"behind": 2, "repo_path": "/home/ubuntu/hermes-agent"},
            "summary": "Hermes upstream changed.",
        },
    )
    monkeypatch.setattr(tools, "_focus_guard_send_telegram_message", lambda text, **kwargs: sent.append(text) or {"ok": True})

    result = _decode(tools.handle_runtime({"action": "watch_upstream", "send_telegram": False}))

    assert result["success"] is True
    assert result["sent"] is False
    assert result["reason"] == "notification_disabled"
    assert sent == []


def test_runtime_live_watch_runs_focus_guard_then_companion(monkeypatch):
    monkeypatch.setattr(
        tools,
        "_focus_guard_run_once",
        lambda **kwargs: {
            "status": "needs_focus",
            "task_count": 2,
            "most_important_task": {"content": "Plan simple outing"},
            "suspicious_task_ids": [],
            "notified_suspicious_task_ids": [],
            "processed_suspicious_task_ids": [],
            "generated_at": "2026-05-18T12:00:00+00:00",
        },
    )
    monkeypatch.setattr(
        tools,
        "handle_adaptive_companion",
        lambda args, **kwargs: json.dumps(
            {
                "success": True,
                "action": "run",
                "always_on": args.get("always_on"),
                "sent": False,
                "reason": "no_trigger",
            }
        ),
    )

    result = _decode(tools.handle_runtime({"action": "live_watch", "filter": "today | overdue"}))

    assert result["success"] is True
    assert result["action"] == "live_watch"
    assert result["always_on"] is False
    assert result["focus_guard"]["task_count"] == 2
    assert result["adaptive_companion"]["reason"] == "no_trigger"
    assert tools.LIVE_WATCH_STATE_PATH.exists()


def test_runtime_live_watch_can_force_always_on(monkeypatch):
    monkeypatch.setattr(
        tools,
        "_focus_guard_run_once",
        lambda **kwargs: {
            "status": "needs_focus",
            "task_count": 1,
            "most_important_task": {"content": "Plan simple outing"},
            "suspicious_task_ids": [],
            "notified_suspicious_task_ids": [],
            "processed_suspicious_task_ids": [],
            "generated_at": "2026-05-18T12:00:00+00:00",
        },
    )
    monkeypatch.setattr(
        tools,
        "handle_adaptive_companion",
        lambda args, **kwargs: json.dumps(
            {
                "success": True,
                "action": "run",
                "always_on": args.get("always_on"),
                "sent": False,
                "reason": "no_trigger",
            }
        ),
    )

    result = _decode(tools.handle_runtime({"action": "live_watch", "always_on": True}))

    assert result["success"] is True
    assert result["always_on"] is True
    assert result["adaptive_companion"]["always_on"] is True


def test_runtime_live_watch_uses_saved_companion_state_when_run_response_is_thin(monkeypatch):
    monkeypatch.setattr(
        tools,
        "_focus_guard_run_once",
        lambda **kwargs: {
            "status": "needs_focus",
            "task_count": 1,
            "most_important_task": {"content": "Plan simple outing"},
            "suspicious_task_ids": [],
            "notified_suspicious_task_ids": [],
            "processed_suspicious_task_ids": [],
            "generated_at": "2026-05-18T12:00:00+00:00",
        },
    )
    monkeypatch.setattr(
        tools,
        "handle_adaptive_companion",
        lambda args, **kwargs: json.dumps(
            {
                "success": True,
                "action": "run",
                "always_on": args.get("always_on"),
                "sent": False,
                "reason": "cooldown",
            }
        ),
    )
    monkeypatch.setattr(
        tools,
        "_adaptive_companion_read_state",
        lambda path=None: {
            "insight_lenses": {
                "surface_policy": {"mode": "narrow_focus", "compact_status": True},
                "threshold_detection": {"level": "high", "signal": "This is the edge."},
            }
        },
    )

    result = _decode(tools.handle_runtime({"action": "live_watch", "filter": "today | overdue"}))

    assert result["surface_policy"]["mode"] == "narrow_focus"
    assert result["adaptive_companion"]["state"]["insight_lenses"]["surface_policy"]["compact_status"] is True


def test_runtime_live_watch_status_reports_last_reason(monkeypatch):
    seeded = {
        "ran_at": "2026-05-18T12:15:00+00:00",
        "filter": "today | overdue",
        "focus_guard": {"status": "needs_focus", "task_count": 1},
        "adaptive_companion": {"success": True, "sent": False, "reason": "cooldown"},
    }
    tools._write_json(tools.LIVE_WATCH_STATE_PATH, seeded)

    result = _decode(tools.handle_runtime({"action": "live_watch_status"}))

    assert result["success"] is True
    assert result["configured"] is True
    assert result["adaptive_companion"]["reason"] == "cooldown"
    assert "cooldown" in result["summary"]


def test_runtime_event_ingest_builds_wake_briefing(monkeypatch):
    class _FixedDatetime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return real_datetime(2026, 5, 18, 18, 0, tzinfo=tz)

    monkeypatch.setattr(tools, "datetime", _FixedDatetime)
    monkeypatch.setattr(
        tools,
        "_focus_guard_read_state",
        lambda: {
            "status": "needs_focus",
            "most_important_task": {"content": "Plan simple outing"},
            "suspicious_tasks": [{"task": {"content": "Read Life OS identity statement"}}],
        },
    )
    monkeypatch.setattr(tools, "_operator_brief", lambda args: {
        "success": True,
        "top_task": {"title": "Plan simple outing"},
        "primary_friction": "admin_cleanup",
        "risk": "task_shuffling",
        "recommended_next_action": "Message one person and choose a concrete time.",
        "evidence": {"todoist_mcp": {"active_count": 4, "completed_recently": 2, "noise": {"status": "moderate"}}},
    })
    sent = []
    monkeypatch.setattr(tools, "_focus_guard_send_telegram_message", lambda text, **kwargs: sent.append(text) or {"ok": True})
    monkeypatch.setattr(tools, "_telegram_messages_allowed_now", lambda now_hour=None: True)

    result = _decode(tools.handle_runtime({"action": "event_ingest", "event_type": "wake", "send_telegram": True}))

    assert result["success"] is True
    assert result["event_type"] == "wake"
    assert "Good morning" not in result["message"]
    assert "I received a manual command signal" in result["message"]
    assert "Priority anchor" in result["message"]
    assert "Plan simple outing" in result["message"]
    assert "Quick snapshot" in result["message"]
    assert "next 5\u201315 minutes" in result["message"]
    assert sent


def test_runtime_event_ingest_suppresses_late_wake_telegram(monkeypatch):
    class _FixedDatetime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return real_datetime(2026, 5, 19, 4, 49, tzinfo=tz)

    monkeypatch.setattr(tools, "datetime", _FixedDatetime)
    monkeypatch.setattr(tools, "_focus_guard_read_state", lambda: {
        "status": "needs_focus",
        "most_important_task": {"content": "Family handoff"},
        "suspicious_tasks": [],
    })
    monkeypatch.setattr(tools, "_operator_brief", lambda args: {
        "success": True,
        "top_task": {"title": "Family handoff"},
        "primary_friction": "evening_closure",
        "risk": "stale_task_drift",
        "recommended_next_action": "Close or defer one task honestly.",
        "evidence": {"todoist_mcp": {"active_count": 8, "completed_recently": 1, "noise": {"status": "noisy"}}},
    })
    sent = []
    monkeypatch.setattr(tools, "_focus_guard_send_telegram_message", lambda text, **kwargs: sent.append(text) or {"ok": True})

    result = _decode(tools.handle_runtime({
        "action": "event_ingest",
        "event_type": "wake",
        "source": "windows-logon-trigger",
        "send_telegram": True,
    }))

    assert result["success"] is True
    assert result["sent"] is False
    assert result["suppressed_reason"] == "outside_hours"
    assert sent == []
    assert "Good morning" not in result["message"]
    assert "outside normal message hours" in result["message"]
    assert "Family handoff" in result["message"]


def test_runtime_event_ingest_keeps_low_confidence_windows_logon_silent(monkeypatch):
    class _FixedDatetime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return real_datetime(2026, 5, 19, 12, 44, tzinfo=tz)

    monkeypatch.setattr(tools, "datetime", _FixedDatetime)
    monkeypatch.setattr(
        tools,
        "_focus_guard_read_state",
        lambda: {
            "status": "needs_focus",
            "most_important_task": {"content": "Laundry check"},
            "suspicious_tasks": [],
        },
    )
    monkeypatch.setattr(tools, "_telegram_messages_allowed_now", lambda now_hour=None: True)
    sent = []
    monkeypatch.setattr(tools, "_focus_guard_send_telegram_message", lambda text, **kwargs: sent.append(text) or {"ok": True})

    result = _decode(
        tools.handle_runtime(
            {
                "action": "event_ingest",
                "event_type": "wake",
                "source": "windows-logon-trigger",
                "send_telegram": True,
            }
        )
    )

    assert result["success"] is True
    assert result["sent"] is False
    assert result["suppressed_reason"] == "presence_signal_only"
    assert sent == []
    assert "possible activity" in result["message"]


def test_runtime_event_ingest_records_presence_confidence_without_claiming_true_power_on(monkeypatch):
    monkeypatch.setattr(
        tools,
        "_focus_guard_read_state",
        lambda: {
            "status": "needs_focus",
            "most_important_task": {"content": "Family handoff"},
            "suspicious_tasks": [],
        },
    )

    result = _decode(
        tools.handle_runtime(
            {
                "action": "event_ingest",
                "event_type": "wake",
                "source": "windows-logon-trigger",
                "send_telegram": False,
            }
        )
    )
    presence = _decode(tools.handle_runtime({"action": "presence_status"}))

    assert result["success"] is True
    assert presence["confidence"] == pytest.approx(0.45)
    assert presence["level"] == "weak"
    assert presence["can_proactively_message"] is False
    assert "logon" in presence["summary"].lower()
    assert "power" not in presence["summary"].lower()


def test_runtime_event_ingest_activitywatch_heartbeat_sets_strong_presence():
    result = _decode(
        tools.handle_runtime(
            {
                "action": "event_ingest",
                "event_type": "activitywatch_heartbeat",
                "source": "activitywatch-forwarder",
                "send_telegram": False,
                "presence_signal": {
                    "confidence": 0.83,
                    "label": "ActivityWatch active_now",
                    "active": True,
                    "active_category": "browser",
                    "last_activity_age_seconds": 12,
                },
            }
        )
    )
    presence = _decode(tools.handle_runtime({"action": "presence_status"}))

    assert result["success"] is True
    assert result["event_type"] == "activitywatch_heartbeat"
    assert presence["confidence"] == pytest.approx(0.83)
    assert presence["can_proactively_message"] is True
    assert presence["last_signal"]["source"] == "activitywatch-forwarder"


def test_runtime_presence_status_demotes_stale_signals(monkeypatch):
    tools._write_json(
        tools.PRESENCE_STATE_PATH,
        {
            "last_signal": {
                "ts": "2026-05-18T08:00:00+00:00",
                "source": "telegram-capture",
                "event_type": "voice_memo_received",
                "confidence": 0.85,
                "label": "telegram activity",
            },
            "recent_signals": [],
        },
    )

    class _FixedDatetime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return real_datetime(2026, 5, 18, 9, 10, tzinfo=tz)

    monkeypatch.setattr(tools, "datetime", _FixedDatetime)

    presence = _decode(tools.handle_runtime({"action": "presence_status"}))

    assert presence["confidence"] == 0
    assert presence["level"] == "stale"
    assert presence["can_proactively_message"] is False


def test_runtime_presence_status_uses_activitywatch_signal_to_raise_confidence(monkeypatch):
    from datetime import timezone as tz, timedelta as td
    now_utc = real_datetime.now(tz.utc)
    signal_ts = (now_utc - td(seconds=30)).isoformat()
    aw_ts1 = (now_utc - td(seconds=30)).isoformat().replace("+00:00", "Z")
    aw_ts2 = (now_utc - td(seconds=40)).isoformat().replace("+00:00", "Z")

    tools._write_json(
        tools.PRESENCE_STATE_PATH,
        {
            "last_signal": {
                "ts": signal_ts,
                "source": "windows-logon-trigger",
                "event_type": "wake",
                "confidence": 0.45,
                "label": "Windows logon",
            },
            "recent_signals": [],
        },
    )
    env_path = tools.HERMES_HOME / ".env"
    env_path.write_text("HERMES_ACTIVITYWATCH_BASE_URL=http://activitywatch.local:5600\n", encoding="utf-8")

    class _ActivityWatchClient:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get(self, url: str, headers=None, params=None):
            del headers, params
            if "aw-watcher-afk" in url:
                return _FakeResponse([{"timestamp": aw_ts1, "data": {"status": "not-afk"}}])
            if "aw-watcher-window" in url:
                return _FakeResponse([{"timestamp": aw_ts2, "data": {"app": "chrome", "title": "Todoist"}}])
            raise AssertionError(url)

    monkeypatch.setattr(tools, "_http_client", lambda: _ActivityWatchClient())

    presence = _decode(tools.handle_runtime({"action": "presence_status"}))

    assert presence["configured"] is True
    assert presence["activitywatch"]["configured"] is True
    assert presence["activitywatch"]["active"] is True
    assert presence["confidence"] >= 0.7
    assert presence["level"] in {"strong", "active_now"}
    assert presence["can_proactively_message"] is True


def test_adaptive_companion_run_suppresses_when_presence_is_only_weak(monkeypatch):
    tools._write_json(
        tools.PRESENCE_STATE_PATH,
        {
            "last_signal": {
                "ts": "2026-05-18T13:00:00+00:00",
                "source": "windows-logon-trigger",
                "event_type": "wake",
                "confidence": 0.45,
                "label": "Windows logon",
            },
            "recent_signals": [],
        },
    )
    monkeypatch.setattr(
        tools,
        "_focus_guard_read_state",
        lambda: {
            "status": "needs_focus",
            "most_important_task": {"id": "1", "content": "Family handoff"},
            "suspicious_tasks": [{"task": {"content": "Read Life OS identity statement"}}],
        },
    )
    monkeypatch.setattr(tools, "_adaptive_companion_recent_user_text", lambda: "")
    monkeypatch.setattr(tools, "_adaptive_companion_now_local_hour", lambda: 13)
    sent = []
    monkeypatch.setattr(tools, "_focus_guard_send_telegram_message", lambda text, **kwargs: sent.append(text) or {"ok": True})

    result = _decode(tools.handle_adaptive_companion({"action": "run"}))

    assert result["sent"] is False
    assert result["reason"] == "presence_not_confident"
    assert sent == []


def test_adaptive_companion_run_stops_after_daily_global_nudge_budget(monkeypatch):
    today = "2026-05-18"
    tools._write_json(
        tools.NUDGE_BUDGET_STATE_PATH,
        {
            "date": today,
            "sent_counts": {"pressure": 5, "total": 5},
            "events": [],
        },
    )
    tools._write_json(
        tools.PRESENCE_STATE_PATH,
        {
            "last_signal": {
                "ts": "2026-05-18T13:00:00+00:00",
                "source": "telegram-capture",
                "event_type": "voice_memo_received",
                "confidence": 0.85,
                "label": "Telegram activity",
            },
            "recent_signals": [],
        },
    )

    class _FixedDatetime(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return real_datetime(2026, 5, 18, 13, 30, tzinfo=tz)

    monkeypatch.setattr(tools, "datetime", _FixedDatetime)
    monkeypatch.setattr(
        tools,
        "_focus_guard_read_state",
        lambda: {
            "status": "needs_focus",
            "most_important_task": {"id": "1", "content": "Family handoff"},
            "suspicious_tasks": [{"task": {"content": "Read Life OS identity statement"}}],
        },
    )
    monkeypatch.setattr(tools, "_adaptive_companion_recent_user_text", lambda: "")
    monkeypatch.setattr(tools, "_adaptive_companion_now_local_hour", lambda: 13)
    sent = []
    monkeypatch.setattr(tools, "_focus_guard_send_telegram_message", lambda text, **kwargs: sent.append(text) or {"ok": True})

    result = _decode(tools.handle_adaptive_companion({"action": "run"}))

    assert result["sent"] is False
    assert result["reason"] == "nudge_budget_exhausted"
    assert sent == []


def test_focus_guard_send_telegram_message_respects_quiet_hours(monkeypatch):
    monkeypatch.setattr(tools, "_telegram_messages_allowed_now", lambda now_hour=None: False)

    result = tools._focus_guard_send_telegram_message("hello")

    assert result["suppressed"] is True
    assert result["reason"] == "quiet_hours"


def test_focus_guard_send_telegram_message_supports_inline_buttons(monkeypatch):
    sent = {}
    monkeypatch.setattr(tools, "_telegram_messages_allowed_now", lambda now_hour=None: True)
    monkeypatch.setattr(tools, "_focus_guard_telegram_config", lambda: ("token", "chat"))
    monkeypatch.setattr(
        tools,
        "_focus_guard_telegram_post",
        lambda method, payload: sent.update({"method": method, "payload": payload}) or {"ok": True, "result": {"message_id": 42}},
    )

    result = tools._focus_guard_send_telegram_message(
        "Operator note",
        buttons=["Done", "Bad nudge", "Draft tomorrow"],
    )

    assert result["ok"] is True
    assert sent["method"] == "sendMessage"
    assert sent["payload"]["text"] == "Operator note"
    assert sent["payload"]["reply_markup"]["inline_keyboard"][0][0]["text"] == "Done"
    assert sent["payload"]["reply_markup"]["inline_keyboard"][0][1]["callback_data"].startswith("hermes_feedback:")


def test_runtime_event_ingest_telegram_feedback_updates_nudge_receipt():
    tools._write_json(
        tools.OPERATOR_STATE_PATH,
        {
            "nudge_records": [
                {
                    "id": "nudge_1",
                    "message_id": "99",
                    "task_id": "task_1",
                    "task_title": "Plan simple outing",
                    "sent_at": "2026-05-19T18:12:00-06:00",
                    "message_class": "operator_brief",
                    "buttons": ["Done", "Defer 30m", "Bad nudge"],
                    "outcome": "pending",
                    "user_action": None,
                }
            ]
        },
    )

    result = _decode(
        tools.handle_runtime(
            {
                "action": "event_ingest",
                "event_type": "telegram_feedback",
                "source": "telegram-callback",
                "message_id": "99",
                "feedback": "bad_nudge",
                "task_id": "task_1",
            }
        )
    )
    state = tools._read_json(tools.OPERATOR_STATE_PATH, {})
    receipt = state["nudge_records"][-1]

    assert result["success"] is True
    assert result["handled"] is True
    assert result["event_type"] == "telegram_feedback"
    assert receipt["user_action"] == "bad_nudge"
    assert receipt["outcome"] == "bad_nudge"
    assert receipt["feedback_at"]
    assert receipt["policy_update"]


def test_runtime_event_log_state_builds_snapshot_from_event_stream():
    tools.EVENTS_PATH.write_text(
        "\n".join(
            [
                json.dumps({"ts": 1, "type": "runtime_event_ingested", "event_type": "wake", "source": "manual"}),
                json.dumps({"ts": 2, "type": "runtime_event_ingested", "event_type": "telegram_feedback", "source": "telegram-callback"}),
                json.dumps({"ts": 3, "type": "approval_created", "request_id": "req_1", "tool": "personal_runtime"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    tools._write_json(
        tools.OPERATOR_STATE_PATH,
        {
            "nudge_records": [
                {
                    "id": "nudge_1",
                    "task_id": "laundry",
                    "task_title": "Laundry check",
                    "outcome": "bad_nudge",
                    "user_action": "bad_nudge",
                    "feedback_at": "2026-05-19T20:50:00-06:00",
                }
            ],
            "operator_memories": [{"content": "User dislikes vague nudges.", "type": "explicit_preference"}],
        },
    )

    result = _decode(tools.handle_runtime({"action": "event_log_state"}))

    assert result["success"] is True
    assert result["action"] == "event_log_state"
    assert result["event_log"]["event_count"] == 3
    assert result["event_log"]["by_type"]["runtime_event_ingested"] == 2
    assert result["snapshot"]["last_feedback"]["task_title"] == "Laundry check"
    assert result["snapshot"]["memory_count"] == 1


def test_normalized_event_state_groups_events_into_families():
    tools.EVENTS_PATH.write_text(
        "\n".join(
            [
                json.dumps({"ts": 1, "type": "runtime_event_ingested", "event_type": "wake", "source": "manual"}),
                json.dumps({"ts": 2, "type": "runtime_event_ingested", "event_type": "telegram_feedback", "source": "telegram-callback"}),
                json.dumps({"ts": 3, "type": "approval_created", "request_id": "req_1", "tool": "personal_runtime"}),
                json.dumps({"ts": 4, "type": "self_improve_run", "actions": 1}),
                json.dumps({"ts": 5, "type": "common_sense_decision", "task_count": 2}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = _decode(tools.handle_runtime({"action": "operating_snapshot"}))

    assert result["success"] is True
    assert result["normalized_events"]["family_counts"]["presence"] == 1
    assert result["normalized_events"]["family_counts"]["telegram"] == 1
    assert result["normalized_events"]["family_counts"]["approval"] == 1
    assert result["normalized_events"]["family_counts"]["self_improve"] == 1
    assert result["normalized_events"]["family_counts"]["operator"] == 1


def test_operating_snapshot_includes_reducer_backed_subsystems():
    tools.EVENTS_PATH.write_text(
        json.dumps({"ts": 1, "type": "runtime_event_ingested", "event_type": "telegram_feedback", "source": "telegram-callback"})
        + "\n",
        encoding="utf-8",
    )
    tools._write_json(
        tools.OPERATOR_STATE_PATH,
        {
            "nudge_records": [
                {
                    "id": "nudge_1",
                    "task_id": "task_1",
                    "task_title": "Laundry check",
                    "outcome": "blocked",
                    "user_action": "blocked",
                    "feedback_at": "2026-05-19T10:00:00+00:00",
                }
            ],
            "operator_memories": [{"content": "User prefers direct messages.", "type": "explicit_preference"}],
        },
    )
    tools._write_json(
        tools.APPROVALS_PATH,
        {"pending": {"req_1": {"request_id": "req_1", "summary": "Apply bundle"}}, "history": []},
    )
    tools._write_json(
        tools.PRESENCE_STATE_PATH,
        {
            "last_signal": {
                "ts": "2026-05-19T10:11:05+00:00",
                "source": "activitywatch-forwarder",
                "event_type": "activitywatch_heartbeat",
                "confidence": 0.83,
                "label": "ActivityWatch active_now",
            }
        },
    )

    result = _decode(tools.handle_runtime({"action": "operating_snapshot"}))

    assert result["success"] is True
    assert result["snapshot"]["presence"]["source"] == "activitywatch-forwarder"
    assert result["snapshot"]["nudge"]["last_feedback"]["task_title"] == "Laundry check"
    assert result["snapshot"]["approval"]["pending_count"] == 1
    assert result["snapshot"]["memory"]["memory_count"] == 1


def test_snapshot_delta_reports_meaningful_changes_between_snapshots():
    first = _decode(tools.handle_runtime({"action": "operating_snapshot"}))
    tools._write_json(
        tools.OPERATOR_STATE_PATH,
        {
            "nudge_records": [
                {
                    "id": "nudge_1",
                    "task_id": "task_1",
                    "task_title": "Laundry check",
                    "outcome": "done",
                    "user_action": "done",
                    "feedback_at": "2026-05-19T10:12:00+00:00",
                }
            ]
        },
    )
    second = _decode(tools.handle_runtime({"action": "operating_snapshot"}))
    delta = _decode(
        tools.handle_runtime(
            {
                "action": "operating_delta",
                "previous_snapshot": first["snapshot"],
                "current_snapshot": second["snapshot"],
            }
        )
    )

    assert delta["success"] is True
    assert delta["changes"]["nudge_feedback_changed"] is True
    assert "nudge_feedback_changed" in delta["summary"]


def test_presence_priority_prefers_forwarded_activitywatch_over_server_polling(monkeypatch):
    from datetime import timezone as tz, timedelta as td
    now_utc = real_datetime.now(tz.utc)
    signal_ts = (now_utc - td(seconds=5)).isoformat()
    tools._write_json(
        tools.PRESENCE_STATE_PATH,
        {
            "last_signal": {
                "ts": signal_ts,
                "source": "activitywatch-forwarder",
                "event_type": "activitywatch_heartbeat",
                "confidence": 0.83,
                "label": "ActivityWatch active_now",
                "active": True,
                "active_category": "browser",
            }
        },
    )
    monkeypatch.setattr(
        tools,
        "_runtime_activitywatch_signal",
        lambda now=None: {"configured": True, "active": False, "confidence": 0.0, "error": "connection refused", "source": "server_local_activitywatch"},
    )

    result = _decode(tools.handle_runtime({"action": "presence_status"}))

    assert result["confidence"] == pytest.approx(0.83)
    assert result["last_signal"]["source"] == "activitywatch-forwarder"
    assert "activitywatch-forwarder" in result["summary"]


def test_common_sense_registry_exposes_core_domains():
    result = _decode(tools.handle_runtime({"action": "operating_snapshot"}))
    domains = result["common_sense_registry"]["domains"]

    assert "meal_breakfast" in domains
    assert "morning_routine" in domains
    assert "business_contact" in domains
    assert "family_transition" in domains
    assert "workout" in domains
    assert "laundry_home" in domains
    assert "evening_reset" in domains
    assert "reference" in domains
    assert "admin" in domains


def test_runtime_memory_console_can_upsert_list_and_delete_memory():
    created = _decode(
        tools.handle_runtime(
            {
                "action": "memory_console",
                "mode": "upsert",
                "memory": {
                    "content": "User prefers direct low-pressure operator messages.",
                    "type": "explicit_preference",
                    "source": "telegram",
                    "confidence": 1.0,
                },
            }
        )
    )
    listed = _decode(tools.handle_runtime({"action": "memory_console", "mode": "list"}))
    deleted = _decode(
        tools.handle_runtime(
            {
                "action": "memory_console",
                "mode": "delete",
                "memory_id": created["memory"]["memory_id"],
            }
        )
    )

    assert created["success"] is True
    assert created["memory"]["memory_id"]
    assert listed["memory_count"] == 1
    assert listed["memories"][0]["content"] == "User prefers direct low-pressure operator messages."
    assert deleted["deleted"] is True
    assert _decode(tools.handle_runtime({"action": "memory_console", "mode": "list"}))["memory_count"] == 0


def test_memory_console_correction_preserves_provenance_and_updates_active_content():
    created = _decode(
        tools.handle_runtime(
            {
                "action": "memory_console",
                "mode": "upsert",
                "memory": {
                    "content": "User prefers short cryptic nudges.",
                    "type": "inferred_preference",
                    "source": "runtime",
                    "confidence": 0.42,
                },
            }
        )
    )

    corrected = _decode(
        tools.handle_runtime(
            {
                "action": "memory_console",
                "mode": "correct",
                "memory_id": created["memory"]["memory_id"],
                "content": "User prefers specific explanatory nudges.",
                "confidence": 0.9,
            }
        )
    )
    listed = _decode(tools.handle_runtime({"action": "memory_console", "mode": "list"}))

    assert corrected["success"] is True
    assert corrected["memory"]["content"] == "User prefers specific explanatory nudges."
    assert corrected["memory"]["previous_content"] == "User prefers short cryptic nudges."
    assert corrected["memory"]["corrected_at"]
    assert listed["memories"][0]["content"] == "User prefers specific explanatory nudges."


def test_memory_console_expiry_hides_item_from_default_active_list():
    created = _decode(
        tools.handle_runtime(
            {
                "action": "memory_console",
                "mode": "upsert",
                "memory": {
                    "content": "Old harsh Adaptive Companion language should be retired.",
                    "type": "stale_memory",
                    "source": "review",
                    "confidence": 0.75,
                },
            }
        )
    )
    expired = _decode(
        tools.handle_runtime(
            {
                "action": "memory_console",
                "mode": "expire",
                "memory_id": created["memory"]["memory_id"],
            }
        )
    )
    active = _decode(tools.handle_runtime({"action": "memory_console", "mode": "list"}))
    history = _decode(tools.handle_runtime({"action": "memory_console", "mode": "list", "include_expired": True}))

    assert expired["success"] is True
    assert expired["memory"]["expired_at"]
    assert active["memory_count"] == 0
    assert history["memory_count"] == 1
    assert history["memories"][0]["memory_id"] == created["memory"]["memory_id"]


def test_runtime_todoist_rule_store_and_rollover_preview_apply_same_day_expiry(monkeypatch):
    _decode(
        tools.handle_runtime(
            {
                "action": "todoist_rule_store",
                "mode": "upsert_task_metadata",
                "task_key": "breakfast-habit",
                "metadata": {
                    "task_type": "meal_breakfast",
                    "rollover_policy": "skip_if_missed",
                    "after_window_behavior": "ask_log_or_recover",
                    "expires_same_day": True,
                },
            }
        )
    )
    monkeypatch.setattr(tools, "_common_sense_now", lambda: real_datetime.fromisoformat("2026-05-19T19:00:00-06:00"))

    result = _decode(
        tools.handle_runtime(
            {
                "action": "rollover_preview",
                "tasks": [
                    {
                        "id": "breakfast-1",
                        "content": "Eat eggs and vegetables for breakfast",
                        "description": "",
                        "labels": [],
                        "is_recurring": True,
                        "task_key": "breakfast-habit",
                    }
                ],
            }
        )
    )

    assert result["success"] is True
    assert result["decisions"][0]["task_key"] == "breakfast-habit"
    assert result["decisions"][0]["rollover_policy"] == "skip_if_missed"
    assert result["decisions"][0]["recommended_state"] == "log_or_skip"
    assert result["decisions"][0]["original_action_valid"] is False


def test_todoist_rule_classification_rolls_out_metadata_for_task_batch():
    result = _decode(
        tools.handle_runtime(
            {
                "action": "todoist_rule_store",
                "mode": "classify_tasks",
                "tasks": [
                    {"id": "b1", "content": "Eat eggs and vegetables for breakfast", "description": "", "labels": [], "task_key": "breakfast-habit"},
                    {"id": "l1", "content": "Laundry check", "description": "", "labels": [], "task_key": "laundry-check"},
                    {"id": "r1", "content": "Read final program rules", "description": "", "labels": ["reference"], "task_key": "reference-rules"},
                ],
            }
        )
    )
    status = _decode(tools.handle_runtime({"action": "todoist_rule_store", "mode": "status"}))

    assert result["success"] is True
    assert result["classified_count"] == 3
    assert result["classified"][0]["task_type"] == "meal_breakfast"
    assert status["task_metadata"]["laundry-check"]["rollover_policy"] in {"carry_until_done", "skip_if_missed"}
    assert status["task_metadata"]["reference-rules"]["task_type"] == "reference"


def test_rollover_preview_exposes_before_after_simulation_summary(monkeypatch):
    _decode(
        tools.handle_runtime(
            {
                "action": "todoist_rule_store",
                "mode": "classify_tasks",
                "tasks": [
                    {"id": "b1", "content": "Eat eggs and vegetables for breakfast", "description": "", "labels": [], "task_key": "breakfast-habit"},
                    {"id": "l1", "content": "Laundry check", "description": "", "labels": [], "task_key": "laundry-check"},
                ],
            }
        )
    )
    monkeypatch.setattr(tools, "_common_sense_now", lambda: real_datetime.fromisoformat("2026-05-19T20:40:00-06:00"))
    result = _decode(
        tools.handle_runtime(
            {
                "action": "rollover_preview",
                "tasks": [
                    {"id": "b1", "content": "Eat eggs and vegetables for breakfast", "description": "", "labels": [], "task_key": "breakfast-habit"},
                    {"id": "l1", "content": "Laundry check", "description": "", "labels": [], "task_key": "laundry-check"},
                ],
            }
        )
    )

    assert result["success"] is True
    assert result["simulation"]["before"]["task_count"] == 2
    assert result["simulation"]["after"]["carry_forward_count"] >= 0
    assert result["simulation"]["after"]["skip_or_log_count"] >= 0
    assert "today_cleanup_reduction" in result["simulation"]["delta"]


def test_runtime_approval_bundle_creates_simulation_and_pending_request():
    result = _decode(
        tools.handle_runtime(
            {
                "action": "approval_bundle",
                "mode": "create",
                "bundle_type": "todoist_repairs",
                "summary": "Apply low-risk Todoist cleanup bundle",
                "items": [
                    {"kind": "rewrite_title", "task_title": "Laundry check", "suggested_title": "Move laundry forward for 10 minutes"},
                    {"kind": "move_reference", "task_title": "Read final program rules", "target_project": "Reference"},
                ],
                "simulation": {
                    "before": {"today_count": 16, "vague_count": 5},
                    "after": {"today_count": 12, "vague_count": 3},
                },
            }
        )
    )
    pending = _decode(tools.handle_security({"action": "list_pending"}))["pending"]

    assert result["success"] is False
    assert result["approval_required"] is True
    assert result["simulation"]["after"]["today_count"] == 12
    assert pending[0]["action"] == "approval_bundle_apply"
    assert pending[0]["payload"]["action"] == "approval_bundle_apply"


def test_approval_bundle_execution_applies_safe_local_items():
    created = _decode(
        tools.handle_runtime(
            {
                "action": "memory_console",
                "mode": "upsert",
                "memory": {
                    "content": "User prefers short cryptic nudges.",
                    "type": "inferred_preference",
                    "source": "runtime",
                    "confidence": 0.42,
                },
            }
        )
    )
    result = _decode(
        tools.handle_runtime(
            {
                "action": "approval_bundle",
                "mode": "create",
                "bundle_type": "safe_local_ops",
                "summary": "Apply safe local Hermes bundle",
                "items": [
                    {
                        "kind": "memory_correct",
                        "memory_id": created["memory"]["memory_id"],
                        "content": "User prefers specific explanatory nudges.",
                        "confidence": 0.91,
                    },
                    {
                        "kind": "task_metadata_upsert",
                        "task_key": "laundry-check",
                        "metadata": {"task_type": "laundry_home", "rollover_policy": "carry_until_done"},
                    },
                ],
                "simulation": {
                    "before": {"memory_updates": 0, "task_metadata_updates": 0},
                    "after": {"memory_updates": 1, "task_metadata_updates": 1},
                },
            }
        )
    )
    pending = _decode(tools.handle_security({"action": "list_pending"}))["pending"]
    approved = _decode(tools.handle_security({"action": "approve_request", "request_id": pending[0]["request_id"]}))
    listed = _decode(tools.handle_runtime({"action": "memory_console", "mode": "list"}))
    status = _decode(tools.handle_runtime({"action": "todoist_rule_store", "mode": "status"}))

    assert result["success"] is False
    assert approved["success"] is True
    assert approved["result"]["success"] is True
    assert approved["result"]["applied_count"] == 2
    assert approved["result"]["skipped_count"] == 0
    assert listed["memories"][0]["content"] == "User prefers specific explanatory nudges."
    assert status["task_metadata"]["laundry-check"]["task_type"] == "laundry_home"


def test_approval_bundle_execution_returns_summary_with_simulation():
    result = _decode(
        tools.handle_runtime(
            {
                "action": "approval_bundle",
                "mode": "create",
                "bundle_type": "safe_local_ops",
                "summary": "Apply metadata-only bundle",
                "items": [
                    {
                        "kind": "task_metadata_upsert",
                        "task_key": "breakfast-habit",
                        "metadata": {"task_type": "meal_breakfast", "rollover_policy": "skip_if_missed"},
                    }
                ],
                "simulation": {
                    "before": {"today_count": 14, "stale_count": 6},
                    "after": {"today_count": 13, "stale_count": 5},
                },
            }
        )
    )
    pending = _decode(tools.handle_security({"action": "list_pending"}))["pending"]
    approved = _decode(tools.handle_security({"action": "approve_request", "request_id": pending[0]["request_id"]}))

    assert approved["success"] is True
    assert approved["result"]["summary"]["bundle_type"] == "safe_local_ops"
    assert approved["result"]["summary"]["applied_count"] == 1
    assert approved["result"]["summary"]["simulation"]["after"]["stale_count"] == 5


def test_bad_nudge_feedback_creates_self_improvement_rule_and_eval_proposal():
    tools._write_json(
        tools.OPERATOR_STATE_PATH,
        {
            "nudge_records": [
                {
                    "id": "nudge_1",
                    "message_id": "99",
                    "task_id": "task_1",
                    "task_title": "Eat eggs and vegetables for breakfast",
                    "sent_at": "2026-05-19T19:00:00-06:00",
                    "message_class": "operator_brief",
                    "message": "Eat breakfast now.",
                    "buttons": ["Ate it", "Skipped", "Bad nudge"],
                    "outcome": "pending",
                    "user_action": None,
                }
            ]
        },
    )

    _decode(
        tools.handle_runtime(
            {
                "action": "event_ingest",
                "event_type": "telegram_feedback",
                "source": "telegram-callback",
                "message_id": "99",
                "feedback": "bad_nudge",
                "task_id": "task_1",
            }
        )
    )
    proposals = _decode(tools.handle_runtime({"action": "self_improve_proposals", "mode": "list"}))

    assert proposals["success"] is True
    assert proposals["proposal_count"] == 1
    assert proposals["proposals"][0]["kind"] == "bad_nudge_rule"
    assert "Breakfast" in proposals["proposals"][0]["rule_summary"]
    assert proposals["proposals"][0]["eval_case"]["expected_behavior"]


def test_runtime_trace_event_records_receipt_and_trace_status_reads_it():
    logged = _decode(
        tools.handle_runtime(
            {
                "action": "trace_event",
                "trace_type": "operator_cycle",
                "status": "success",
                "data": {"task_title": "Laundry check", "decision": "stay_quiet"},
            }
        )
    )
    status = _decode(tools.handle_runtime({"action": "trace_status"}))

    assert logged["success"] is True
    assert logged["trace"]["trace_id"]
    assert status["success"] is True
    assert status["trace_count"] == 1
    assert status["recent_traces"][0]["trace_type"] == "operator_cycle"


def test_trace_event_metadata_includes_family_span_tags_and_langfuse_context():
    env_path = tools.HERMES_HOME / ".env"
    env_path.write_text(
        "\n".join(
            [
                "HERMES_LANGFUSE_PUBLIC_KEY=pk-lf-test",
                "HERMES_LANGFUSE_SECRET_KEY=sk-lf-test",
                "HERMES_LANGFUSE_BASE_URL=https://us.cloud.langfuse.com",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    logged = _decode(
        tools.handle_runtime(
            {
                "action": "trace_event",
                "trace_type": "operator_cycle",
                "span_name": "operator_brief",
                "trace_family": "operator",
                "status": "success",
                "tags": ["operator", "adaptive_nudge"],
                "data": {"task_title": "Laundry check", "decision": "digest"},
            }
        )
    )

    assert logged["success"] is True
    assert logged["trace"]["trace_family"] == "operator"
    assert logged["trace"]["span_name"] == "operator_brief"
    assert logged["trace"]["tags"] == ["operator", "adaptive_nudge"]
    assert logged["trace"]["langfuse"]["configured"] is True
    assert logged["trace"]["langfuse"]["base_url"] == "https://us.cloud.langfuse.com"


def test_runtime_trace_status_reports_langfuse_env_configuration():
    env_path = tools.HERMES_HOME / ".env"
    env_path.write_text(
        "\n".join(
            [
                "HERMES_LANGFUSE_PUBLIC_KEY=pk-lf-test",
                "HERMES_LANGFUSE_SECRET_KEY=sk-lf-test",
                "HERMES_LANGFUSE_BASE_URL=https://us.cloud.langfuse.com",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    status = _decode(tools.handle_runtime({"action": "trace_status"}))

    assert status["langfuse"]["configured"] is True
    assert status["langfuse"]["base_url"] == "https://us.cloud.langfuse.com"


def test_operator_brief_trace_emission_appends_runtime_trace(monkeypatch):
    monkeypatch.setattr(tools, "_todoist_mcp_intelligence", lambda args: _fake_operator_intelligence())
    monkeypatch.setattr(tools, "_runtime_presence_status", lambda now=None: {
        "configured": True,
        "can_proactively_message": True,
        "confidence": 0.9,
        "summary": "present",
    })
    monkeypatch.setattr(tools, "_mood_router_status", lambda: {"last_mood": {"label": "neutral"}, "model_status": {}})
    monkeypatch.setattr(tools, "_focus_guard_read_state", lambda: {"status": "available"})
    monkeypatch.setattr(tools, "_runtime_live_watch_status", lambda: {"configured": True})
    monkeypatch.setattr(tools, "_adaptive_companion_now_local_hour", lambda: 10)
    monkeypatch.setattr(tools, "_common_sense_now", lambda: real_datetime.fromisoformat("2026-05-19T10:00:00-06:00"))

    result = _decode(tools.handle_runtime({"action": "operator_brief", "allow_message": True}))
    trace_status = _decode(tools.handle_runtime({"action": "trace_status"}))

    assert result["success"] is True
    assert trace_status["trace_count"] >= 1
    operator_trace = trace_status["recent_traces"][-1]
    assert operator_trace["trace_type"] == "operator_cycle"
    assert operator_trace["span_name"] == "operator_brief"
    assert operator_trace["data"]["adaptive_route"] == result["adaptive_nudge"]["route"]
    assert operator_trace["data"]["top_task_title"] == result["top_task"]["title"]


def test_runtime_eval_suite_export_writes_promptfoo_cases_from_proposals():
    tools._write_json(
        tools.SELF_IMPROVE_PROPOSALS_PATH,
        {
            "proposals": [
                {
                    "proposal_id": "proposal_1",
                    "kind": "bad_nudge_rule",
                    "task_title": "Eat eggs and vegetables for breakfast",
                    "eval_case": {
                        "name": "breakfast_after_hours_bad_nudge",
                        "input": {"task": "Eat eggs and vegetables for breakfast", "current_time": "19:00"},
                        "expected_behavior": "Do not suggest eating breakfast now; offer log, skipped, or prep tomorrow.",
                    },
                }
            ]
        },
    )

    result = _decode(tools.handle_runtime({"action": "eval_suite_export"}))

    assert result["success"] is True
    assert result["case_count"] > 1
    exported = tools._read_json(tools.PROMPTFOO_EVALS_PATH, {})
    descriptions = [case["description"] for case in exported["tests"]]
    assert "breakfast_after_hours_bad_nudge" in descriptions


def test_eval_suite_export_writes_promptfoo_config_and_command_hints():
    tools._write_json(
        tools.SELF_IMPROVE_PROPOSALS_PATH,
        {
            "proposals": [
                {
                    "proposal_id": "proposal_1",
                    "kind": "bad_nudge_rule",
                    "task_title": "Laundry check",
                    "eval_case": {
                        "name": "laundry_evening_bad_nudge",
                        "input": {"task": "Laundry check", "current_time": "23:30"},
                        "expected_behavior": "Stay quiet or defer instead of nudging laundry late at night.",
                    },
                }
            ]
        },
    )

    result = _decode(tools.handle_runtime({"action": "eval_suite_export"}))

    assert result["success"] is True
    assert result["case_count"] > 1
    assert result["config_path"]
    assert "promptfoo eval" in result["command_hint"]
    config = tools._read_json(Path(result["config_path"]), {})
    assert config["tests_file"] == str(tools.PROMPTFOO_EVALS_PATH)
    assert config["prompts"]
    assert config["providers"]
    assert config["tests"]


def test_eval_suite_export_includes_builtin_bad_nudge_common_sense_cases():
    from plugins.personal_ops.promptfoo_suite import builtin_common_sense_cases

    assert builtin_common_sense_cases()

    result = _decode(tools.handle_runtime({"action": "eval_suite_export"}))
    exported = tools._read_json(tools.PROMPTFOO_EVALS_PATH, {})
    descriptions = {case["description"] for case in exported["tests"]}

    assert result["success"] is True
    assert result["case_count"] >= 10
    assert {
        "builtin_breakfast_after_window",
        "builtin_business_contact_after_hours",
        "builtin_morning_launch_at_night",
        "builtin_laundry_evening_recoverable",
        "builtin_laundry_quiet_hours",
        "builtin_vague_junk_drawer_repair",
        "builtin_reference_task_not_execution_priority",
        "builtin_todoist_prompt_injection",
        "builtin_repeat_bad_nudge_suppression",
        "builtin_family_handoff_repair_not_scoreboard",
    }.issubset(descriptions)


def test_builtin_promptfoo_cases_have_real_assertions_and_structured_inputs():
    _decode(tools.handle_runtime({"action": "eval_suite_export"}))
    exported = tools._read_json(tools.PROMPTFOO_EVALS_PATH, {})

    for case in exported["tests"]:
        assert case["vars"]["input_json"].startswith("{")
        assert case["assert"]
        assert case["metadata"]["source"] in {"builtin_common_sense", "self_improve_proposal", "trace_failure"}

    breakfast = next(case for case in exported["tests"] if case["description"] == "builtin_breakfast_after_window")
    assert {"contains", "not-contains"} <= {item["type"] for item in breakfast["assert"]}
    assert any("Quick log" in item["value"] for item in breakfast["assert"] if item["type"] == "contains")


def test_live_watch_state_compaction_removes_raw_task_bulk():
    oversized = {
        "ran_at": "2026-05-18T12:00:00+00:00",
        "focus_guard": {
            "status": "needs_focus",
            "raw_tasks": [
                {"id": str(index), "content": f"Task {index}", "description": "x" * 2000}
                for index in range(40)
            ],
            "tasks": [
                {"id": str(index), "content": f"Visible {index}", "description": "y" * 2000}
                for index in range(40)
            ],
        },
        "adaptive_companion": {
            "state": {
                "nudge_records": [
                    {"id": str(index), "message": "z" * 2000}
                    for index in range(50)
                ]
            }
        },
    }

    compacted = tools._compact_live_watch_payload(oversized)

    assert "raw_tasks" not in compacted["focus_guard"]
    assert len(compacted["focus_guard"]["tasks"]) <= 12
    assert len(compacted["adaptive_companion"]["state"]["nudge_records"]) <= 12
    encoded = json.dumps(compacted)
    assert len(encoded) < 25000
    assert len(compacted["focus_guard"]["tasks"][0]["description"]) < 700


def test_trace_failure_to_eval_adds_case_from_failed_trace():
    _decode(
        tools.handle_runtime(
            {
                "action": "trace_event",
                "trace_type": "operator_cycle",
                "span_name": "operator_brief",
                "trace_family": "operator",
                "status": "failure",
                "tags": ["operator", "bad_nudge"],
                "data": {
                    "task_title": "Eat eggs and vegetables for breakfast",
                    "task_type": "meal_breakfast",
                    "current_time": "19:00",
                    "expected_behavior": "Do not suggest eating breakfast now; offer log, skipped, or prep tomorrow.",
                },
            }
        )
    )

    result = _decode(tools.handle_runtime({"action": "eval_suite_export"}))
    exported = tools._read_json(tools.PROMPTFOO_EVALS_PATH, {})

    assert result["success"] is True
    assert result["case_count"] >= 1
    descriptions = [item["description"] for item in exported["tests"]]
    assert any("trace_failure" in desc for desc in descriptions)


def test_capture_bot_callback_dispatches_telegram_feedback(monkeypatch):
    import importlib
    import asyncio

    calls = []
    fake_filters = types.SimpleNamespace(TEXT=object(), COMMAND=object(), VOICE=object(), AUDIO=object())
    fake_ext = types.SimpleNamespace(
        Application=types.SimpleNamespace(builder=lambda: None),
        CommandHandler=object,
        ContextTypes=types.SimpleNamespace(DEFAULT_TYPE=object),
        MessageHandler=object,
        CallbackQueryHandler=object,
        filters=fake_filters,
    )
    monkeypatch.setitem(sys.modules, "telegram", types.SimpleNamespace(Update=object))
    monkeypatch.setitem(sys.modules, "telegram.ext", fake_ext)
    capture_bot = importlib.import_module("hermes_capture_bot")
    monkeypatch.setattr(capture_bot, "_ensure_allowed", lambda update: _async_true())
    monkeypatch.setattr(
        capture_bot,
        "tools",
        types.SimpleNamespace(
            handle_runtime=lambda payload: calls.append(payload) or json.dumps({"success": True, "handled": True, "event_type": "telegram_feedback"})
        ),
    )

    class FakeCallbackQuery:
        def __init__(self):
            self.data = "hermes_feedback:bad_nudge"
            self.answered = False
            self.message = types.SimpleNamespace(message_id=321)

        async def answer(self):
            self.answered = True

        async def edit_message_text(self, text):
            self.edited = text

    callback = FakeCallbackQuery()
    update = types.SimpleNamespace(
        effective_user=types.SimpleNamespace(id=1),
        callback_query=callback,
        effective_message=types.SimpleNamespace(reply_text=_async_reply),
    )

    asyncio.run(capture_bot._handle_callback(update, None))

    assert callback.answered is True
    assert calls
    assert calls[0]["action"] == "event_ingest"
    assert calls[0]["event_type"] == "telegram_feedback"
    assert calls[0]["message_id"] == "321"
    assert calls[0]["feedback"] == "bad_nudge"


def test_runtime_event_ingest_outing_request_creates_todoist_and_proposal(monkeypatch):
    created = []
    monkeypatch.setattr(
        tools,
        "_execute_todoist",
        lambda payload: created.append(payload) or {"success": True, "action": "add_task", "task": {"content": payload["content"]}},
    )
    monkeypatch.setattr(tools, "_focus_guard_read_state", lambda: {})

    result = _decode(
        tools.handle_runtime(
            {
                "action": "event_ingest",
                "event_type": "outing_request",
                "budget": "low",
                "time_window": "this afternoon",
                "energy": "medium",
                "auto_create_todoist": True,
            }
        )
    )

    assert result["success"] is True
    assert result["event_type"] == "outing_request"
    assert result["options"]
    assert result["calendar_proposal"]["status"] == "proposal_only"
    assert created


def test_runtime_event_ingest_voice_capture_routes_task_to_todoist(monkeypatch):
    created = []
    monkeypatch.setattr(
        tools,
        "_execute_todoist",
        lambda payload: created.append(payload) or {"success": True, "action": "add_task", "task": {"content": payload["content"]}},
    )
    monkeypatch.setattr(tools, "_focus_guard_read_state", lambda: {})
    monkeypatch.setattr(tools, "_focus_guard_send_telegram_message", lambda text, **kwargs: {"ok": True})

    result = _decode(
        tools.handle_runtime(
            {
                "action": "event_ingest",
                "event_type": "voice_memo_received",
                "transcript": "I need to follow up with the contractor about the leak tomorrow.",
                "auto_create_todoist": True,
                "source": "telegram",
            }
        )
    )

    assert result["success"] is True
    assert result["classification"]["kind"] == "task_capture"
    assert created


def test_runtime_event_ingest_voice_capture_routes_work_log_without_todoist(monkeypatch):
    monkeypatch.setattr(tools, "_focus_guard_read_state", lambda: {})
    monkeypatch.setattr(tools, "_focus_guard_send_telegram_message", lambda text, **kwargs: {"ok": True})
    result = _decode(
        tools.handle_runtime(
            {
                "action": "event_ingest",
                "event_type": "voice_memo_received",
                "transcript": "Today I worked on the Calgary landing page for two hours and cleaned up the hero section.",
                "source": "telegram",
            }
        )
    )

    assert result["success"] is True
    assert result["classification"]["kind"] == "work_log"
    assert result["todoist"] is None


def test_mood_router_ingests_text_without_storing_raw_content():
    result = _decode(
        tools.handle_runtime(
            {
                "action": "mood_route",
                "text": "I am frustrated and confused because the Telegram bot keeps sending nonsense.",
                "source": "telegram-text",
            }
        )
    )
    state = _decode(tools.handle_runtime({"action": "mood_status"}))

    assert result["success"] is True
    assert result["mood"]["label"] == "frustrated"
    assert result["mood"]["style_policy"]["tone"] == "warm"
    assert "text" in result["mood"]["modalities"]
    assert "raw_text" not in state["last_mood"]
    assert "transcript" not in state["last_mood"]
    assert "Telegram bot" not in json.dumps(state)


def test_mood_router_fuses_text_and_voice_tone_into_low_energy():
    result = _decode(
        tools.handle_runtime(
            {
                "action": "mood_route",
                "text": "I am tired and overwhelmed today.",
                "audio_emotions": {"sad": 0.72, "neutral": 0.18},
                "source": "telegram-voice",
            }
        )
    )

    assert result["mood"]["label"] == "low_energy"
    assert result["mood"]["style_policy"]["pace"] == "slow"
    assert result["mood"]["style_policy"]["next_step_size"] == "tiny"
    assert result["mood"]["evidence_summary"] == "text+voice mood signal"


def test_voice_capture_updates_mood_router_but_keeps_voice_log_raw_transcript(monkeypatch):
    monkeypatch.setattr(tools, "_execute_todoist", lambda payload: {"success": True, "task": {"content": payload["content"]}})
    monkeypatch.setattr(tools, "_focus_guard_send_telegram_message", lambda text, **kwargs: {"ok": True})

    result = _decode(
        tools.handle_runtime(
            {
                "action": "event_ingest",
                "event_type": "voice_memo_received",
                "transcript": "I need to follow up but I feel overwhelmed and stuck.",
                "audio_emotions": {"sad": 0.66},
                "source": "telegram-voice",
                "auto_create_todoist": False,
            }
        )
    )
    mood_state = _decode(tools.handle_runtime({"action": "mood_status"}))

    assert result["success"] is True
    assert result["mood"]["label"] == "low_energy"
    assert mood_state["last_mood"]["source"] == "telegram-voice"
    assert "follow up" not in json.dumps(mood_state)


def test_adaptive_companion_strategy_softens_when_mood_router_sees_low_energy():
    state = tools._adaptive_companion_default_state()
    state["mood_router"] = {
        "last_mood": {
            "label": "low_energy",
            "confidence": 0.76,
            "style_policy": {"tone": "encouraging", "pace": "slow", "next_step_size": "tiny"},
        }
    }

    strategy = tools._adaptive_companion_select_response_strategy(
        trigger={"kind": "focus_drift", "task_label": "Family handoff"},
        inferred_state="drifting",
        state=state,
        now_hour=14,
    )

    assert strategy["pressure"] == "warm"
    assert strategy["energy"] == "calm"
    assert strategy["length"] == "short"


def test_runtime_self_improve_waits_for_second_inactive_check_before_restart(monkeypatch):
    monkeypatch.setattr(
        tools,
        "_runtime_service_status",
        lambda service_name=tools.RUNTIME_SERVICE_NAME: {"service": service_name, "active": False, "state": "failed"},
    )
    monkeypatch.setattr(
        tools,
        "_runtime_restart_user_service",
        lambda service_name: {"service": service_name, "ok": True, "output": "restarted"},
    )
    monkeypatch.setattr(
        tools,
        "_runtime_live_watch_run",
        lambda **kwargs: {"success": True, "ran_at": "2026-05-18T12:00:00+00:00"},
    )
    monkeypatch.setattr(tools, "_runtime_recent_incidents", lambda **kwargs: [])
    monkeypatch.setattr(tools, "_runtime_upstream_status", lambda **kwargs: {"local": {"behind": 0}, "recent_commit_count": 0})

    result = _decode(tools.handle_runtime({"action": "self_improve"}))

    assert result["success"] is True
    assert any(action["kind"] == "refresh_live_watch" for action in result["actions"])
    assert not any(action["kind"] == "restart_service" for action in result["actions"])


def test_runtime_self_improve_restarts_after_second_inactive_check(monkeypatch):
    monkeypatch.setattr(
        tools,
        "_runtime_service_status",
        lambda service_name=tools.RUNTIME_SERVICE_NAME: {"service": service_name, "active": False, "state": "failed"},
    )
    monkeypatch.setattr(
        tools,
        "_runtime_restart_user_service",
        lambda service_name: {"service": service_name, "ok": True, "output": "restarted"},
    )
    monkeypatch.setattr(
        tools,
        "_runtime_live_watch_run",
        lambda **kwargs: {"success": True, "ran_at": "2026-05-18T12:00:00+00:00"},
    )
    monkeypatch.setattr(tools, "_runtime_recent_incidents", lambda **kwargs: [])
    monkeypatch.setattr(tools, "_runtime_upstream_status", lambda **kwargs: {"local": {"behind": 0}, "recent_commit_count": 0})

    _decode(tools.handle_runtime({"action": "self_improve"}))
    result = _decode(tools.handle_runtime({"action": "self_improve"}))

    assert result["success"] is True
    assert any(action["kind"] == "restart_service" for action in result["actions"])


def test_runtime_self_improve_repairs_cron_jobs_and_restores_status_message(monkeypatch):
    tools._write_json(
        tools.CRON_JOBS_PATH,
        {
            "jobs": [
                {"id": "hermeslivewatch24x7", "script": "wrong.py", "enabled": False, "state": "paused", "schedule": {"expr": "0 * * * *"}},
                {"id": "hermesselfimprove24x7", "script": "wrong2.py", "enabled": False, "state": "paused", "schedule": {"expr": "0 * * * *"}},
            ]
        },
    )
    tools._write_json(
        tools.LIVE_WATCH_STATE_PATH,
        {
            "ran_at": "2099-05-18T12:00:00+00:00",
            "focus_guard": {"status": "needs_focus", "most_important_task": {"content": "Plan simple outing"}},
            "adaptive_companion": {"sent": False, "reason": "cooldown"},
        },
    )
    monkeypatch.setattr(
        tools,
        "_runtime_service_status",
        lambda service_name=tools.RUNTIME_SERVICE_NAME: {"service": service_name, "active": True, "state": "active"},
    )
    monkeypatch.setattr(tools, "_runtime_recent_incidents", lambda **kwargs: [])
    monkeypatch.setattr(tools, "_runtime_upstream_status", lambda **kwargs: {"local": {"behind": 0}, "recent_commit_count": 0})
    monkeypatch.setattr(tools, "_telegram_messages_allowed_now", lambda now_hour=None: True)
    monkeypatch.setattr(tools, "_runtime_live_watch_update_status_message", lambda payload: {"chat_id": "chat", "message_id": 123})

    result = _decode(tools.handle_runtime({"action": "self_improve"}))
    repaired = next(action for action in result["actions"] if action["kind"] == "repair_cron_jobs")
    restored = next(action for action in result["actions"] if action["kind"] == "restore_status_message")
    cron = tools._read_json(tools.CRON_JOBS_PATH, {})
    jobs = {job["id"]: job for job in cron["jobs"]}
    state = tools._read_json(tools.LIVE_WATCH_STATE_PATH, {})

    assert repaired["ok"] is True
    assert set(repaired["jobs"]) == {"hermeslivewatch24x7", "hermesselfimprove24x7"}
    assert jobs["hermeslivewatch24x7"]["enabled"] is True
    assert jobs["hermesselfimprove24x7"]["script"] == "hermes_self_improve.py"
    assert restored["message_id"] == 123
    assert state["status_message"]["message_id"] == 123


def test_runtime_self_improve_surfaces_candidate_skills(monkeypatch):
    tools._append_jsonl(
        tools.EVENTS_PATH,
        {"ts": 1, "type": "runtime_event_ingested", "event_type": "desktop_unlocked", "source": "windows-unlock-trigger"},
    )
    tools._append_jsonl(
        tools.EVENTS_PATH,
        {"ts": 2, "type": "runtime_event_ingested", "event_type": "desktop_unlocked", "source": "windows-unlock-trigger"},
    )
    tools._append_jsonl(
        tools.EVENTS_PATH,
        {"ts": 3, "type": "runtime_event_ingested", "event_type": "desktop_unlocked", "source": "windows-unlock-trigger"},
    )
    tools._write_json(
        tools.ADAPTIVE_COMPANION_STATE_PATH,
        {
            "completion_history": [
                {
                    "task_id": "1",
                    "task_label": "Plan simple outing",
                    "style": "amused_contempt",
                    "family": "pattern_mirror",
                    "pattern": "smart_detour",
                    "completed_at": "2026-05-18T08:00:00+00:00",
                    "outcome": "completed_after_nudge",
                },
                {
                    "task_id": "2",
                    "task_label": "Plan simple outing",
                    "style": "amused_contempt",
                    "family": "pattern_mirror",
                    "pattern": "smart_detour",
                    "completed_at": "2026-05-18T09:00:00+00:00",
                    "outcome": "completed_after_nudge",
                },
                {
                    "task_id": "3",
                    "task_label": "Plan simple outing",
                    "style": "amused_contempt",
                    "family": "pattern_mirror",
                    "pattern": "smart_detour",
                    "completed_at": "2026-05-18T10:00:00+00:00",
                    "outcome": "completed_after_nudge",
                },
            ]
        },
    )
    tools._write_json(
        tools.LIVE_WATCH_STATE_PATH,
        {
            "ran_at": "2099-05-18T12:00:00+00:00",
            "focus_guard": {"status": "needs_focus"},
            "adaptive_companion": {"sent": False, "reason": "cooldown"},
            "status_message": {"chat_id": "chat", "message_id": 1},
        },
    )
    monkeypatch.setattr(
        tools,
        "_runtime_service_status",
        lambda service_name=tools.RUNTIME_SERVICE_NAME: {"service": service_name, "active": True, "state": "active"},
    )
    monkeypatch.setattr(tools, "_runtime_recent_incidents", lambda **kwargs: [])
    monkeypatch.setattr(tools, "_runtime_upstream_status", lambda **kwargs: {"local": {"behind": 0}, "recent_commit_count": 0})

    result = _decode(tools.handle_runtime({"action": "self_improve"}))

    assert result["success"] is True
    assert len(result["candidate_skills"]) >= 3
    ids = {item["id"] for item in result["candidate_skills"]}
    assert "workflow:desktop_unlocked:windows-unlock-trigger" in ids
    assert "intervention:pattern_mirror:smart_detour" in ids
    assert "style:amused_contempt" in ids


def test_runtime_self_improve_report_creates_approval_request(monkeypatch):
    monkeypatch.setattr(tools, "_runtime_service_status", lambda service_name=tools.RUNTIME_SERVICE_NAME: {
        "active": True,
        "state": "active",
        "service": service_name,
    })
    monkeypatch.setattr(tools, "_runtime_upstream_status", lambda **kwargs: {
        "recent_commit_count": 2,
        "local": {"behind": 3, "origin_ref": "origin/hermes/update-upstream-2026-06-18"},
    })
    monkeypatch.setattr(tools, "_runtime_recent_incidents", lambda **kwargs: [{"type": "example_incident"}])
    tools._write_json(tools.LIVE_WATCH_STATE_PATH, {
        "ran_at": "2026-05-19T12:00:00+00:00",
        "operator_brief": {"summary": "operator"},
        "agi_operator_cycle": {"decision": {"best_move": "stay_quiet"}},
    })

    result = _decode(tools.handle_runtime({"action": "self_improve_report", "create_approval": True}))
    pending = _decode(tools.handle_security({"action": "list_pending"}))["pending"]

    assert result["approval_required"] is True
    assert result["request_id"]
    assert pending[0]["tool"] == "personal_runtime"
    assert pending[0]["action"] == "apply_self_improve_report"
    assert pending[0]["payload"]["action"] == "self_improve_apply"
    assert pending[0]["payload"]["report"]["recommendations"]
    upstream_items = [item for item in result["report"]["recommendations"] if item["kind"] == "upstream_review"]
    assert upstream_items
    assert "origin/hermes/update-upstream-2026-06-18" in upstream_items[0]["summary"]
    assert upstream_items[0]["evidence"]["origin_ref"] == "origin/hermes/update-upstream-2026-06-18"


def test_runtime_self_improve_report_can_send_proactive_telegram(monkeypatch):
    sent = []
    monkeypatch.setattr(tools, "_focus_guard_send_telegram_message", lambda text, **kwargs: sent.append(text) or {"ok": True})
    monkeypatch.setattr(tools, "_telegram_messages_allowed_now", lambda now_hour=None: True)
    monkeypatch.setattr(tools, "_runtime_service_status", lambda service_name=tools.RUNTIME_SERVICE_NAME: {
        "active": True,
        "state": "active",
        "service": service_name,
    })
    monkeypatch.setattr(tools, "_runtime_upstream_status", lambda **kwargs: {
        "recent_commit_count": 1,
        "local": {"behind": 2, "origin_ref": "origin/hermes/update-upstream-2026-06-18"},
    })
    monkeypatch.setattr(tools, "_runtime_recent_incidents", lambda **kwargs: [])

    result = _decode(tools.handle_runtime({
        "action": "self_improve_report",
        "create_approval": True,
        "send_telegram": True,
    }))

    assert result["approval_required"] is True
    assert result["sent"] is True
    assert sent
    assert result["request_id"] in sent[0]
    assert "Self-improvement report" in sent[0]
    assert "origin/hermes/update-upstream-2026-06-18" in sent[0]
    assert "Approve:" in sent[0]


def test_runtime_self_improve_report_throttles_repeat_telegram(monkeypatch):
    sent = []
    monkeypatch.setattr(tools, "_focus_guard_send_telegram_message", lambda text, **kwargs: sent.append(text) or {"ok": True})
    monkeypatch.setattr(tools, "_telegram_messages_allowed_now", lambda now_hour=None: True)
    monkeypatch.setattr(tools, "_runtime_service_status", lambda service_name=tools.RUNTIME_SERVICE_NAME: {
        "active": True,
        "state": "active",
        "service": service_name,
    })
    monkeypatch.setattr(tools, "_runtime_upstream_status", lambda **kwargs: {
        "recent_commit_count": 1,
        "local": {"behind": 2},
    })
    monkeypatch.setattr(tools, "_runtime_recent_incidents", lambda **kwargs: [])

    first = _decode(tools.handle_runtime({"action": "self_improve_report", "send_telegram": True}))
    second = _decode(tools.handle_runtime({"action": "self_improve_report", "send_telegram": True}))
    pending = _decode(tools.handle_security({"action": "list_pending"}))["pending"]

    assert first["sent"] is True
    assert second["sent"] is False
    assert second["send_reason"] == "same_report_recently_sent"
    assert len(sent) == 1
    assert len(pending) == 1


def test_security_approval_can_apply_self_improve_report(monkeypatch):
    monkeypatch.setattr(tools, "_runtime_self_improve_run", lambda: {
        "success": True,
        "ran_at": "now",
        "actions": [{"kind": "repair_cron_jobs"}],
        "observations": ["cron jobs repaired"],
        "summary": "applied",
    })
    request = _decode(tools.handle_runtime({"action": "self_improve_report", "create_approval": True}))

    result = _decode(tools.handle_security({
        "action": "approve_request",
        "request_id": request["request_id"],
    }))

    assert result["success"] is True
    assert result["approved"] is True
    assert result["result"]["success"] is True
    assert result["result"]["summary"] == "applied"


def test_self_improve_pipeline_propose_creates_branch_stages_and_approval():
    tools._write_json(
        tools.SELF_IMPROVE_PROPOSALS_PATH,
        {
            "proposals": [
                {
                    "proposal_id": "proposal_1",
                    "kind": "bad_nudge_rule",
                    "task_title": "Eat eggs and vegetables for breakfast",
                    "rule_summary": "Breakfast tasks should not be nudged after late morning.",
                    "eval_case": {"name": "breakfast_after_hours_bad_nudge"},
                }
            ]
        },
    )

    result = _decode(tools.handle_runtime({"action": "self_improve_pipeline", "mode": "propose"}))
    pending = _decode(tools.handle_security({"action": "list_pending"}))["pending"]

    assert result["success"] is False
    assert result["approval_required"] is True
    assert result["pipeline"]["pipeline_id"]
    assert result["pipeline"]["branch_name"].startswith("hermes/self-improve/")
    assert result["pipeline"]["stages"][0] == "detect"
    assert "rollback" in result["pipeline"]["stages"]
    assert pending[0]["action"] == "self_improve_pipeline_apply"


def test_security_approval_can_apply_self_improve_pipeline_and_track_next_stage():
    tools._write_json(
        tools.SELF_IMPROVE_PROPOSALS_PATH,
        {
            "proposals": [
                {
                    "proposal_id": "proposal_1",
                    "kind": "bad_nudge_rule",
                    "task_title": "Laundry check",
                    "rule_summary": "Late-night laundry nudges should prefer silence.",
                }
            ]
        },
    )

    proposed = _decode(tools.handle_runtime({"action": "self_improve_pipeline", "mode": "propose"}))
    approved = _decode(tools.handle_security({"action": "approve_request", "request_id": proposed["request_id"]}))
    status = _decode(tools.handle_runtime({"action": "self_improve_pipeline", "mode": "status"}))

    assert approved["success"] is True
    assert approved["result"]["success"] is True
    assert approved["result"]["pipeline"]["approved_at"]
    assert approved["result"]["pipeline"]["current_stage"] == "approval"
    assert approved["result"]["pipeline"]["next_stage"] == "patch"
    assert approved["result"]["pipeline"]["rollback"]["strategy"] == "revert_branch_or_restore_previous_runtime_state"
    assert status["pipeline_count"] >= 1


def test_self_improve_pipeline_artifacts_are_present_on_proposal_and_approval():
    tools._write_json(
        tools.SELF_IMPROVE_PROPOSALS_PATH,
        {
            "proposals": [
                {
                    "proposal_id": "proposal_1",
                    "kind": "bad_nudge_rule",
                    "task_title": "Laundry check",
                    "rule_summary": "Late-night laundry nudges should prefer silence.",
                }
            ]
        },
    )

    proposed = _decode(tools.handle_runtime({"action": "self_improve_pipeline", "mode": "propose"}))
    proposal_artifacts = proposed["pipeline"]["artifacts"]
    patch_plan_path = Path(proposal_artifacts["patch_plan_path"])
    test_summary_path = Path(proposal_artifacts["test_summary_path"])
    diff_summary_path = Path(proposal_artifacts["diff_summary_path"])
    assert json.loads(test_summary_path.read_text(encoding="utf-8"))["stage"] == "proposed"

    approved = _decode(tools.handle_security({"action": "approve_request", "request_id": proposed["request_id"]}))

    approved_artifacts = approved["result"]["pipeline"]["artifacts"]
    rollback_notes_path = Path(approved_artifacts["rollback_notes_path"])

    assert proposal_artifacts["artifact_dir"]
    assert proposal_artifacts["patch_plan_path"].endswith(".md")
    assert proposal_artifacts["test_summary_path"].endswith(".json")
    assert proposal_artifacts["diff_summary_path"].endswith(".md")
    assert approved_artifacts["rollback_notes_path"].endswith(".md")
    assert approved["result"]["pipeline"]["verify_checklist"]
    assert patch_plan_path.exists()
    assert test_summary_path.exists()
    assert diff_summary_path.exists()
    assert rollback_notes_path.exists()
    assert "Hermes Self-Improve Patch Plan" in patch_plan_path.read_text(encoding="utf-8")
    assert proposed["pipeline"]["branch_name"] in patch_plan_path.read_text(encoding="utf-8")
    assert json.loads(test_summary_path.read_text(encoding="utf-8"))["stage"] == "approved"
    assert "Diff Strategy" in diff_summary_path.read_text(encoding="utf-8")
    assert "approved" in rollback_notes_path.read_text(encoding="utf-8")


def test_external_systems_status_reports_scaffolding_and_risk_policy():
    env_path = tools.HERMES_HOME / ".env"
    env_path.write_text(
        "\n".join(
            [
                "HERMES_CALENDAR_PROVIDER=local_stub",
                "HERMES_HOME_ASSISTANT_URL=http://ha.local:8123",
                "HERMES_PAPERLESS_URL=http://paperless.local",
                "HERMES_ACTUAL_BUDGET_URL=http://actual.local",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = _decode(tools.handle_runtime({"action": "external_systems_status"}))

    assert result["success"] is True
    assert result["systems"]["calendar"]["configured"] is True
    assert result["systems"]["home_assistant"]["configured"] is True
    assert result["systems"]["paperless"]["configured"] is True
    assert result["systems"]["actual_budget"]["configured"] is True
    assert result["systems"]["calendar"]["access_mode"] == "observe_or_draft"
    assert result["systems"]["actual_budget"]["risk_policy"] == "read_only_budget_review"


def test_calendar_status_reports_browser_google_calendar_provider():
    env_path = tools.HERMES_HOME / ".env"
    env_path.write_text(
        "\n".join(
            [
                "HERMES_CALENDAR_PROVIDER=browser_google_calendar",
                "HERMES_GOOGLE_CALENDAR_URL=https://calendar.google.com/calendar/u/7/r?pli=1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = _decode(tools.handle_runtime({"action": "calendar_status"}))

    assert result["success"] is True
    assert result["provider"] == "browser_google_calendar"
    assert result["configured"] is True
    assert result["approval_policy"] == "commit_requires_approval"
    assert result["mode"] == "browser_handoff"


def test_calendar_event_draft_creates_prefilled_google_calendar_url():
    env_path = tools.HERMES_HOME / ".env"
    env_path.write_text(
        "\n".join(
            [
                "HERMES_CALENDAR_PROVIDER=browser_google_calendar",
                "HERMES_GOOGLE_CALENDAR_URL=https://calendar.google.com/calendar/u/7/r?pli=1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = _decode(
        tools.handle_runtime(
            {
                "action": "calendar_event",
                "mode": "draft",
                "title": "Hermes admin block",
                "start": "2026-05-20T08:00:00-06:00",
                "end": "2026-05-20T08:30:00-06:00",
                "description": "Close one admin loop.",
            }
        )
    )

    assert result["success"] is True
    assert result["provider"] == "browser_google_calendar"
    assert result["draft"]["title"] == "Hermes admin block"
    assert "calendar.google.com" in result["draft"]["prefill_url"]
    assert result["draft"]["status"] == "draft_ready"


def test_calendar_event_commit_is_approval_gated_and_returns_browser_handoff():
    env_path = tools.HERMES_HOME / ".env"
    env_path.write_text(
        "\n".join(
            [
                "HERMES_CALENDAR_PROVIDER=browser_google_calendar",
                "HERMES_GOOGLE_CALENDAR_URL=https://calendar.google.com/calendar/u/7/r?pli=1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    draft = _decode(
        tools.handle_runtime(
            {
                "action": "calendar_event",
                "mode": "draft",
                "title": "Family handoff",
                "start": "2026-05-20T17:15:00-06:00",
                "end": "2026-05-20T17:45:00-06:00",
                "description": "Transition out of work mode.",
            }
        )
    )
    commit = _decode(
        tools.handle_runtime(
            {
                "action": "calendar_event",
                "mode": "commit",
                "draft_id": draft["draft"]["draft_id"],
            }
        )
    )
    pending = _decode(tools.handle_security({"action": "list_pending"}))["pending"]
    approved = _decode(tools.handle_security({"action": "approve_request", "request_id": pending[0]["request_id"]}))

    assert commit["success"] is False
    assert commit["approval_required"] is True
    assert approved["success"] is True
    assert approved["result"]["success"] is True
    assert approved["result"]["commit"]["status"] == "browser_handoff_ready"
    assert "calendar.google.com" in approved["result"]["commit"]["prefill_url"]


def test_hermes_capabilities_dossier_summarizes_live_and_scaffolded_surfaces():
    env_path = tools.HERMES_HOME / ".env"
    env_path.write_text(
        "\n".join(
            [
                "HERMES_CALENDAR_PROVIDER=browser_google_calendar",
                "HERMES_GOOGLE_CALENDAR_URL=https://calendar.google.com/calendar/u/7/r?pli=1",
                "HERMES_HOME_ASSISTANT_URL=http://ha.local:8123",
                "HERMES_PAPERLESS_URL=http://paperless.local",
                "HERMES_ACTUAL_BUDGET_URL=http://actual.local",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = _decode(tools.handle_runtime({"action": "hermes_capabilities_dossier"}))

    assert result["success"] is True
    assert result["identity"]["mode"] == "bounded_personal_operations_kernel"
    assert result["calendar"]["provider"] == "browser_google_calendar"
    assert result["calendar"]["status"] in {"browser_handoff_ready", "configured"}
    assert result["external_systems"]["actual_budget"]["risk_policy"] == "read_only_budget_review"
    assert "approval_gated" in result["boundaries"]


def test_hermes_system_audit_marks_live_vs_scaffolded_surfaces(monkeypatch):
    for name in (
        "LANGFUSE_SECRET_KEY",
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_BASE_URL",
        "HERMES_LANGFUSE_SECRET_KEY",
        "HERMES_LANGFUSE_PUBLIC_KEY",
        "HERMES_LANGFUSE_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    env_path = tools.HERMES_HOME / ".env"
    env_path.write_text(
        "\n".join(
            [
                "HERMES_CALENDAR_PROVIDER=browser_google_calendar",
                "HERMES_GOOGLE_CALENDAR_URL=https://calendar.google.com/calendar/u/7/r?pli=1",
                "HERMES_HOME_ASSISTANT_URL=http://ha.local:8123",
                "HERMES_PAPERLESS_URL=http://paperless.local",
                "HERMES_ACTUAL_BUDGET_URL=http://actual.local",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    tools._write_json(tools.PRESENCE_STATE_PATH, {"events": []})
    monkeypatch.setattr(
        tools,
        "_runtime_presence_status",
        lambda now=None: {
            "success": True,
            "configured": True,
            "confidence": 0.83,
            "last_signal": {
                "source": "activitywatch-forwarder",
                "event_type": "activitywatch_heartbeat",
            },
            "activitywatch": {"configured": False},
        },
    )

    result = _decode(tools.handle_runtime({"action": "hermes_system_audit"}))

    assert result["success"] is True
    assert result["surfaces"]["calendar"]["status"] == "live"
    assert result["surfaces"]["presence_model"]["status"] == "live"
    assert result["surfaces"]["home_assistant"]["status"] == "scaffolded"
    assert result["surfaces"]["tracing"]["details"]["langfuse_configured_now"] is False
    assert any("Langfuse is not currently configured" in item for item in result["non_connected"])


def test_adaptive_companion_run_stays_quiet_outside_hours(monkeypatch):
    monkeypatch.setattr(tools, "_adaptive_companion_now_local_hour", lambda: 3)

    result = _decode(tools.handle_adaptive_companion({"action": "run", "always_on": True}))

    assert result["success"] is True
    assert result["sent"] is False
    assert result["reason"] == "outside_hours"


def test_adaptive_companion_records_task_completion_from_matching_nudge():
    state = tools._adaptive_companion_default_state()
    state["recent_interventions"] = [
        {
            "trigger": "suspicious_task",
            "style": "amused_contempt",
            "pattern": {"label": "smart_detour"},
            "intervention_family": "pattern_mirror",
            "task_label": "Plan simple outing",
            "task_id": "task-123",
            "strategy": {"pressure": "warm", "language": "conversational", "length": "short", "energy": "calm"},
            "sent_at": "2026-05-18T08:00:00+00:00",
        }
    ]

    updated = tools._adaptive_companion_record_task_completion(
        state=state,
        task_id="task-123",
        completed_at="2026-05-18T08:20:00+00:00",
    )

    assert updated["style_effectiveness"]["amused_contempt"]["completed_after_nudge"] == 1
    assert updated["intervention_family_effectiveness"]["pattern_mirror"]["completed_after_nudge"] == 1
    assert updated["completion_history"][-1]["task_id"] == "task-123"
    assert updated["recent_interventions"][-1]["completion_recorded_at"] == "2026-05-18T08:20:00+00:00"


def test_adaptive_companion_completion_recording_is_idempotent():
    state = tools._adaptive_companion_default_state()
    state["recent_interventions"] = [
        {
            "trigger": "suspicious_task",
            "style": "amused_contempt",
            "pattern": {"label": "smart_detour"},
            "intervention_family": "pattern_mirror",
            "task_label": "Plan simple outing",
            "task_id": "task-123",
            "strategy": {"pressure": "warm", "language": "conversational", "length": "short", "energy": "calm"},
            "sent_at": "2026-05-18T08:00:00+00:00",
            "completion_recorded_at": "2026-05-18T08:20:00+00:00",
        }
    ]

    updated = tools._adaptive_companion_record_task_completion(
        state=state,
        task_id="task-123",
        completed_at="2026-05-18T08:30:00+00:00",
    )

    assert updated["recent_interventions"][-1]["completion_recorded_at"] == "2026-05-18T08:20:00+00:00"
    assert updated["style_effectiveness"] == {}
    assert updated["completion_history"] == []


def test_adaptive_companion_refreshes_insight_lenses():
    state = tools._adaptive_companion_default_state()
    state["pattern_history"] = [
        {"pattern": "smart_detour", "family": "pattern_mirror", "outcome": "corrected"},
        {"pattern": "false_prep", "family": "pattern_mirror", "outcome": "corrected"},
        {"pattern": "smart_detour", "family": "short_punch", "outcome": "corrected"},
    ]
    updated = tools._adaptive_companion_refresh_insight_lenses(
        state=state,
        trigger={"kind": "suspicious_task", "task_label": "Plan simple outing", "evidence": "Read Life OS identity statement"},
        pattern={"label": "smart_detour"},
        focus_state={"status": "needs_focus", "task_count": 50, "suspicious_tasks": [{"task": {"id": "x"}}] * 3},
        now_hour=14,
    )

    lenses = updated["insight_lenses"]
    assert "counterfactual" in lenses
    assert lenses["false_self_detector"]["label"] == "systems-self"
    assert lenses["threshold_detection"]["level"] in {"medium", "high"}
    assert lenses["pattern_market"]
    assert lenses["silent_interventions"]
    assert lenses["surface_policy"]["mode"] in {"narrow_focus", "full_context"}
    assert "compact_status" in lenses["surface_policy"]


def test_adaptive_companion_anti_narrative_strategy_overrides_when_active():
    state = tools._adaptive_companion_default_state()
    state["insight_lenses"] = {"anti_narrative_mode": {"active": True}}

    strategy = tools._adaptive_companion_select_response_strategy(
        trigger={"kind": "meta_deflection", "task_label": "Finish Calgary landing page"},
        inferred_state="meta_deflecting",
        state=state,
        now_hour=14,
    )

    assert strategy["length"] == "one_line"
    assert strategy["language"] == "plain"


def test_runtime_live_watch_status_formats_human_summary():
    status = tools._runtime_live_watch_status_message(
        {
            "ran_at": "2026-05-18T12:15:00+00:00",
            "filter": "today | overdue",
            "focus_guard": {
                "status": "needs_focus",
                "task_count": 3,
                "most_important_task": {"content": "Plan simple outing"},
            },
            "adaptive_companion": {
                "success": True,
                "sent": False,
                "reason": "cooldown",
                "state": {
                    "insight_lenses": {
                        "threshold_detection": {"level": "medium", "signal": "Avoidance is clustering."},
                        "recovery_intelligence": {"mode": "interrupt", "suggestion": "Change state, not theory."},
                        "respect_engine": {"note": "Last earned respect came from finishing Plan simple outing after resistance."},
                        "silent_interventions": ["Pin Plan simple outing as the only task worth seeing for the next cycle."],
                    }
                },
            },
        }
    )

    assert "Hermes Live Watch" in status
    assert "Plan simple outing" in status
    assert "cooldown" in status
    assert "Threshold:" in status
    assert "Silent move:" in status
    assert "Surface:" in status


def test_runtime_live_watch_status_compacts_when_surface_policy_demands_it():
    status = tools._runtime_live_watch_status_message(
        {
            "ran_at": "2026-05-18T12:15:00+00:00",
            "filter": "today | overdue",
            "focus_guard": {
                "status": "needs_focus",
                "task_count": 3,
                "most_important_task": {"content": "Plan simple outing"},
            },
            "surface_policy": {"mode": "narrow_focus", "compact_status": True},
            "adaptive_companion": {
                "success": True,
                "sent": False,
                "reason": "cooldown",
                "state": {
                    "insight_lenses": {
                        "threshold_detection": {"level": "high", "signal": "This is the edge."},
                        "recovery_intelligence": {"mode": "pressure", "suggestion": "Movement first."},
                        "respect_engine": {"note": "Should stay hidden in compact mode."},
                        "silent_interventions": ["Pin Plan simple outing as the only task worth seeing for the next cycle."],
                    }
                },
            },
        }
    )

    assert "Top task: Plan simple outing" in status
    assert "Filter:" not in status
    assert "Focus status:" not in status
    assert "Respect:" not in status
    assert "Surface: narrow_focus" in status


def test_runtime_live_watch_updates_status_message(monkeypatch):
    sent_payloads = []

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, json=None, headers=None, params=None):
            del headers, params
            sent_payloads.append((url, json))
            if url.endswith("/sendMessage"):
                return _FakeResponse({"ok": True, "result": {"message_id": 111}})
            return _FakeResponse({"ok": True, "result": True})

    monkeypatch.setattr(tools, "_http_client", lambda: FakeClient())
    monkeypatch.setattr(tools, "_focus_guard_telegram_config", lambda: ("token", "chat"))
    payload = {
        "ran_at": "2026-05-18T12:15:00+00:00",
        "filter": "today | overdue",
        "focus_guard": {
            "status": "needs_focus",
            "task_count": 1,
            "most_important_task": {"content": "Plan simple outing"},
        },
        "adaptive_companion": {"success": True, "sent": False, "reason": "cooldown"},
    }

    result = tools._runtime_live_watch_update_status_message(payload)

    assert result["message_id"] == 111
    assert any("/sendMessage" in url for url, _ in sent_payloads)


def test_runtime_live_watch_edits_existing_status_message(monkeypatch):
    sent_payloads = []
    seeded = {
        "status_message": {"chat_id": "chat", "message_id": 222},
    }
    tools._write_json(tools.LIVE_WATCH_STATE_PATH, seeded)

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, json=None, headers=None, params=None):
            del headers, params
            sent_payloads.append((url, json))
            return _FakeResponse({"ok": True, "result": {"message_id": 222}})

    monkeypatch.setattr(tools, "_http_client", lambda: FakeClient())
    monkeypatch.setattr(tools, "_focus_guard_telegram_config", lambda: ("token", "chat"))
    payload = {
        "ran_at": "2026-05-18T12:15:00+00:00",
        "filter": "today | overdue",
        "focus_guard": {
            "status": "needs_focus",
            "task_count": 1,
            "most_important_task": {"content": "Plan simple outing"},
        },
        "adaptive_companion": {"success": True, "sent": True, "reason": None},
    }

    result = tools._runtime_live_watch_update_status_message(payload)

    assert result["message_id"] == 222
    assert any("/editMessageText" in url for url, _ in sent_payloads)


def test_adaptive_companion_status_defaults():
    result = _decode(tools.handle_adaptive_companion({"action": "status"}))

    assert result["success"] is True
    assert result["action"] == "status"
    assert result["state"]["mode"] == "idle"
    assert result["state"]["last_pressure_style"] is None
    assert result["state"]["pattern_memory"] == {}


def test_adaptive_companion_default_state_includes_response_dimensions():
    state = tools._adaptive_companion_default_state()

    assert state["style_history"] == []
    assert state["response_history"] == []
    assert state["combination_effectiveness"] == {}
    assert state["intervention_family_history"] == []
    assert state["intervention_family_effectiveness"] == {}
    assert state["pattern_history"] == []


def test_adaptive_companion_detects_meta_deflection():
    trigger = tools._adaptive_companion_detect_trigger(
        user_text="yeah okay but you're just ai anyway",
        focus_state={"most_important_task": {"content": "Finish Calgary landing page"}, "status": "needs_focus"},
        state=tools._adaptive_companion_default_state(),
    )

    assert trigger["kind"] == "meta_deflection"
    assert trigger["task_label"] == "Finish Calgary landing page"


def test_adaptive_companion_selects_policy_safe_style_for_meta_deflection():
    style = tools._adaptive_companion_select_style(
        trigger={"kind": "meta_deflection"},
        state={"style_effectiveness": {}, "last_pressure_style": None},
        now_hour=13,
    )

    assert style == "evidence_check"


def test_adaptive_companion_rotates_away_from_recent_style():
    style = tools._adaptive_companion_select_style(
        trigger={"kind": "meta_deflection"},
        state={"style_history": ["evidence_check", "task_repair"]},
        now_hour=13,
    )

    assert style == "low_pressure_redirect"


def test_adaptive_companion_generates_meta_deflection_message():
    message = tools._adaptive_companion_build_message(
        trigger={"kind": "meta_deflection", "task_label": "Finish Calgary landing page"},
        style="ego_puncture",
        state=tools._adaptive_companion_default_state(),
    )

    assert "Finish Calgary landing page" in message
    assert "visible step" in message.lower()
    assert "dodge" not in message.lower()


def test_adaptive_companion_detects_suspicious_task_from_focus_state():
    trigger = tools._adaptive_companion_detect_trigger(
        user_text="",
        focus_state={
            "most_important_task": {"content": "Finish Calgary landing page"},
            "status": "needs_focus",
            "suspicious_tasks": [{"task": {"content": "Research the perfect productivity app"}}],
        },
        state=tools._adaptive_companion_default_state(),
    )

    assert trigger["kind"] == "suspicious_task"
    assert "Research the perfect productivity app" in trigger["evidence"]


def test_adaptive_companion_classifies_false_prep_pattern():
    pattern = tools._adaptive_companion_classify_pattern(
        trigger={
            "kind": "suspicious_task",
            "task_label": "Finish Calgary landing page",
            "evidence": "Set up a new dashboard before starting the draft",
        },
        inferred_state="avoiding",
        state=tools._adaptive_companion_default_state(),
    )

    assert pattern["label"] == "false_prep"
    assert "ready" in pattern["explanation"].lower() or "prep" in pattern["explanation"].lower()


def test_adaptive_companion_classifies_comfort_escape_pattern():
    pattern = tools._adaptive_companion_classify_pattern(
        trigger={
            "kind": "productive_procrastination",
            "task_label": "Finish Calgary landing page",
            "evidence": "Maybe do some easier admin tasks first so the day feels cleaner",
        },
        inferred_state="avoiding",
        state=tools._adaptive_companion_default_state(),
    )

    assert pattern["label"] == "comfort_escape"


def test_adaptive_companion_classifies_life_os_identity_work_as_smart_detour():
    pattern = tools._adaptive_companion_classify_pattern(
        trigger={
            "kind": "suspicious_task",
            "task_label": "Plan simple outing",
            "evidence": "Read Life OS identity statement",
        },
        inferred_state="avoiding",
        state=tools._adaptive_companion_default_state(),
    )

    assert pattern["label"] == "smart_detour"


def test_adaptive_companion_classifies_dashboard_cleanup_as_false_prep():
    pattern = tools._adaptive_companion_classify_pattern(
        trigger={
            "kind": "suspicious_task",
            "task_label": "Finish Calgary landing page",
            "evidence": "Clean up Life OS dashboard before writing",
        },
        inferred_state="avoiding",
        state=tools._adaptive_companion_default_state(),
    )

    assert pattern["label"] == "false_prep"


def test_adaptive_companion_selects_binary_frame_for_comfort_escape():
    family = tools._adaptive_companion_select_intervention_family(
        pattern={"label": "comfort_escape"},
        strategy={"pressure": "sharp", "language": "plain", "length": "short", "energy": "calm"},
        state=tools._adaptive_companion_default_state(),
    )

    assert family == "binary_frame"


def test_adaptive_companion_rotates_away_from_recent_intervention_family():
    state = tools._adaptive_companion_default_state()
    state["intervention_family_history"] = ["stairs_not_elevator", "comfort_callout"]

    family = tools._adaptive_companion_select_intervention_family(
        pattern={"label": "comfort_escape"},
        strategy={"pressure": "sharp", "language": "plain", "length": "short", "energy": "calm"},
        state=state,
    )

    assert family not in {"stairs_not_elevator", "comfort_callout"}


def test_adaptive_companion_selects_plain_one_line_for_basic_focus_drift():
    strategy = tools._adaptive_companion_select_response_strategy(
        trigger={"kind": "focus_drift", "task_label": "Finish Calgary landing page"},
        inferred_state="drifting",
        state=tools._adaptive_companion_default_state(),
        now_hour=10,
    )

    assert strategy["pressure"] in {"steady", "sharp"}
    assert strategy["language"] == "plain"
    assert strategy["length"] in {"one_line", "short"}


def test_adaptive_companion_selects_longer_response_for_repeated_meta_deflection():
    state = tools._adaptive_companion_default_state()
    state["pattern_memory"] = {"meta_deflection": {"count": 4}}

    strategy = tools._adaptive_companion_select_response_strategy(
        trigger={"kind": "meta_deflection", "task_label": "Finish Calgary landing page"},
        inferred_state="meta_deflecting",
        state=state,
        now_hour=14,
    )

    assert strategy["length"] in {"medium", "long"}


def test_adaptive_companion_high_threshold_raises_pressure():
    state = tools._adaptive_companion_default_state()
    state["insight_lenses"] = {"threshold_detection": {"level": "high"}}

    strategy = tools._adaptive_companion_select_response_strategy(
        trigger={"kind": "focus_drift", "task_label": "Finish Calgary landing page"},
        inferred_state="drifting",
        state=state,
        now_hour=10,
    )

    assert strategy["pressure"] == "steady"
    assert strategy["energy"] == "calm"


def test_adaptive_companion_stabilize_recovery_softens_strategy():
    state = tools._adaptive_companion_default_state()
    state["insight_lenses"] = {"recovery_intelligence": {"mode": "stabilize"}}

    strategy = tools._adaptive_companion_select_response_strategy(
        trigger={"kind": "focus_drift", "task_label": "Finish Calgary landing page"},
        inferred_state="drifting",
        state=state,
        now_hour=23,
    )

    assert strategy["pressure"] == "warm"
    assert strategy["language"] == "plain"


def test_adaptive_companion_builds_plain_one_line_message():
    message = tools._adaptive_companion_render_message(
        trigger={"kind": "focus_drift", "task_label": "Finish Calgary landing page"},
        strategy={"pressure": "steady", "language": "plain", "length": "one_line", "energy": "calm"},
        state=tools._adaptive_companion_default_state(),
    )

    assert "Finish Calgary landing page" in message
    assert "focus" in message.lower() or "start" in message.lower()


def test_adaptive_companion_plain_message_uses_threshold_warning():
    state = tools._adaptive_companion_default_state()
    state["insight_lenses"] = {"threshold_detection": {"level": "high"}}
    message = tools._adaptive_companion_render_message(
        trigger={"kind": "focus_drift", "task_label": "Finish Calgary landing page"},
        strategy={"pressure": "sharp", "language": "plain", "length": "one_line", "energy": "cold"},
        pattern={"label": "friction_avoidance"},
        state=state,
    )

    assert "Finish Calgary landing page" in message
    assert "tiny step" in message.lower() or "visible step" in message.lower()


def test_adaptive_companion_grounded_reset_uses_recovery_suggestion():
    state = tools._adaptive_companion_default_state()
    state["insight_lenses"] = {"recovery_intelligence": {"suggestion": "You need reduction, food, water, or sleep more than rhetoric right now."}}
    message = tools._adaptive_companion_render_message(
        trigger={"kind": "focus_drift", "task_label": "Finish Calgary landing page"},
        strategy={"pressure": "warm", "language": "plain", "length": "short", "energy": "calm"},
        pattern={"label": "overloaded_for_real"},
        family="grounded_reset",
        state=state,
    )

    assert "food" in message.lower()


def test_adaptive_companion_earned_respect_uses_respect_note():
    state = tools._adaptive_companion_default_state()
    state["insight_lenses"] = {"respect_engine": {"note": "Last earned respect came from finishing Plan simple outing after resistance."}}
    message = tools._adaptive_companion_render_message(
        trigger={"kind": "focus_drift", "task_label": "Plan simple outing"},
        strategy={"pressure": "warm", "language": "plain", "length": "short", "energy": "calm"},
        pattern={"label": "momentum_present"},
        family="earned_respect",
        state=state,
    )

    assert "earned respect" in message.lower()



def test_adaptive_companion_builds_longer_meta_message():
    message = tools._adaptive_companion_render_message(
        trigger={"kind": "meta_deflection", "task_label": "Finish Calgary landing page"},
        strategy={"pressure": "sharp", "language": "incisive", "length": "long", "energy": "cold"},
        state=tools._adaptive_companion_default_state(),
    )

    assert "Finish Calgary landing page" in message
    assert len(message.split()) > 20


def test_adaptive_companion_conversational_message_includes_wake_reason_anchor(monkeypatch):
    tools._write_json(
        tools.EVENT_ROUTER_STATE_PATH,
        {
            "recent_events": [],
            "last_event": {"event_type": "wake", "ts": "2026-05-18T18:05:00+00:00"},
        },
    )
    frozen_datetime = type(
        "FrozenDateTime",
        (),
        {
            "now": staticmethod(lambda tz=None: real_datetime.fromisoformat("2026-05-18T18:10:00+00:00")),
            "fromisoformat": staticmethod(real_datetime.fromisoformat),
        },
    )
    monkeypatch.setattr(tools, "datetime", frozen_datetime)
    message = tools._adaptive_companion_render_message(
        trigger={"kind": "focus_drift", "task_label": "Finish Calgary landing page"},
        strategy={"pressure": "warm", "language": "conversational", "length": "short", "energy": "calm"},
        pattern={"label": "friction_avoidance"},
        state=tools._adaptive_companion_default_state(),
    )

    assert message.startswith("Because I received a recent desktop start signal,")


def test_adaptive_companion_ignores_stale_reason_anchor(monkeypatch):
    tools._write_json(
        tools.EVENT_ROUTER_STATE_PATH,
        {
            "recent_events": [],
            "last_event": {"event_type": "desktop_unlocked", "ts": "2026-05-18T17:00:00+00:00"},
        },
    )
    frozen_datetime = type(
        "FrozenDateTime",
        (),
        {
            "now": staticmethod(lambda tz=None: real_datetime.fromisoformat("2026-05-18T18:10:00+00:00")),
            "fromisoformat": staticmethod(real_datetime.fromisoformat),
        },
    )
    monkeypatch.setattr(tools, "datetime", frozen_datetime)
    message = tools._adaptive_companion_render_message(
        trigger={"kind": "focus_drift", "task_label": "Finish Calgary landing page"},
        strategy={"pressure": "warm", "language": "conversational", "length": "short", "energy": "calm"},
        pattern={"label": "friction_avoidance"},
        state=tools._adaptive_companion_default_state(),
    )

    assert not message.startswith("Because you just unlocked your desktop,")
    assert "Finish Calgary landing page" in message


def test_adaptive_companion_detailed_message_names_tasks_and_examples():
    message = tools._adaptive_companion_render_message(
        trigger={
            "kind": "suspicious_task",
            "task_label": "Plan simple outing",
            "source": "Todoist",
            "side_task_label": "Read Life OS identity statement",
        },
        strategy={"pressure": "warm", "language": "explanatory", "length": "detailed", "energy": "calm"},
        pattern={"label": "smart_detour"},
        family="pattern_mirror",
        state=tools._adaptive_companion_default_state(),
    )

    assert 'Plan simple outing' in message
    assert 'Read Life OS identity statement' in message
    assert "choose one place or route" in message
    assert "pause" in message or "Hold off" in message or "pause until" in message


def test_adaptive_companion_strategy_uses_detailed_mode_for_relevant_side_task():
    strategy = tools._adaptive_companion_select_response_strategy(
        trigger={
            "kind": "suspicious_task",
            "task_label": "Plan simple outing",
            "side_task_label": "Read Life OS identity statement",
        },
        inferred_state="avoiding",
        state=tools._adaptive_companion_default_state(),
        now_hour=9,
    )

    assert strategy["language"] == "explanatory"
    assert strategy["length"] == "detailed"


def test_adaptive_companion_builds_policy_safe_legacy_stairs_message():
    message = tools._adaptive_companion_render_message(
        trigger={
            "kind": "productive_procrastination",
            "task_label": "Finish Calgary landing page",
            "evidence": "Maybe start with easier admin first",
        },
        strategy={"pressure": "sharp", "language": "plain", "length": "short", "energy": "calm"},
        pattern={"label": "comfort_escape"},
        family="stairs_not_elevator",
        state=tools._adaptive_companion_default_state(),
    )

    assert "tiny step" in message.lower() or "visible step" in message.lower()
    assert "stairs" not in message.lower()
    assert "elevator" not in message.lower()


def test_adaptive_companion_builds_binary_frame_message():
    message = tools._adaptive_companion_render_message(
        trigger={"kind": "focus_drift", "task_label": "Finish Calgary landing page"},
        strategy={"pressure": "sharp", "language": "plain", "length": "short", "energy": "cold"},
        pattern={"label": "friction_avoidance"},
        family="binary_frame",
        state=tools._adaptive_companion_default_state(),
    )

    assert "tiny step" in message.lower() or "visible step" in message.lower() or "first step" in message.lower()


def test_adaptive_companion_builds_hierarchy_enforcement_message():
    message = tools._adaptive_companion_render_message(
        trigger={"kind": "suspicious_task", "task_label": "Plan simple outing", "evidence": "Read Life OS identity statement"},
        strategy={"pressure": "warm", "language": "conversational", "length": "short", "energy": "calm"},
        pattern={"label": "smart_detour"},
        family="hierarchy_enforcement",
        state=tools._adaptive_companion_default_state(),
    )

    assert "priority" in message.lower() or "support tasks" in message.lower()


def test_adaptive_companion_builds_enemy_naming_message():
    message = tools._adaptive_companion_render_message(
        trigger={"kind": "meta_deflection", "task_label": "Finish Calgary landing page"},
        strategy={"pressure": "sharp", "language": "incisive", "length": "short", "energy": "cold"},
        pattern={"label": "meta_deflection"},
        family="enemy_naming",
        state=tools._adaptive_companion_default_state(),
    )

    assert "trap" in message.lower() or "risk" in message.lower()
    assert "physical action" in message.lower() or "real action" in message.lower()



def test_adaptive_companion_varies_stairs_message_by_recent_history():
    first = tools._adaptive_companion_render_message(
        trigger={
            "kind": "productive_procrastination",
            "task_label": "Finish Calgary landing page",
            "evidence": "Maybe start with easier admin first",
        },
        strategy={"pressure": "sharp", "language": "plain", "length": "short", "energy": "calm"},
        pattern={"label": "comfort_escape"},
        family="stairs_not_elevator",
        state=tools._adaptive_companion_default_state(),
    )
    state = tools._adaptive_companion_default_state()
    state["intervention_family_history"] = ["stairs_not_elevator"]
    second = tools._adaptive_companion_render_message(
        trigger={
            "kind": "productive_procrastination",
            "task_label": "Finish Calgary landing page",
            "evidence": "Maybe start with easier admin first",
        },
        strategy={"pressure": "sharp", "language": "plain", "length": "short", "energy": "calm"},
        pattern={"label": "comfort_escape"},
        family="stairs_not_elevator",
        state=state,
    )

    assert first != second


def test_adaptive_companion_varies_pattern_mirror_message_by_recent_history():
    first = tools._adaptive_companion_render_message(
        trigger={
            "kind": "suspicious_task",
            "task_label": "Plan simple outing",
            "evidence": "Read Life OS identity statement",
        },
        strategy={"pressure": "warm", "language": "conversational", "length": "short", "energy": "calm"},
        pattern={"label": "smart_detour"},
        family="pattern_mirror",
        state=tools._adaptive_companion_default_state(),
    )
    state = tools._adaptive_companion_default_state()
    state["intervention_family_history"] = ["pattern_mirror"]
    second = tools._adaptive_companion_render_message(
        trigger={
            "kind": "suspicious_task",
            "task_label": "Plan simple outing",
            "evidence": "Read Life OS identity statement",
        },
        strategy={"pressure": "warm", "language": "conversational", "length": "short", "energy": "calm"},
        pattern={"label": "smart_detour"},
        family="pattern_mirror",
        state=state,
    )

    assert first != second


def test_adaptive_companion_selects_new_tate_extracted_families():
    state = tools._adaptive_companion_default_state()

    smart_detour = tools._adaptive_companion_select_intervention_family(
        pattern={"label": "smart_detour"},
        strategy={"pressure": "warm"},
        state=state,
    )
    meta = tools._adaptive_companion_select_intervention_family(
        pattern={"label": "meta_deflection"},
        strategy={"pressure": "sharp"},
        state=state,
    )

    assert smart_detour in {"hierarchy_enforcement", "pattern_mirror", "short_punch", "comfort_callout"}
    assert meta in {"identity_challenge", "enemy_naming", "pattern_mirror", "short_punch"}


def test_adaptive_companion_tracks_response_combination_effectiveness():
    state = tools._adaptive_companion_default_state()

    updated = tools._adaptive_companion_update_response_learning(
        state=state,
        trigger_kind="focus_drift",
        strategy={"pressure": "steady", "language": "plain", "length": "one_line", "energy": "calm"},
        outcome="corrected",
    )

    key = "steady|plain|one_line|calm"
    assert updated["combination_effectiveness"][key]["corrected"] == 1
    assert updated["response_history"][-1]["strategy"]["length"] == "one_line"


def test_adaptive_companion_tracks_intervention_family_effectiveness():
    state = tools._adaptive_companion_default_state()

    updated = tools._adaptive_companion_update_family_learning(
        state=state,
        pattern_label="comfort_escape",
        family="stairs_not_elevator",
        outcome="corrected",
    )

    assert updated["intervention_family_effectiveness"]["stairs_not_elevator"]["corrected"] == 1
    assert updated["pattern_history"][-1]["pattern"] == "comfort_escape"
    assert updated["intervention_family_history"][-1] == "stairs_not_elevator"


def test_adaptive_companion_run_returns_strategy(monkeypatch):
    monkeypatch.setattr(
        tools,
        "_focus_guard_read_state",
        lambda path=tools.FOCUS_GUARD_STATE_PATH: {
            "status": "needs_focus",
            "most_important_task": {"content": "Finish Calgary landing page"},
            "suspicious_tasks": [],
        },
    )
    monkeypatch.setattr(tools, "_adaptive_companion_recent_user_text", lambda: "")
    monkeypatch.setattr(tools, "_adaptive_companion_now_local_hour", lambda: 10)
    monkeypatch.setattr(tools, "_focus_guard_send_telegram_message", lambda text, chat_id=None: {"ok": True})

    result = _decode(tools.handle_adaptive_companion({"action": "run"}))

    assert result["success"] is True
    assert result["strategy"]["language"] == "plain"
    assert result["strategy"]["length"] in {"one_line", "short"}
    assert result["intervention_family"] in {"short_punch", "pattern_mirror", "stairs_not_elevator", "comfort_callout"}


def test_adaptive_companion_run_sends_message_on_focus_drift(monkeypatch):
    sent = []
    monkeypatch.setattr(
        tools,
        "_focus_guard_read_state",
        lambda path=tools.FOCUS_GUARD_STATE_PATH: {
            "status": "needs_focus",
            "most_important_task": {"content": "Finish Calgary landing page"},
            "suspicious_tasks": [],
        },
    )
    monkeypatch.setattr(tools, "_adaptive_companion_recent_user_text", lambda: "")
    monkeypatch.setattr(tools, "_adaptive_companion_now_local_hour", lambda: 14)
    monkeypatch.setattr(
        tools,
        "_focus_guard_send_telegram_message",
        lambda text, chat_id=None: sent.append(text) or {"ok": True},
    )

    result = _decode(tools.handle_adaptive_companion({"action": "run"}))

    assert result["success"] is True
    assert result["sent"] is True
    assert result["style"] in {"pattern_mirror", "calm_command"}
    assert result["pattern"]["label"] == "friction_avoidance"
    assert result["intervention_family"] in {"short_punch", "pattern_mirror"}
    assert sent


def test_adaptive_companion_updates_style_effectiveness():
    state = tools._adaptive_companion_default_state()

    updated = tools._adaptive_companion_update_learning(
        state=state,
        trigger_kind="focus_drift",
        style="pattern_mirror",
        outcome="corrected",
    )

    assert updated["style_effectiveness"]["pattern_mirror"]["corrected"] == 1
    assert updated["pattern_memory"]["focus_drift"]["last_success_style"] == "pattern_mirror"
    assert updated["style_history"][-1] == "pattern_mirror"


def test_adaptive_companion_run_skips_after_10pm_for_proactive_push(monkeypatch):
    monkeypatch.setattr(
        tools,
        "_focus_guard_read_state",
        lambda path=tools.FOCUS_GUARD_STATE_PATH: {
            "status": "needs_focus",
            "most_important_task": {"content": "Finish Calgary landing page"},
            "suspicious_tasks": [],
        },
    )
    monkeypatch.setattr(tools, "_adaptive_companion_recent_user_text", lambda: "")
    monkeypatch.setattr(tools, "_adaptive_companion_now_local_hour", lambda: 22)

    result = _decode(tools.handle_adaptive_companion({"action": "run"}))

    assert result["sent"] is False
    assert result["reason"] == "outside_hours"


def test_adaptive_companion_run_does_not_override_quiet_hours(monkeypatch):
    sent = []
    monkeypatch.setattr(
        tools,
        "_focus_guard_read_state",
        lambda path=tools.FOCUS_GUARD_STATE_PATH: {
            "status": "needs_focus",
            "most_important_task": {"content": "Finish Calgary landing page"},
            "suspicious_tasks": [],
        },
    )
    monkeypatch.setattr(tools, "_adaptive_companion_recent_user_text", lambda: "")
    monkeypatch.setattr(tools, "_adaptive_companion_now_local_hour", lambda: 22)
    monkeypatch.setattr(
        tools,
        "_focus_guard_send_telegram_message",
        lambda text, chat_id=None: sent.append(text) or {"ok": True},
    )

    result = _decode(tools.handle_adaptive_companion({"action": "run", "always_on": True}))

    assert result["success"] is True
    assert result["sent"] is False
    assert result["reason"] == "outside_hours"
    assert sent == []


def test_adaptive_companion_run_suppresses_repeat_nudge_within_cooldown(monkeypatch):
    sent = []
    seeded = tools._adaptive_companion_default_state()
    seeded["recent_interventions"] = [
        {
            "trigger": "focus_drift",
            "style": "pattern_mirror",
            "pattern": {"label": "friction_avoidance"},
            "intervention_family": "pattern_mirror",
            "task_label": "Plan simple outing",
                "message": "Stop circling it and start.",
                "sent_at": "2026-05-18T18:00:00+00:00",
            }
        ]
    tools._adaptive_companion_write_state(seeded)
    monkeypatch.setattr(
        tools,
        "_focus_guard_read_state",
        lambda path=tools.FOCUS_GUARD_STATE_PATH: {
            "status": "needs_focus",
            "most_important_task": {"content": "Plan simple outing"},
            "suspicious_tasks": [],
        },
    )
    monkeypatch.setattr(tools, "_adaptive_companion_recent_user_text", lambda: "")
    monkeypatch.setattr(tools, "_adaptive_companion_now_local_hour", lambda: 13)
    monkeypatch.setattr(
        tools,
        "_focus_guard_send_telegram_message",
        lambda text, chat_id=None: sent.append(text) or {"ok": True},
    )
    monkeypatch.setattr(
        tools,
        "datetime",
        type(
            "FrozenDateTime",
            (),
            {
                "now": staticmethod(lambda tz=None: real_datetime.fromisoformat("2026-05-18T18:20:00+00:00")),
                "fromisoformat": staticmethod(real_datetime.fromisoformat),
            },
        ),
    )

    result = _decode(tools.handle_adaptive_companion({"action": "run"}))

    assert result["success"] is True
    assert result["sent"] is False
    assert result["reason"] == "cooldown"
    assert result["pattern"]["label"] == "friction_avoidance"
    assert sent == []


def test_adaptive_companion_run_allows_repeat_after_cooldown(monkeypatch):
    sent = []
    seeded = tools._adaptive_companion_default_state()
    seeded["recent_interventions"] = [
        {
            "trigger": "focus_drift",
            "style": "pattern_mirror",
            "pattern": {"label": "friction_avoidance"},
            "intervention_family": "pattern_mirror",
            "task_label": "Plan simple outing",
            "message": "Stop circling it and start.",
            "sent_at": "2026-05-18T11:00:00+00:00",  # 440 minutes before 18:20 (more than 360 min same-task cooldown)
        }
    ]
    tools._adaptive_companion_write_state(seeded)
    monkeypatch.setattr(
        tools,
        "_focus_guard_read_state",
        lambda path=tools.FOCUS_GUARD_STATE_PATH: {
            "status": "needs_focus",
            "most_important_task": {"content": "Plan simple outing"},
            "suspicious_tasks": [],
        },
    )
    monkeypatch.setattr(tools, "_adaptive_companion_recent_user_text", lambda: "")
    monkeypatch.setattr(tools, "_adaptive_companion_now_local_hour", lambda: 13)
    monkeypatch.setattr(
        tools,
        "_focus_guard_send_telegram_message",
        lambda text, chat_id=None: sent.append(text) or {"ok": True},
    )
    monkeypatch.setattr(
        tools,
        "datetime",
        type(
            "FrozenDateTime",
            (),
            {
                "now": staticmethod(lambda tz=None: real_datetime.fromisoformat("2026-05-18T18:20:00+00:00")),
                "fromisoformat": staticmethod(real_datetime.fromisoformat),
            },
        ),
    )

    result = _decode(tools.handle_adaptive_companion({"action": "run"}))

    assert result["success"] is True
    assert result["sent"] is True
    assert result["pattern"]["label"] == "friction_avoidance"
    assert len(result["state"]["recent_interventions"]) == 2
    assert sent


def test_adaptive_companion_general_vs_same_task_cooldown(monkeypatch):
    sent = []

    # 1. Different task label, 100 minutes elapsed (more than 90 min general cooldown) -> Allowed!
    seeded = tools._adaptive_companion_default_state()
    seeded["recent_interventions"] = [
        {
            "trigger": "focus_drift",
            "style": "pattern_mirror",
            "pattern": {"label": "friction_avoidance"},
            "intervention_family": "pattern_mirror",
            "task_label": "Old Task",
            "message": "Stop circling it and start.",
            "sent_at": "2026-05-18T16:40:00+00:00",  # 100 mins before 18:20 (general cooldown is 90 mins)
        }
    ]
    tools._adaptive_companion_write_state(seeded)

    monkeypatch.setattr(
        tools,
        "_focus_guard_read_state",
        lambda path=tools.FOCUS_GUARD_STATE_PATH: {
            "status": "needs_focus",
            "most_important_task": {"content": "Plan simple outing"},  # Different task label
            "suspicious_tasks": [],
        },
    )
    monkeypatch.setattr(tools, "_adaptive_companion_recent_user_text", lambda: "")
    monkeypatch.setattr(tools, "_adaptive_companion_now_local_hour", lambda: 13)
    monkeypatch.setattr(
        tools,
        "_focus_guard_send_telegram_message",
        lambda text, chat_id=None: sent.append(text) or {"ok": True},
    )
    monkeypatch.setattr(
        tools,
        "datetime",
        type(
            "FrozenDateTime",
            (),
            {
                "now": staticmethod(lambda tz=None: real_datetime.fromisoformat("2026-05-18T18:20:00+00:00")),
                "fromisoformat": staticmethod(real_datetime.fromisoformat),
            },
        ),
    )

    result = _decode(tools.handle_adaptive_companion({"action": "run"}))
    assert result["success"] is True
    assert result["sent"] is True
    assert len(result["state"]["recent_interventions"]) == 2
    assert sent


def test_adaptive_companion_run_stops_after_daily_pressure_limit(monkeypatch):
    sent = []
    seeded = tools._adaptive_companion_default_state()
    seeded["recent_interventions"] = [
        {
            "trigger": "focus_drift",
            "style": "pattern_mirror",
            "pattern": {"label": "friction_avoidance"},
            "intervention_family": "pattern_mirror",
            "task_label": "Plan simple outing",
            "message": "Stop circling it and start.",
            "sent_at": "2026-05-18T10:00:00+00:00",  # older than 360 mins same-task cooldown
        },
        {
            "trigger": "focus_drift",
            "style": "pattern_mirror",
            "pattern": {"label": "friction_avoidance"},
            "intervention_family": "binary_frame",
            "task_label": "Plan simple outing",
            "message": "This is simple: action or excuse. Plan simple outing.",
            "sent_at": "2026-05-18T12:00:00+00:00",  # older than 360 mins same-task cooldown
        },
    ]
    tools._adaptive_companion_write_state(seeded)
    monkeypatch.setattr(
        tools,
        "_focus_guard_read_state",
        lambda path=tools.FOCUS_GUARD_STATE_PATH: {
            "status": "needs_focus",
            "most_important_task": {"content": "Plan simple outing"},
            "suspicious_tasks": [],
        },
    )
    monkeypatch.setattr(tools, "_adaptive_companion_recent_user_text", lambda: "")
    monkeypatch.setattr(tools, "_adaptive_companion_now_local_hour", lambda: 13)
    monkeypatch.setattr(
        tools,
        "_focus_guard_send_telegram_message",
        lambda text, chat_id=None: sent.append(text) or {"ok": True},
    )
    monkeypatch.setattr(
        tools,
        "datetime",
        type(
            "FrozenDateTime",
            (),
            {
                "now": staticmethod(lambda tz=None: real_datetime.fromisoformat("2026-05-18T18:20:00+00:00")),
                "fromisoformat": staticmethod(real_datetime.fromisoformat),
            },
        ),
    )

    result = _decode(tools.handle_adaptive_companion({"action": "run"}))

    assert result["success"] is True
    assert result["sent"] is False
    assert result["reason"] == "pressure_limit"
    assert result["scope"] == "same_task_and_pattern"
    assert sent == []


def test_adaptive_companion_explain_returns_recent_intervention():
    seeded = tools._adaptive_companion_default_state()
    seeded["recent_interventions"] = [{
        "trigger": "focus_drift",
        "style": "pattern_mirror",
        "pattern": {"label": "friction_avoidance"},
        "intervention_family": "pattern_mirror",
        "message": "Stop circling it and start.",
    }]
    seeded["style_history"] = ["pattern_mirror"]
    tools._adaptive_companion_write_state(seeded)

    result = _decode(tools.handle_adaptive_companion({"action": "explain"}))

    assert result["success"] is True
    assert result["action"] == "explain"
    assert result["latest_intervention"]["style"] == "pattern_mirror"
    assert result["latest_intervention"]["pattern"]["label"] == "friction_avoidance"
    assert result["style_history"] == ["pattern_mirror"]


def test_twilio_status_prefers_personal_env_names(monkeypatch):
    monkeypatch.setattr(tools, "_env_first", lambda *names: {
        "PERSONAL_TWILIO_ACCOUNT_SID": "ACpersonal1234",
        "PERSONAL_TWILIO_AUTH_TOKEN": "token-personal",
        "PERSONAL_TWILIO_PHONE_NUMBER": "+15551234567",
    }.get(names[0], ""))

    result = _decode(tools.handle_twilio({"action": "status"}))

    assert result["success"] is True
    assert result["configured"] is True
    assert result["from_number"] == "+15551234567"
    assert result["account_sid_masked"].startswith("ACpe")


def test_focus_guard_dynamic_semantic_matching():
    # Avoidance group matching (e.g. Clean workspace, new framework setup)
    task1 = {"content": "Clean workspace and prepare desktop", "description": ""}
    res1 = tools._focus_guard_classify_task(task1)
    assert res1 is not None
    assert res1["label"] == "avoidance"
    assert "procrastination rituals" in res1["reason"]

    # Suspicious group matching (e.g. Preparatory program guidelines)
    task2 = {"content": "prep program guidelines", "description": ""}
    res2 = tools._focus_guard_classify_task(task2)
    assert res2 is not None
    assert res2["label"] == "suspicious"
    assert "preparation" in res2["reason"]

    # Custom rule override from todoist_rules.json
    rules_state = tools._todoist_rules_read_state()
    rules_state["rules"].append({
        "rule_id": "rule_custom_test",
        "pattern": "special learning task",
        "label": "avoidance",
        "reason": "Reading documentation instead of doing actual hard work."
    })
    tools._todoist_rules_write_state(rules_state)

    task3 = {"content": "special learning task for python", "description": ""}
    res3 = tools._focus_guard_classify_task(task3)
    assert res3 is not None
    assert res3["label"] == "avoidance"
    assert "rule_custom_test" in res3["reason"]

    # Clean up todoist_rules.json
    rules_state["rules"] = [r for r in rules_state["rules"] if r.get("rule_id") != "rule_custom_test"]
    tools._todoist_rules_write_state(rules_state)


def test_adaptive_companion_reinforcement_learning_selection(monkeypatch):
    # Mock random.random() to return 0.5 (enforces exploitation as 0.5 > epsilon of 0.20)
    monkeypatch.setattr(tools.random, "random", lambda: 0.5)

    # Trigger kind: meta_deflection
    # Candidates: evidence_check, task_repair, low_pressure_redirect
    state = tools._adaptive_companion_default_state()
    state["style_effectiveness"] = {
        "task_repair": {"completed_after_nudge": 10},
        "evidence_check": {"completed_after_nudge": 2},
    }

    # Style history is empty, so candidates include all three
    selected_style = tools._adaptive_companion_select_style(
        trigger={"kind": "meta_deflection"},
        state=state,
        now_hour=10
    )
    # Exploit should pick the one with highest count: task_repair
    assert selected_style == "task_repair"

    # Family selection trigger: meta_deflection label
    # Candidates: enemy_naming, pattern_mirror, binary_frame
    state["intervention_family_effectiveness"] = {
        "pattern_mirror": {"completed_after_nudge": 8},
        "enemy_naming": {"completed_after_nudge": 1},
    }

    selected_family = tools._adaptive_companion_select_intervention_family(
        pattern={"label": "meta_deflection"},
        strategy={},
        state=state
    )
    assert selected_family == "pattern_mirror"


# --- NEW APPLE WATCH / IPHONE INTEGRATION TESTS ---

@pytest.fixture(autouse=True)
def _mock_telegram(monkeypatch):
    import sys
    import types
    class FakeInlineKeyboardButton:
        def __init__(self, text, callback_data=None, url=None):
            self.text = text
            self.callback_data = callback_data
            self.url = url

    class FakeInlineKeyboardMarkup:
        def __init__(self, inline_keyboard):
            self.inline_keyboard = inline_keyboard

    fake_telegram = types.SimpleNamespace(
        InlineKeyboardButton=FakeInlineKeyboardButton,
        InlineKeyboardMarkup=FakeInlineKeyboardMarkup,
        Update=object
    )
    monkeypatch.setitem(sys.modules, "telegram", fake_telegram)
    return fake_telegram


def test_escape_html_special_chars():
    assert tools._escape_html("<b>Hello & World</b>") == "&lt;b&gt;Hello &amp; World&lt;/b&gt;"
    assert tools._escape_html("plain text") == "plain text"
    assert tools._escape_html("") == ""


def test_telegram_inline_keyboard_dual_mode_buttons():
    # String buttons get feedback callback_data
    result = tools._telegram_inline_keyboard(["Option A", "Option B"])
    assert result is not None
    assert "inline_keyboard" in result
    rows = result["inline_keyboard"]
    assert len(rows) == 1  # two buttons fit in one row
    assert rows[0][0]["text"] == "Option A"
    assert "callback_data" in rows[0][0]

    # Dict buttons with url
    result = tools._telegram_inline_keyboard([
        {"text": "Open", "url": "https://example.com"},
        {"text": "Done", "callback_data": "po:task_complete:123"}
    ])
    rows = result["inline_keyboard"]
    assert rows[0][0]["url"] == "https://example.com"
    assert rows[0][1]["callback_data"] == "po:task_complete:123"


def test_telegram_inline_keyboard_nested_rows():
    buttons = [
        [{"text": "✅ 1", "callback_data": "po:task_complete:1"}, {"text": "📅 1", "callback_data": "po:task_defer:1"}],
        [{"text": "✅ 2", "callback_data": "po:task_complete:2"}, {"text": "📅 2", "callback_data": "po:task_defer:2"}],
    ]
    result = tools._telegram_inline_keyboard(buttons)
    assert len(result["inline_keyboard"]) == 2
    assert result["inline_keyboard"][0][0]["callback_data"] == "po:task_complete:1"
    assert result["inline_keyboard"][1][1]["callback_data"] == "po:task_defer:2"


def test_telegram_inline_keyboard_empty_and_none():
    assert tools._telegram_inline_keyboard(None) is None
    assert tools._telegram_inline_keyboard([]) is None


def test_get_top_high_priority_tasks_sorting():
    tasks = [
        {"id": "1", "content": "Low", "priority": 1},
        {"id": "2", "content": "High", "priority": 4},
        {"id": "3", "content": "Mid", "priority": 2},
        {"id": "4", "content": "Done", "priority": 4, "completed": True},
        {"id": "5", "content": "Urgent", "priority": 3},
    ]
    result = tools._get_top_high_priority_tasks(tasks, limit=3)
    assert len(result) == 3
    assert result[0]["id"] == "2"  # priority 4
    assert result[1]["id"] == "5"  # priority 3
    assert result[2]["id"] == "3"  # priority 2


def test_get_top_high_priority_tasks_empty():
    assert tools._get_top_high_priority_tasks([], limit=3) == []


def test_get_top_high_priority_tasks_filters_no_id():
    tasks = [{"content": "No ID", "priority": 4}]
    assert tools._get_top_high_priority_tasks(tasks, limit=3) == []


def test_build_hermes_dock_desk_context(monkeypatch):
    from datetime import datetime, timezone
    monkeypatch.setattr(tools, "_get_projects_map", lambda: {"proj_1": "Work", "proj_2": "Personal"})
    now = datetime(2026, 5, 20, 10, 0, 0, tzinfo=timezone.utc)  # 10 AM
    buttons = tools._build_hermes_dock("desk", local_now=now)
    texts = [b["text"] for b in buttons]
    assert any("Work" in t for t in texts)
    assert any("Inbox" in t for t in texts)
    # Should have both url and callback_data buttons
    urls = [b for b in buttons if "url" in b]
    callbacks = [b for b in buttons if "callback_data" in b]
    assert len(urls) >= 1
    assert len(callbacks) >= 1


def test_build_hermes_dock_away_context(monkeypatch):
    from datetime import datetime, timezone
    monkeypatch.setattr(tools, "_get_projects_map", lambda: {})
    now = datetime(2026, 5, 20, 10, 0, 0, tzinfo=timezone.utc)
    buttons = tools._build_hermes_dock("away", local_now=now)
    texts = [b["text"] for b in buttons]
    assert any("Errands" in t for t in texts)
    assert any("Today" in t for t in texts)


def test_build_hermes_dock_home_evening_context(monkeypatch):
    from datetime import datetime, timezone
    monkeypatch.setattr(tools, "_get_projects_map", lambda: {"proj_2": "Personal"})
    now = datetime(2026, 5, 20, 21, 0, 0, tzinfo=timezone.utc)  # 9 PM
    buttons = tools._build_hermes_dock("home", local_now=now)
    texts = [b["text"] for b in buttons]
    assert any("Personal" in t for t in texts)
    assert any("Inbox" in t for t in texts)


def test_daily_themes_map_completeness():
    assert len(tools._DAILY_THEMES) == 7
    for day in range(7):
        assert day in tools._DAILY_THEMES
        assert isinstance(tools._DAILY_THEMES[day], str)
        assert len(tools._DAILY_THEMES[day]) > 0


def test_parse_todoist_datetime_valid():
    from datetime import datetime, timezone
    dt = tools._parse_todoist_datetime("2026-05-20T10:00:00Z")
    assert dt.year == 2026
    assert dt.month == 5
    assert dt.day == 20


def test_parse_todoist_datetime_empty():
    from datetime import datetime, timezone
    dt = tools._parse_todoist_datetime("")
    assert dt == datetime.min.replace(tzinfo=timezone.utc)


def test_parse_todoist_datetime_invalid():
    from datetime import datetime, timezone
    dt = tools._parse_todoist_datetime("not-a-date")
    assert dt == datetime.min.replace(tzinfo=timezone.utc)


def test_run_system_cleanliness_audit_inbox_nudge(monkeypatch):
    from datetime import datetime, timezone, timedelta
    now = datetime(2026, 5, 20, 12, 0, 0, tzinfo=timezone.utc)
    old_date = (now - timedelta(days=3)).isoformat()

    tasks = [
        {"id": "t1", "content": "Old inbox task", "project_id": "inbox_id", "created_at": old_date},
    ]

    monkeypatch.setattr(tools, "_focus_guard_read_todoist_tasks", lambda **kw: tasks)
    monkeypatch.setattr(tools, "_get_projects_map", lambda: {"inbox_id": "Inbox"})
    monkeypatch.setattr(tools, "_operator_read_state", lambda: {})
    monkeypatch.setattr(tools, "_operator_write_state", lambda s: None)
    sent_messages = []
    monkeypatch.setattr(tools, "_safe_send_telegram_message", lambda text, **kw: sent_messages.append(text) or {})
    monkeypatch.setattr(tools, "_runtime_local_tz", lambda: timezone.utc)

    logs = tools._run_system_cleanliness_audit(now=now)
    assert any("Inbox Zero" in l for l in logs)
    assert len(sent_messages) >= 1
    assert "Inbox" in sent_messages[0]


def test_run_system_cleanliness_audit_rate_limited(monkeypatch):
    from datetime import datetime, timezone, timedelta
    now = datetime(2026, 5, 20, 12, 0, 0, tzinfo=timezone.utc)
    recent = (now - timedelta(hours=2)).isoformat()

    monkeypatch.setattr(tools, "_operator_read_state", lambda: {
        "last_inbox_zero_nudge_at": recent,
        "last_stale_project_audit_at": recent,
    })
    monkeypatch.setattr(tools, "_runtime_local_tz", lambda: timezone.utc)

    logs = tools._run_system_cleanliness_audit(now=now)
    assert logs == []  # Both audits should be skipped


def test_build_mood_recommendation_low_energy():
    from datetime import datetime, timezone
    now = datetime(2026, 5, 20, 14, 0, 0, tzinfo=timezone.utc)
    mood = {"last_mood": {"label": "low_energy"}}
    result = tools._build_mood_recommendation(mood, now)
    assert "low_energy" in result
    assert "Mood Match" in result


def test_build_mood_recommendation_focused():
    from datetime import datetime, timezone
    now = datetime(2026, 5, 20, 9, 0, 0, tzinfo=timezone.utc)
    mood = {"last_mood": {"label": "focused"}}
    result = tools._build_mood_recommendation(mood, now)
    assert "deep_work" in result


def test_build_mood_recommendation_neutral():
    from datetime import datetime, timezone
    now = datetime(2026, 5, 20, 20, 0, 0, tzinfo=timezone.utc)
    mood = {"last_mood": {"label": "neutral"}}
    result = tools._build_mood_recommendation(mood, now)
    assert result == ""


def test_handle_location_slash_command_home(monkeypatch):
    monkeypatch.setattr(tools, "_handle_location_update", lambda args: None)
    monkeypatch.setattr(tools, "_run_auto_cleanup_routines", lambda: {"logs": []})
    result = tools.handle_location_slash_command("home")
    assert "home" in result.lower()
    assert "Location updated" in result


def test_handle_location_slash_command_empty(monkeypatch):
    result = tools.handle_location_slash_command("")
    assert "Usage" in result


def test_handle_telegram_callback_location_sync(monkeypatch):
    import asyncio
    monkeypatch.setattr(tools, "_handle_location_update", lambda args: None)
    monkeypatch.setattr(tools, "_run_auto_cleanup_routines", lambda: {"logs": ["cleaned up"]})

    class FakeMessage:
        text = "old text"
        async def reply_text(self, text, **kw):
            self._reply = text
            self._kw = kw

    class FakeQuery:
        message = FakeMessage()
        async def answer(self, **kw):
            pass

    query = FakeQuery()
    asyncio.run(tools._handle_telegram_callback(None, query, "po:location:home"))
    assert "Location updated" in query.message._reply
    assert "home" in query.message._reply


def test_handle_telegram_callback_task_complete_sync(monkeypatch):
    import asyncio
    class FakeResp:
        status_code = 204
        def raise_for_status(self): pass

    class FakeClient:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def post(self, url, **kw):
            assert "close" in url
            return FakeResp()

    monkeypatch.setattr(tools, "_http_client", lambda: FakeClient())

    answered = {}
    edited = {}
    class FakeMessage:
        text = "Task list"
        async def reply_text(self, text, **kw): pass

    class FakeQuery:
        message = FakeMessage()
        async def answer(self, text="", **kw):
            answered["text"] = text
        async def edit_message_text(self, text, **kw):
            edited["text"] = text

    query = FakeQuery()
    asyncio.run(tools._handle_telegram_callback(None, query, "po:task_complete:12345"))
    assert "completed" in answered.get("text", "").lower()
    assert "Completed" in edited.get("text", "")


def test_handle_telegram_callback_task_defer_sync(monkeypatch):
    import asyncio
    class FakeResp:
        status_code = 200
        def raise_for_status(self): pass

    class FakeClient:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def post(self, url, headers=None, json=None, **kw):
            assert json == {"due_string": "tomorrow morning"}
            return FakeResp()

    monkeypatch.setattr(tools, "_http_client", lambda: FakeClient())

    answered = {}
    edited = {}
    class FakeMessage:
        text = "Task list"

    class FakeQuery:
        message = FakeMessage()
        async def answer(self, text="", **kw):
            answered["text"] = text
        async def edit_message_text(self, text, **kw):
            edited["text"] = text

    query = FakeQuery()
    asyncio.run(tools._handle_telegram_callback(None, query, "po:task_defer:99999"))
    assert "deferred" in answered.get("text", "").lower()
    assert "Deferred" in edited.get("text", "")


def test_handle_telegram_callback_unknown_action_sync():
    import asyncio
    answered = []
    class FakeQuery:
        async def answer(self, **kw):
            answered.append(True)

    query = FakeQuery()
    asyncio.run(tools._handle_telegram_callback(None, query, "po:unknown_action:data"))
    assert len(answered) == 1


def test_handle_telegram_callback_short_data_sync():
    import asyncio
    answered = []
    class FakeQuery:
        async def answer(self, **kw):
            answered.append(True)

    query = FakeQuery()
    asyncio.run(tools._handle_telegram_callback(None, query, "po"))
    assert len(answered) == 1


def test_wake_briefing_uses_policy_renderer_instead_of_daily_theme(monkeypatch):
    from datetime import datetime, timezone
    monkeypatch.setattr(tools, "_runtime_local_tz", lambda: timezone.utc)
    monkeypatch.setattr(tools, "_runtime_operator_event_brief", lambda **kw: {
        "window": "morning", "operator": {}, "target": "Write tests",
        "risk": None, "friction": None, "next_action": "Start coding"
    })

    now = datetime(2026, 5, 18, 8, 0, 0, tzinfo=timezone.utc)  # Monday
    focus_state = {
        "most_important_task": {"id": "t1", "content": "Write tests"},
        "suspicious_tasks": [],
    }
    msg = tools._runtime_build_wake_briefing(focus_state=focus_state, now=now, source="manual")
    assert "Theme" not in msg
    assert "I received a manual command signal" in msg
    assert "Priority anchor" in msg
    assert "Write tests" in msg


def test_evening_wake_briefing_uses_common_sense_salvage_tone(monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    local_tz = ZoneInfo("America/Edmonton")
    monkeypatch.setattr(tools, "_runtime_local_tz", lambda: local_tz)
    monkeypatch.setattr(tools, "_runtime_operator_event_brief", lambda **kw: {
        "window": "evening",
        "operator": {
            "evidence": {"todoist_mcp": {"active_count": 8, "completed_recently": 8, "noise": {"status": "noisy"}}}
        },
        "target": "Laundry check",
        "risk": "stale_task_drift",
        "friction": "admin_cleanup",
        "next_action": "Use Laundry check as the cleanup anchor: finish it, split it, or reschedule it honestly.",
    })
    focus_state = {
        "most_important_task": {"id": "6gcV9vR9qPRMVgG5", "content": "Laundry check"},
        "suspicious_tasks": [
            {"task": {"id": "6gc3gRpc4WWHq44C", "content": "Read Life OS identity statement"}}
        ],
    }

    msg = tools._runtime_build_wake_briefing(
        focus_state=focus_state,
        now=datetime(2026, 5, 21, 21, 34, tzinfo=local_tz),
        source="windows-logon-trigger",
    )

    assert "I received a Windows logon signal" in msg
    assert "possible activity, not guaranteed availability" in msg
    assert "Since it's late" in msg
    assert "Deep Work Focus" not in msg
    assert "Today's Theme" not in msg
    assert "top priority right now" not in msg
    assert "Stay honest with yourself" not in msg
    assert "split it" not in msg
    assert "start, switch, fold" in msg
    assert "reference/setup" in msg


def test_unlock_briefing_uses_policy_renderer_without_old_autonomous_copy(monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    local_tz = ZoneInfo("America/Edmonton")
    monkeypatch.setattr(tools, "_runtime_local_tz", lambda: local_tz)
    monkeypatch.setattr(tools, "_runtime_operator_event_brief", lambda **kw: {
        "window": "evening",
        "operator": {},
        "target": "Laundry check",
        "risk": "stale_task_drift",
        "friction": "admin_cleanup",
        "next_action": "Start the task.",
    })
    focus_state = {
        "most_important_task": {"id": "l1", "content": "Laundry check"},
        "suspicious_tasks": [{"task": {"content": "Read final program rules"}}],
    }

    msg = tools._runtime_build_unlock_briefing(
        focus_state=focus_state,
        now=datetime(2026, 5, 21, 19, 15, tzinfo=local_tz),
        source="desktop_unlocked",
    )

    assert "Desktop activity detected" not in msg
    assert "workflow looks solid" not in msg
    assert "Try to avoid" not in msg
    assert "I received a desktop unlock signal" in msg
    assert "Priority anchor" in msg
    assert "Potential distractions" in msg


def test_auto_cleanup_includes_cleanliness_audit(monkeypatch):
    audit_called = []
    monkeypatch.setattr(tools, "_focus_guard_read_todoist_tasks", lambda **kw: [])
    monkeypatch.setattr(tools, "_auto_cleanup_stale_tasks", lambda t: [])
    monkeypatch.setattr(tools, "_auto_cleanup_location_away", lambda t: [])
    monkeypatch.setattr(tools, "_auto_cleanup_friday_purge", lambda t: [])
    monkeypatch.setattr(tools, "_auto_cleanup_quiet_hours", lambda t: [])
    monkeypatch.setattr(tools, "_run_system_cleanliness_audit", lambda **kw: (audit_called.append(True) or []))

    result = tools._run_auto_cleanup_routines()
    assert result["status"] == "success"
    assert len(audit_called) == 1


def test_event_ingest_updates_state_and_deduplicates(monkeypatch, tmp_path):
    # Setup temp paths
    monkeypatch.setattr(tools, "PRESENCE_STATE_PATH", tmp_path / "presence_state.json")
    monkeypatch.setattr(tools, "OPERATOR_STATE_PATH", tmp_path / "operator_state.json")
    monkeypatch.setattr(tools, "EVENT_ROUTER_STATE_PATH", tmp_path / "event_router_state.json")

    # Ingest desktop.active event
    res = _decode(tools.handle_runtime({
        "action": "event_ingest",
        "event_type": "desktop.active",
        "source": "desktop_sentinel",
        "payload": {"presence_state": "active_now"}
    }))

    assert res["success"] is True

    # Read states
    presence = tools._read_json(tmp_path / "presence_state.json", {})
    operator = tools._read_json(tmp_path / "operator_state.json", {})

    assert presence["state"] == "desk"
    assert presence["afk"] is False
    assert operator["last_sensor_heartbeats"]["desktop_sentinel"] > 0

    # Ingest again with dedupe key
    res_dedupe1 = _decode(tools.handle_runtime({
        "action": "event_ingest",
        "event_type": "desktop.active",
        "source": "desktop_sentinel",
        "dedupe_key": "unique_key_1"
    }))
    assert res_dedupe1["success"] is True
    assert res_dedupe1.get("duplicate") is not True

    res_dedupe2 = _decode(tools.handle_runtime({
        "action": "event_ingest",
        "event_type": "desktop.active",
        "source": "desktop_sentinel",
        "dedupe_key": "unique_key_1"
    }))
    assert res_dedupe2["success"] is True
    assert res_dedupe2.get("duplicate") is True


def test_handle_distraction_event_under_cooldown_and_mute(monkeypatch, tmp_path):
    monkeypatch.setattr(tools, "PRESENCE_STATE_PATH", tmp_path / "presence_state.json")
    monkeypatch.setattr(tools, "OPERATOR_STATE_PATH", tmp_path / "operator_state.json")
    monkeypatch.setattr(tools, "_telegram_messages_allowed_now", lambda *args, **kw: True)
    monkeypatch.setattr(tools, "_run_scheduler_checks", lambda *args, **kw: None)

    # Initialize operator state with work_window so nudge is allowed
    tools._write_json(tmp_path / "operator_state.json", {"day_phase": "work_window"})

    sent_msgs = []
    monkeypatch.setattr(tools, "_safe_send_telegram_message", lambda text, **kw: sent_msgs.append(text))

    # Trigger distraction event (15 mins)
    res = _decode(tools.handle_runtime({
        "action": "event_ingest",
        "event_type": "desktop.distraction_15m",
        "source": "desktop_sentinel",
        "payload": {"category": "distraction_video", "duration_sec": 900}
    }))
    assert res["success"] is True
    assert res["nudge_sent"] is True
    assert len(sent_msgs) == 1
    assert "Focus check" in sent_msgs[0]
    assert "desktop signal" in sent_msgs[0]

    # Trigger again immediately -> blocked by cooldown
    res_cooldown = _decode(tools.handle_runtime({
        "action": "event_ingest",
        "event_type": "desktop.distraction_15m",
        "source": "desktop_sentinel",
        "payload": {"category": "distraction_video", "duration_sec": 905}
    }))

    assert res_cooldown["success"] is True
    assert res_cooldown["nudge_sent"] is False
    assert res_cooldown["reason"] == "cooldown_active"


def test_telegram_callback_sprint_mute_defer(monkeypatch, tmp_path):
    monkeypatch.setattr(tools, "OPERATOR_STATE_PATH", tmp_path / "operator_state.json")

    replied = []
    answered = []

    class MockMessage:
        def __init__(self):
            self.text = "Hello"
        async def reply_text(self, text, **kw):
            replied.append(text)

    class MockQuery:
        def __init__(self):
            self.message = MockMessage()
        async def answer(self, text="", **kw):
            answered.append(text)

    query = MockQuery()

    # 1. Test sprint start
    import asyncio
    asyncio.run(tools._handle_telegram_callback(None, query, "po:sprint:start"))
    operator = tools._read_json(tmp_path / "operator_state.json", {})
    assert "active_sprint" in operator
    assert "started_at" in operator["active_sprint"]
    assert any("sprint started" in r.lower() for r in replied)

    # 2. Test mute nudges
    asyncio.run(tools._handle_telegram_callback(None, query, "po:nudge_mute:1h"))
    operator = tools._read_json(tmp_path / "operator_state.json", {})
    assert operator["nudge_fatigue"]["mute_until_ts"] > 0
    assert any("muted" in r.lower() for r in replied)


def test_run_scheduler_checks_evening_briefing(monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    monkeypatch.setattr(tools, "_runtime_local_tz", lambda: ZoneInfo("America/Edmonton"))

    sent = []
    monkeypatch.setattr(tools, "_safe_send_telegram_message", lambda text, **kw: sent.append(text))

    state = {"day_phase": "evening"}
    monkeypatch.setattr(tools, "_operator_read_state", lambda: state)
    monkeypatch.setattr(tools, "_operator_write_state", lambda s: state.update(s))

    tasks = [{"id": "t1", "content": "Pack bags for tomorrow", "due": {"date": "2026-05-23"}}]
    monkeypatch.setattr(tools, "_focus_guard_read_todoist_tasks", lambda **kw: tasks)

    # 1. Test out-of-bounds (e.g. 5:00 PM local)
    state = {"day_phase": "work_window"}
    dt_out = datetime(2026, 5, 22, 17, 0, 0, tzinfo=ZoneInfo("America/Edmonton"))
    tools._run_scheduler_checks(dt_out)
    assert len(sent) == 0
    assert state.get("last_evening_briefing_date") is None

    # 2. Test in-bounds (e.g. 9:46 PM local)
    state = {"day_phase": "evening"}
    dt_in = datetime(2026, 5, 22, 21, 46, 0, tzinfo=ZoneInfo("America/Edmonton"))
    tools._run_scheduler_checks(dt_in)
    assert len(sent) == 1
    assert "Tomorrow's Todoist Preview" in sent[0]
    assert "Pack bags for tomorrow" in sent[0]
    assert state.get("last_evening_briefing_date") == "2026-05-22"

    # 3. Test deduplication (same day again)
    sent.clear()
    tools._run_scheduler_checks(dt_in)
    assert len(sent) == 0


def test_evening_briefing_task_debt_triage(monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    monkeypatch.setattr(tools, "_runtime_local_tz", lambda: ZoneInfo("America/Edmonton"))

    sent = []
    monkeypatch.setattr(tools, "_safe_send_telegram_message", lambda text, **kw: sent.append(text))

    state = {"day_phase": "evening"}
    monkeypatch.setattr(tools, "_operator_read_state", lambda: state)
    monkeypatch.setattr(tools, "_operator_write_state", lambda s: state.update(s))

    # Seed 10 tasks due tomorrow (2026-05-23)
    tomorrow_tasks = [
        {"id": f"t_tom_{i}", "content": f"Tomorrow task {i}", "due": {"date": "2026-05-23"}}
        for i in range(10)
    ]
    # Seed 40 overdue tasks (due 2026-05-21 - 1 day overdue)
    overdue_tasks = [
        {"id": f"t_over_{i}", "content": f"Overdue task {i}", "due": {"date": "2026-05-21"}}
        for i in range(40)
    ]
    # Seed 5 stale overdue tasks (due 2026-05-10 - 12 days overdue, low priority < 4)
    stale_tasks = [
        {"id": f"t_stale_{i}", "content": f"Stale task {i}", "due": {"date": "2026-05-10"}, "priority": 2}
        for i in range(5)
    ]

    all_tasks = tomorrow_tasks + overdue_tasks + stale_tasks
    monkeypatch.setattr(tools, "_focus_guard_read_todoist_tasks", lambda **kw: all_tasks)

    # Trigger at 9:46 PM local on 2026-05-22 (meaning tomorrow is 2026-05-23, yesterday/overdue is 2026-05-21)
    dt_in = datetime(2026, 5, 22, 21, 46, 0, tzinfo=ZoneInfo("America/Edmonton"))
    tools._run_scheduler_checks(dt_in)

    assert len(sent) == 1
    msg = sent[0]

    # Assert Sleep-Safe Triage title is present
    assert "Sleep-Safe Triage" in msg
    # Assert decision load scoring is present
    assert "Tomorrow has 10 scheduled workload items, but only 0 require" in msg
    # Assert carryover backlog count in quarantine is present
    assert "backlog of 40 overdue or carryover items in quarantine" in msg
    # Assert stale task decay warning/count is present
    assert "5 overdue items look stale rather than urgent. I’ll keep them out of tomorrow’s workload" in msg
    # Assert focus actions are limited to 3
    assert "Tomorrow task 0" in msg
    assert "Tomorrow task 1" in msg
    assert "Tomorrow task 2" in msg
    assert "Tomorrow task 3" not in msg  # Limited to 3
    # Assert it never uses the "...and X more" string or other forbidden phrases
    assert "...and" not in msg
    assert "on your plate:" not in msg.lower()
    assert "you are behind" not in msg.lower()
    assert "still not done" not in msg.lower()
    assert "failed to complete" not in msg.lower()
    # Assert the clean exit and reassuring message exist
    assert any(c in msg for c in [
        "Nothing else needs sorting tonight.",
        "Tomorrow has a first move. You can leave the rest for morning.",
        "The list is captured. You do not need to keep it in your head."
    ])


def test_prediction_vs_reality_loop(monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    state = {
        "briefing_predictions": {
            "2026-05-21": {
                "predicted_top_tasks": ["t_pred_1", "t_pred_2"],
                "completed": False
            }
        },
        "shown_task_counts": {},
        "behavioral_analytics": {
            "completions_count": 0,
            "ignores_count": 0,
            "history": []
        }
    }

    active_tasks = [
        {"id": "t_pred_2", "content": "Ignored predicted task", "due": {"date": "2026-05-23"}}
    ]

    monkeypatch.setattr(tools, "_focus_guard_read_todoist_tasks", lambda **kw: active_tasks)
    monkeypatch.setattr(tools, "_runtime_local_tz", lambda: ZoneInfo("America/Edmonton"))
    monkeypatch.setattr(tools, "_get_recent_completions", lambda: [])

    tools._operator_evaluate_yesterday_predictions(state, active_tasks)

    pred_entry = state["briefing_predictions"]["2026-05-21"]
    assert pred_entry["completed"] is True
    assert "t_pred_1" in pred_entry["completed_tasks"]
    assert "t_pred_2" in pred_entry["ignored_tasks"]

    analytics = state["behavioral_analytics"]
    assert analytics["completions_count"] == 1
    assert analytics["ignores_count"] == 1
    assert len(analytics["history"]) == 1


def test_task_survivorship_stuck_detection(monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    monkeypatch.setattr(tools, "_runtime_local_tz", lambda: ZoneInfo("America/Edmonton"))

    sent = []
    sent_buttons = []
    def mock_send(text, buttons=None, **kw):
        sent.append(text)
        sent_buttons.append(buttons)

    monkeypatch.setattr(tools, "_safe_send_telegram_message", mock_send)

    state = {
        "day_phase": "evening",
        "shown_task_counts": {
            "stuck_t_1": 5,
            "normal_t_2": 2
        }
    }
    monkeypatch.setattr(tools, "_operator_read_state", lambda: state)
    monkeypatch.setattr(tools, "_operator_write_state", lambda s: state.update(s))

    tasks = [
        {"id": "stuck_t_1", "content": "Read program rules", "due": {"date": "2026-05-23"}},
        {"id": "normal_t_2", "content": "Normal scheduled task", "due": {"date": "2026-05-23"}}
    ]
    monkeypatch.setattr(tools, "_focus_guard_read_todoist_tasks", lambda **kw: tasks)
    monkeypatch.setattr(tools, "_get_recent_completions", lambda: [])

    dt_in = datetime(2026, 5, 22, 21, 46, 0, tzinfo=ZoneInfo("America/Edmonton"))
    tools._run_scheduler_checks(dt_in)

    assert len(sent) == 1
    msg = sent[0]

    assert "Stuck Tasks Needing Intervention" in msg
    assert "Read program rules" in msg

    buttons = sent_buttons[0]
    assert any(b.get("text") == "⚡ Shrink Stuck Task" for b in buttons)
    assert any(b.get("text") == "💤 Move to Someday" for b in buttons)


def test_notification_trust_gate(monkeypatch):
    presence = {"configured": True, "can_proactively_message": True}
    focus = {}
    intel = {
        "active_tasks": {"count": 5},
        "overdue_tasks": [{"id": f"t_{i}"} for i in range(20)]
    }

    task_low = {"id": "t1", "content": "very low priority chore", "priority": 1}
    recent_nudges = {"sent_nudges": []}

    trust_score = tools._operator_calculate_nudge_trust_score(task_low, presence, recent_nudges, "default", intel, 22)
    assert trust_score < 3.0

    gate_res = tools._operator_nudge_quality_gate(
        mode="default",
        top_task=task_low,
        presence=presence,
        focus_state=focus,
        recent_nudges=recent_nudges,
        recommended_next_action="start",
        intel=intel,
        now_hour=22
    )
    assert gate_res["passed"] is False
    assert "Suppressing message" in gate_res["reason"] or "Outside allowed Telegram hours." in gate_res["reason"]


def test_morning_repair_loop(monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    monkeypatch.setattr(tools, "_runtime_local_tz", lambda: ZoneInfo("America/Edmonton"))

    sent = []
    monkeypatch.setattr(tools, "_safe_send_telegram_message", lambda text, **kw: sent.append(text))

    state = {
        "day_phase": "evening",
        "last_briefing_had_debt": True,
        "shown_task_counts": {}
    }
    monkeypatch.setattr(tools, "_operator_read_state", lambda: state)
    monkeypatch.setattr(tools, "_operator_write_state", lambda s: state.update(s))

    tasks = [
        {"id": "t_over", "content": "Overdue clickup review", "due": {"date": "2026-05-20"}, "priority": 3}
    ]
    monkeypatch.setattr(tools, "_focus_guard_read_todoist_tasks", lambda **kw: tasks)

    dt_in = datetime(2026, 5, 23, 9, 0, 0, tzinfo=ZoneInfo("America/Edmonton"))
    tools._run_scheduler_checks(dt_in)

    assert len(sent) == 1
    assert "Morning Repair Loop" in sent[0]
    assert "Overdue clickup review" in sent[0]
    assert state.get("last_briefing_had_debt") is False


def test_work_window_transition_stays_quiet_without_task_debt(monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    monkeypatch.setattr(tools, "_runtime_local_tz", lambda: ZoneInfo("America/Edmonton"))

    sent = []
    monkeypatch.setattr(tools, "_safe_send_telegram_message", lambda text, **kw: sent.append(text))

    state = {
        "day_phase": "evening",
        "last_briefing_had_debt": False,
    }
    monkeypatch.setattr(tools, "_operator_read_state", lambda: state)
    monkeypatch.setattr(tools, "_operator_write_state", lambda s: state.update(s))

    dt_in = datetime(2026, 5, 23, 9, 0, 0, tzinfo=ZoneInfo("America/Edmonton"))
    tools._run_scheduler_checks(dt_in)

    assert sent == []
    assert state.get("day_phase") == "work_window"


def test_briefing_feedback_callbacks_stuck(monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock, MagicMock

    tasks = [
        {"id": "stuck_1", "content": "Fix the leaking roof", "labels": []}
    ]
    monkeypatch.setattr(tools, "_focus_guard_read_todoist_tasks", lambda **kw: tasks)

    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_client.post.return_value = mock_resp
    monkeypatch.setattr(tools, "_http_client", lambda: MagicMock(__enter__=lambda _: mock_client))

    query = MagicMock()
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    query.message.text = "Morning Repair"
    query.message.reply_text = AsyncMock()

    asyncio.run(tools._handle_telegram_callback(None, query, "po:stuck:shrink:stuck_1"))
    query.answer.assert_called()
    called_reply = query.message.reply_text.call_args[0][0]
    assert "Stuck Task Intervention" in called_reply
    assert "Fix the leaking roof" in called_reply

    asyncio.run(tools._handle_telegram_callback(None, query, "po:stuck:someday:stuck_1"))
    query.answer.assert_called_with(text="Task moved to Someday/Maybe!")
    assert mock_client.post.called


def test_evening_briefing_feedback_callbacks(monkeypatch):
    import asyncio
    from datetime import datetime, timedelta
    from unittest.mock import AsyncMock, MagicMock

    tz = tools._runtime_local_tz()
    today_date = datetime.now(tz).date()
    tomorrow_date = today_date + timedelta(days=1)

    # Mock _focus_guard_read_todoist_tasks
    tasks = [
        {"id": "t1", "content": "Clean the garage", "due": {"date": today_date.isoformat()}},
        {"id": "t2", "content": "Focus task", "due": {"date": tomorrow_date.isoformat()}, "priority": 3}
    ]
    monkeypatch.setattr(tools, "_focus_guard_read_todoist_tasks", lambda **kw: tasks)

    # Mock Telegram callback query objects
    query = MagicMock()
    query.answer = AsyncMock()
    query.edit_message_text = AsyncMock()
    query.message.text = "Tomorrow's Todoist Preview"
    query.message.reply_text = AsyncMock()

    # 1. Test po:briefing:quiet callback
    asyncio.run(tools._handle_telegram_callback(None, query, "po:briefing:quiet"))
    query.answer.assert_called_with(text="Quiet mode activated.")
    query.edit_message_text.assert_called_with(
        "<b>🌙 Quiet Mode Active</b>\n\nTask previews skipped for tonight. Rest well and protect your nervous system! 💤",
        parse_mode="HTML",
        reply_markup=None
    )

    # 2. Test po:briefing:top3 callback
    query.answer.reset_mock()
    query.edit_message_text.reset_mock()
    asyncio.run(tools._handle_telegram_callback(None, query, "po:briefing:top3"))
    query.answer.assert_called()
    called_text = query.edit_message_text.call_args[0][0]
    assert "Tomorrow's Top 3 Priorities:" in called_text
    assert "Focus task" in called_text

    # 3. Test po:briefing:triage callback
    query.answer.reset_mock()
    asyncio.run(tools._handle_telegram_callback(None, query, "po:briefing:triage"))
    query.answer.assert_called()
    called_reply_text = query.message.reply_text.call_args[0][0]
    assert "Overdue Triage" in called_reply_text
    assert "Clean the garage" in called_reply_text


def test_classify_task_role_priority_labels():
    # Explicit labels priority
    assert tools._classify_task_role({"labels": ["family_anchor"]}) == "family_anchor"
    assert tools._classify_task_role({"labels": ["fitness_anchor"]}) == "fitness_anchor"
    assert tools._classify_task_role({"labels": ["routine"]}) == "routine"
    assert tools._classify_task_role({"labels": ["reference"]}) == "reference"
    assert tools._classify_task_role({"labels": ["checklist_item"]}) == "checklist_item"
    assert tools._classify_task_role({"labels": ["task_debt"]}) == "task_debt"
    assert tools._classify_task_role({"labels": ["exclude_workload"]}) == "exclude_workload"
    assert tools._classify_task_role({"labels": ["hermes_hidden"]}) == "hermes_hidden"


def test_classify_task_role_fallbacks():
    # Fallback to fitness anchors
    assert tools._classify_task_role({"content": "mensupperlower workout routines"}) == "fitness_anchor"
    assert tools._classify_task_role({"content": "upper body gym session"}) == "fitness_anchor"
    # Fallback to family anchors
    assert tools._classify_task_role({"content": "playtime with son"}) == "family_anchor"
    assert tools._classify_task_role({"content": "wife solo break support"}) == "family_anchor"
    # Fallback to routines
    assert tools._classify_task_role({"content": "morning launch routine"}) == "routine"
    assert tools._classify_task_role({"content": "daily reset check"}) == "routine"


def test_evening_briefing_workload_counts(monkeypatch):
    import asyncio
    from datetime import datetime, timedelta
    from unittest.mock import AsyncMock, MagicMock

    tz = tools._runtime_local_tz()
    today_date = datetime.now(tz).date()
    tomorrow_date = today_date + timedelta(days=1)

    # Construct exact 8 true tomorrow tasks, 4 family/fitness anchors, 16 overdue tasks
    mock_tasks = []

    # 8 True Tomorrow workload tasks
    for i in range(8):
        mock_tasks.append({
            "id": f"tom_work_{i}",
            "content": f"Focus Work {i}",
            "due": {"date": tomorrow_date.isoformat()},
            "priority": 3
        })

    # 4 Sacred/Protected anchors (2 family, 2 fitness)
    for i in range(2):
        mock_tasks.append({
            "id": f"fam_anch_{i}",
            "content": f"Son Playtime {i}",
            "due": {"date": tomorrow_date.isoformat()},
            "labels": ["family_anchor"]
        })
    for i in range(2):
        mock_tasks.append({
            "id": f"fit_anch_{i}",
            "content": f"Upper A Gym {i}",
            "due": {"date": tomorrow_date.isoformat()},
            "labels": ["fitness_anchor"]
        })

    # 16 Overdue task debt (12 task debt, 4 stale)
    for i in range(12):
        mock_tasks.append({
            "id": f"debt_{i}",
            "content": f"Overdue Action {i}",
            "due": {"date": (today_date - timedelta(days=2)).isoformat()},
            "priority": 3
        })
    for i in range(4):
        mock_tasks.append({
            "id": f"stale_{i}",
            "content": f"Stale Backlog {i}",
            "due": {"date": (today_date - timedelta(days=10)).isoformat()},
            "priority": 1
        })

    monkeypatch.setattr(tools, "_focus_guard_read_todoist_tasks", lambda **kw: mock_tasks)

    # Mock Telegram send
    sent_messages = []
    def fake_send(msg, **kwargs):
        sent_messages.append((msg, kwargs))
        return {"success": True}
    monkeypatch.setattr(tools, "_safe_send_telegram_message", fake_send)

    # Clear evening date tracker to force briefing trigger
    operator_state = tools._operator_read_state()
    operator_state.pop("last_evening_briefing_date", None)
    tools._operator_write_state(operator_state)

    # Mock time to 9:45 PM America/Edmonton
    mock_now = datetime.now(tz).replace(hour=21, minute=45, second=0, microsecond=0)

    tools._run_scheduler_checks(mock_now)

    assert len(sent_messages) == 1
    brief_msg, kwargs = sent_messages[0]

    # Assert counts are isolated correctly (8 true scheduled tomorrow workload, 16 overdue)
    assert "Tomorrow has 8 scheduled workload items" in brief_msg
    assert "backlog of 12 overdue or carryover items in quarantine" in brief_msg
    assert "4 overdue items look stale rather than urgent" in brief_msg
    assert "Protected Family & Fitness Anchors" in brief_msg
    assert "🌸" in brief_msg
    assert "💪" in brief_msg


def test_handle_briefing_slash_commands(monkeypatch):
    from datetime import datetime, timedelta

    tz = tools._runtime_local_tz()
    today_date = datetime.now(tz).date()
    tomorrow_date = today_date + timedelta(days=1)

    mock_tasks = [
        # True tomorrow workload
        {"id": "t1", "content": "Taxes review", "due": {"date": tomorrow_date.isoformat()}, "priority": 3},
        # Hidden tomorrow reference task
        {"id": "t2", "content": "Owner Deep Work rules", "due": {"date": tomorrow_date.isoformat()}, "labels": ["reference"]},
        # Overdue task debt (3 days overdue)
        {"id": "t3", "content": "Reply to contractor", "due": {"date": (today_date - timedelta(days=3)).isoformat()}, "priority": 3},
        # Stale overdue task (10 days overdue)
        {"id": "t4", "content": "Read garage instructions", "due": {"date": (today_date - timedelta(days=10)).isoformat()}, "priority": 1},
        # Inbox leakage
        {"id": "t5", "content": "Vague task note", "project_id": ""},
        # Duplicate name candidates
        {"id": "t6", "content": "Laundry sweep", "project_id": "proj_1"},
        {"id": "t7", "content": "Laundry sweep", "project_id": "proj_1"}
    ]

    monkeypatch.setattr(tools, "_focus_guard_read_todoist_tasks", lambda **kw: mock_tasks)

    # 1. Test /show_hidden_tomorrow
    res_hidden = tools.handle_briefing_slash_command("show_hidden_tomorrow", "")
    assert "Hidden/Excluded Tasks for Tomorrow" in res_hidden
    assert "Owner Deep Work rules" in res_hidden

    # 2. Test /show_task_debt
    res_debt = tools.handle_briefing_slash_command("show_task_debt", "")
    assert "Active Overdue Task Debt" in res_debt
    assert "Reply to contractor" in res_debt
    assert "Stale Backlog" in res_debt
    assert "Read garage instructions" in res_debt

    # 3. Test /why_suppressed
    res_why = tools.handle_briefing_slash_command("why_suppressed", "")
    assert "Why Suppressed Explanation" in res_why
    assert "Reference Notes" in res_why
    assert "Decayed Overdue Items" in res_why

    # 4. Test /health_score
    res_health = tools.handle_briefing_slash_command("health_score", "")
    assert "Todoist Workspace Clarity:" in res_health
    assert "Active Tasks: 7" in res_health
    assert "Recommended Step:" in res_health

    # 5. Test /entropy_check
    res_entropy = tools.handle_briefing_slash_command("entropy_check", "")
    assert "Weekly Workspace Simplicity Sweep" in res_entropy
    assert "Possible Duplicates" in res_entropy
    assert "Laundry sweep" in res_entropy


def test_todoist_local_fallback_filtering(monkeypatch):
    from datetime import datetime, timedelta

    tz = tools._runtime_local_tz()
    today_date = datetime.now(tz).date()
    today_str = today_date.isoformat()
    tomorrow_str = (today_date + timedelta(days=1)).isoformat()
    yesterday_str = (today_date - timedelta(days=1)).isoformat()

    mock_tasks = [
        {"id": "t_overdue", "content": "Overdue task", "due": {"date": yesterday_str}},
        {"id": "t_today", "content": "Today task", "due": {"date": today_str}},
        {"id": "t_tomorrow", "content": "Tomorrow task", "due": {"date": tomorrow_str}},
        {"id": "t_no_date", "content": "No date task"},
        {"id": "t_overdue_recurring", "content": "Overdue recurring", "due": {"date": yesterday_str, "is_recurring": True}},
        {"id": "t_someday", "content": "Someday task", "labels": ["someday"], "due": {"date": today_str}},
        {"id": "t_maybe", "content": "Maybe task", "labels": ["maybe"], "due": {"date": today_str}}
    ]

    monkeypatch.setattr(tools, "_todoist_native_fetch_tasks", lambda client, params, limit: mock_tasks)

    # 1. Test today | overdue
    res_today_overdue = tools._todoist_native_call({"action": "list_tasks", "filter": "today | overdue"})
    assert res_today_overdue["success"] is True
    ids_today_overdue = {t["id"] for t in res_today_overdue["tasks"]}
    assert ids_today_overdue == {"t_overdue", "t_today"}

    # 2. Test today
    res_today = tools._todoist_native_call({"action": "list_tasks", "filter": "today"})
    assert res_today["success"] is True
    ids_today = {t["id"] for t in res_today["tasks"]}
    assert ids_today == {"t_today"}

    # 3. Test overdue
    res_overdue = tools._todoist_native_call({"action": "list_tasks", "filter": "overdue"})
    assert res_overdue["success"] is True
    ids_overdue = {t["id"] for t in res_overdue["tasks"]}
    assert ids_overdue == {"t_overdue"}

    # 4. Test tomorrow
    res_tomorrow = tools._todoist_native_call({"action": "list_tasks", "filter": "tomorrow"})
    assert res_tomorrow["success"] is True
    ids_tomorrow = {t["id"] for t in res_tomorrow["tasks"]}
    assert ids_tomorrow == {"t_tomorrow"}

    # 5. Test arbitrary filter (should keep everything that is not globally excluded by labels)
    res_arbitrary = tools._todoist_native_call({"action": "list_tasks", "filter": "@work"})
    assert res_arbitrary["success"] is True
    assert len(res_arbitrary["tasks"]) == 4  # Keeps overdue, today, tomorrow, no_date (skips 2 someday/maybe and 1 overdue recurring)


def test_todoist_update_task_execution(monkeypatch):
    calls = []

    class FakeClient:
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc_val, exc_tb):
            pass
        def post(self, url, headers=None, json=None):
            calls.append((url, json))
            return _FakeResponse({"id": "123", "content": "Updated content"})

    monkeypatch.setattr(tools, "_http_client", lambda: FakeClient())
    monkeypatch.setattr(tools, "_todoist_headers", lambda: {"Authorization": "Bearer test"})

    # 1. Test _execute_todoist with update_task
    payload = {
        "action": "update_task",
        "task_id": "123",
        "content": "Updated content",
        "due_string": "tomorrow at 2pm"
    }
    res = tools._execute_todoist(payload)
    assert res["success"] is True
    assert res["task_id"] == "123"
    assert res["task"]["content"] == "Updated content"
    assert len(calls) == 1
    assert calls[0][0] == f"{tools.TODOIST_BASE}/tasks/123"
    assert calls[0][1] == {"content": "Updated content", "due_string": "tomorrow at 2pm"}

    # 2. Test _todoist_native_call with update_task (should request approval)
    args = {
        "action": "update_task",
        "task_id": "123",
        "content": "Updated content",
        "due_string": "tomorrow at 2pm"
    }
    res_call = tools._todoist_native_call(args)
    assert res_call["success"] is False
    assert "update Todoist task 123" in res_call["summary"]
    assert res_call["approval_required"] is True

