from __future__ import annotations

import json
from pathlib import Path

import pytest

from plugins.personal_ops import temp_personal_ops_tools as tools


@pytest.fixture(autouse=True)
def _isolated_hermes_home(tmp_path, monkeypatch):
    hermes_home = tmp_path / ".hermes"
    hermes_home.mkdir()
    monkeypatch.setattr(tools, "HERMES_HOME", hermes_home)
    monkeypatch.setattr(tools, "EVENTS_PATH", hermes_home / "personal_ops_events.jsonl")
    monkeypatch.setattr(tools, "_append_event", lambda *args, **kwargs: None)
    return hermes_home


def _decode(result: str) -> dict:
    return json.loads(result)


def test_runtime_exposes_isolation_profile_plan():
    result = _decode(tools.handle_runtime({"action": "isolation_profile_plan"}))

    assert result["success"] is True
    assert result["action"] == "isolation_profile_plan"
    assert "personal" in result["profiles"]
    assert result["profiles"]["personal"]["allowed_tools"]


def test_runtime_exposes_intention_gate():
    result = _decode(
        tools.handle_runtime(
            {
                "action": "intention_gate",
                "profile_name": "hermes_engineering",
                "intent": "Patch and deploy the gateway automatically.",
            }
        )
    )

    assert result["success"] is True
    assert result["decision"]["allowed"] is False
    assert result["decision"]["approval_required"] is True


def test_runtime_exposes_hermes_version_status():
    result = _decode(tools.handle_runtime({"action": "hermes_version_status"}))

    assert result["success"] is True
    assert result["action"] == "hermes_version_status"
    assert result["hermes"]["package"] == "hermes-agent"
    assert result["hermes"]["version"]
    assert "Hermes Agent" in result["summary"]
    assert "provider_chain" in result


def test_runtime_exposes_approval_gated_hermes_update_request(monkeypatch):
    monkeypatch.setattr(
        tools,
        "_runtime_upstream_status",
        lambda **kwargs: {
            "local": {"behind": 2, "head": "abc123", "origin_main": "def456"},
            "recent_commit_count": 1,
            "recent_commits": [{"sha": "def456", "message": "Improve runtime status"}],
        },
    )

    result = _decode(tools.handle_runtime({"action": "hermes_update_request"}))

    assert result["success"] is True
    assert result["action"] == "hermes_update_request"
    assert result["updates_available"] is True
    assert result["direct_update_allowed"] is False
    assert result["approval_required"] is True
    assert "approval-gated" in result["recommended_response"]
    assert "skill" not in result["recommended_response"].lower()


def test_runtime_creates_orchestration_job_with_dispatch_plan():
    result = _decode(
        tools.handle_runtime(
            {
                "action": "orchestration_job",
                "mode": "create",
                "profile_name": "hermes_engineering",
                "title": "Fix bad nudge rule",
                "intent": "Create a rule/test proposal from bad nudge feedback.",
            }
        )
    )

    assert result["success"] is True
    assert result["job"]["status"] == "proposed"
    assert result["dispatch_plan"]["controller"] == "hermes"
    assert result["dispatch_plan"]["worker_permissions"]["may_deploy"] is False


def test_capabilities_dossier_includes_orchestration_governance():
    result = _decode(tools.handle_runtime({"action": "hermes_capabilities_dossier"}))

    assert result["success"] is True
    assert "orchestration_governance" in result
    assert "personal" in result["orchestration_governance"]["profiles"]
    assert "controller_worker_job_board" in result["live_layers"]
