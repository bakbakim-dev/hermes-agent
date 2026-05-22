from __future__ import annotations

import json
from pathlib import Path

from plugins.personal_ops.orchestration_kernel import (
    build_dispatch_plan,
    default_profiles,
    evaluate_intention,
    job_board_status,
    record_job,
)


def test_default_profiles_isolate_personal_ops_from_engineering_and_finance():
    profiles = default_profiles()

    personal = profiles["personal"]
    engineering = profiles["hermes_engineering"]
    finance = profiles["finance"]

    assert "telegram" in personal.allowed_tools
    assert "todoist" in personal.allowed_tools
    assert "shell" not in personal.allowed_tools
    assert "code_patch" in engineering.allowed_tools
    assert "todoist_write" not in engineering.allowed_tools
    assert "financial_write" in finance.blocked_tools
    assert finance.requires_approval is True


def test_intention_gate_blocks_autonomous_deploy_and_allows_analysis():
    blocked = evaluate_intention(
        "Patch the gateway, deploy it to production, and restart services",
        profile_name="hermes_engineering",
    )
    allowed = evaluate_intention(
        "Analyze Todoist task debt and create a repair proposal",
        profile_name="personal",
    )

    assert blocked.allowed is False
    assert blocked.approval_required is True
    assert "deploy" in blocked.reasons[0].lower()
    assert allowed.allowed is True
    assert allowed.approval_required is False


def test_job_board_persists_controller_worker_jobs(tmp_path):
    db_path = tmp_path / "orchestration_jobs.sqlite3"

    job = record_job(
        db_path=db_path,
        profile_name="hermes_engineering",
        title="Draft self-improvement patch",
        intent="Create a patch proposal, tests, and diff summary only.",
        controller="hermes",
        worker="codex_sandbox",
        status="proposed",
    )
    status = job_board_status(db_path=db_path)

    assert job["job_id"].startswith("job_")
    assert status["success"] is True
    assert status["job_count"] == 1
    assert status["jobs"][0]["profile_name"] == "hermes_engineering"
    assert status["jobs"][0]["status"] == "proposed"


def test_dispatch_plan_keeps_controller_separate_from_worker():
    plan = build_dispatch_plan(
        title="Fix bad nudge rule",
        intent="Create a rule/test proposal from bad nudge feedback.",
        profile_name="hermes_engineering",
    )

    assert plan["controller"] == "hermes"
    assert plan["worker"] != plan["controller"]
    assert plan["reviewer"] == "hermes"
    assert plan["worker_permissions"]["may_deploy"] is False
    assert plan["approval_required_before_execution"] is True

