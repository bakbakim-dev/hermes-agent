from __future__ import annotations

import json
from pathlib import Path

from plugins.personal_ops.context_budget import (
    build_no_agent_cron_plan,
    build_secret_inventory,
    log_turn_context_contributors,
    summarize_turn_context_contributors,
)
from plugins.personal_ops.tool_router import (
    route_tool_call,
    router_enforce_default,
    summarize_tool_router_events,
)


def test_turn_context_contributor_report_reads_gateway_jsonl(tmp_path: Path) -> None:
    home = tmp_path / ".hermes"
    (home / "memories").mkdir(parents=True)
    (home / "memories" / "MEMORY.md").write_text("stable memory", encoding="utf-8")
    (home / "memories" / "USER.md").write_text("user preference", encoding="utf-8")

    log_turn_context_contributors(
        hermes_home=home,
        platform="telegram",
        session_key="s1",
        context_prompt="context prompt",
        history=[{"role": "user", "content": "hello"}],
        agent_result={
            "model": "test-model",
            "last_prompt_tokens": 120,
            "context_length": 1000,
            "tools": [{"name": "personal_todoist"}],
        },
    )

    report = summarize_turn_context_contributors(hermes_home=home)

    assert report["success"] is True
    assert report["event_count"] == 1
    assert report["max_context_pct"] == 12.0
    assert report["top_tools"] == [{"name": "personal_todoist", "count": 1}]


def test_tool_router_simulates_high_risk_tool_without_default_block() -> None:
    decision = route_tool_call(
        tool_name="browser_click",
        intent_text="what is on my Todoist today",
        enforce=False,
    )

    assert decision.intent == "todoist"
    assert decision.approval_required is True
    assert decision.enforce_mode is False
    assert any("audit mode" in reason for reason in decision.reasons)


def test_tool_router_enforcement_defaults_on_when_env_absent(monkeypatch) -> None:
    monkeypatch.delenv("HERMES_TOOL_ROUTER_ENFORCE", raising=False)

    assert router_enforce_default() is True
    decision = route_tool_call(
        tool_name="browser_click",
        intent_text="what is on my Todoist today",
    )
    assert decision.enforce_mode is True
    assert decision.allowed is False


def test_tool_router_event_summary(tmp_path: Path) -> None:
    home = tmp_path / ".hermes"
    home.mkdir()
    event_path = home / "tool_router_events.jsonl"
    event_path.write_text(
        json.dumps(
            {
                "type": "tool_route_decision",
                "decision": {
                    "tool_name": "browser_click",
                    "tool_class": "browser_logged_in",
                    "approval_required": True,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    summary = summarize_tool_router_events(hermes_home=home)

    assert summary["event_count"] == 1
    assert summary["high_risk_seen"] == 1
    assert summary["by_class"] == {"browser_logged_in": 1}


def test_secret_inventory_redacts_values_and_flags_repo_env(tmp_path: Path) -> None:
    home = tmp_path / ".hermes"
    repo = tmp_path / "repo"
    home.mkdir()
    repo.mkdir()
    (home / ".env").write_text("TODOIST_API_TOKEN=secret\nNORMAL=value\n", encoding="utf-8")
    (repo / ".env").write_text("LANGFUSE_SECRET_KEY=secret\n", encoding="utf-8")

    inventory = build_secret_inventory(hermes_home=home, repo_path=repo)

    names = {row["name"] for row in inventory["secrets"]}
    assert {"TODOIST_API_TOKEN", "LANGFUSE_SECRET_KEY"} <= names
    assert all(row["value_redacted"] for row in inventory["secrets"])
    assert str(repo / ".env") in inventory["risky_files"]


def test_no_agent_cron_plan_is_approval_gated() -> None:
    plan = build_no_agent_cron_plan()

    assert plan["approval_required_to_install"] is True
    assert {job["name"] for job in plan["jobs"]} >= {
        "hermes-health-snapshot",
        "context-budget-audit",
        "secret-inventory-check",
    }
