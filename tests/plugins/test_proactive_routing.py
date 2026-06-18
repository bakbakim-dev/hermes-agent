from __future__ import annotations

import json


def test_proactive_hook_handles_nested_json_string_result(monkeypatch):
    from plugins.personal_ops import proactive_routing

    payload = {
        "success": True,
        "formatted_list": "- Upper B workout (Thursday)",
        "tasks": [],
    }
    monkeypatch.setattr(
        proactive_routing,
        "handle_todoist",
        lambda args: json.dumps({"result": json.dumps(payload)}),
    )

    context = proactive_routing.proactive_personal_query_hook("session", "what workout today?")

    assert context is not None
    assert "Upper B workout" in context
    assert "personal-operation-context" in context
