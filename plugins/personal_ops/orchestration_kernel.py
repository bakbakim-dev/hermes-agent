"""Hermes orchestration governance.

This module borrows the useful parts of multi-project/orchestrator patterns
without turning Hermes into an unbounded autonomous engineer. It keeps context
profiles explicit, routes work through an intention gate, and records proposed
controller/worker jobs in a tiny durable job board.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional


@dataclass(frozen=True)
class IsolationProfile:
    name: str
    purpose: str
    allowed_tools: List[str]
    blocked_tools: List[str]
    context_policy: str
    requires_approval: bool
    risk_notes: List[str]


@dataclass(frozen=True)
class IntentionDecision:
    allowed: bool
    approval_required: bool
    profile_name: str
    intent: str
    reasons: List[str]
    suggested_mode: str
    blocked_terms: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def default_profiles() -> Dict[str, IsolationProfile]:
    """Return Hermes' recommended context/tool isolation profiles."""
    profiles = [
        IsolationProfile(
            name="personal",
            purpose="Daily personal operations, Todoist repair, memory/rules, presence, and Telegram nudges.",
            allowed_tools=[
                "telegram",
                "todoist",
                "todoist_read",
                "todoist_draft",
                "memory_read",
                "memory_rule_store",
                "activitywatch",
                "trace_read",
            ],
            blocked_tools=[
                "shell",
                "code_patch",
                "browser_logged_in",
                "financial_write",
                "public_post",
                "destructive_delete",
            ],
            context_policy="Load personal-ops router, Todoist task summaries, rules, presence state, and only relevant memories.",
            requires_approval=False,
            risk_notes=["Todoist writes still need approval when bulk, destructive, recurring, or ambiguous."],
        ),
        IsolationProfile(
            name="hermes_engineering",
            purpose="Hermes repo maintenance, tests, self-improvement proposals, and approved patch plans.",
            allowed_tools=[
                "repo_read",
                "test_run",
                "code_patch",
                "diff_summary",
                "trace_read",
                "promptfoo_export",
            ],
            blocked_tools=[
                "todoist_write",
                "telegram_proactive_send",
                "financial_write",
                "public_post",
                "deploy_without_approval",
            ],
            context_policy="Load repo/test context and relevant runtime evidence; do not load personal task details unless needed for a bug.",
            requires_approval=True,
            risk_notes=["Patches, deploys, service restarts, and rollbacks must be branch/test/diff/approval gated."],
        ),
        IsolationProfile(
            name="business",
            purpose="Business-hours-aware task reasoning without assuming unconfigured business apps.",
            allowed_tools=["todoist_read", "calendar_read", "memory_rule_store", "telegram_question"],
            blocked_tools=["crm_write", "customer_message", "staff_message_after_hours", "financial_write"],
            context_policy="Use only business facts explicitly provided by the user and Todoist tasks; do not infer hidden systems.",
            requires_approval=True,
            risk_notes=["External person/contact actions are draft/schedule only unless explicitly approved as urgent."],
        ),
        IsolationProfile(
            name="finance",
            purpose="Read-only financial/admin context when explicitly connected later.",
            allowed_tools=["todoist_read", "budget_read", "document_read_summary"],
            blocked_tools=["financial_write", "payment", "bank_transfer", "tax_filing", "document_delete"],
            context_policy="Use summaries and metadata first; raw private documents require explicit approval.",
            requires_approval=True,
            risk_notes=["No payments, filings, cancellations, or financial writes without explicit per-action approval."],
        ),
        IsolationProfile(
            name="experimental",
            purpose="New connector or agent experiments in sandbox mode.",
            allowed_tools=["sandbox_read", "dry_run", "draft_only", "eval_run"],
            blocked_tools=["production_write", "credential_access", "browser_logged_in", "deploy_without_approval"],
            context_policy="Use synthetic fixtures or redacted state; never attach production credentials by default.",
            requires_approval=True,
            risk_notes=["Experiments should produce reports/proposals, not mutate live systems."],
        ),
    ]
    return {profile.name: profile for profile in profiles}


def profiles_as_dict() -> Dict[str, Dict[str, Any]]:
    return {name: asdict(profile) for name, profile in default_profiles().items()}


_RISK_TERMS = {
    "deploy": "Deploy/restart/production changes require GitOps approval.",
    "restart": "Service restarts require explicit approval unless they are already approved safe maintenance.",
    "delete": "Destructive deletes require approval and a simulation/diff.",
    "payment": "Financial actions require explicit approval every time.",
    "pay ": "Financial actions require explicit approval every time.",
    "send to staff": "External person messages require approval or draft/schedule mode.",
    "message staff": "External person messages require approval or draft/schedule mode.",
    "customer": "Customer-facing actions require explicit approval until business systems are configured.",
    "browser logged": "Logged-in browser automation requires explicit session approval.",
    "credential": "Credential access is blocked by default.",
    "secret": "Credential/secret access is blocked by default.",
    "production": "Production changes require GitOps approval.",
    "auto-apply": "Autonomous mutation is blocked; create proposal/patch/diff first.",
    "automatically apply": "Autonomous mutation is blocked; create proposal/patch/diff first.",
}


def evaluate_intention(intent: str, *, profile_name: str = "personal") -> IntentionDecision:
    """Classify a proposed action before any worker/tool is allowed to act."""
    intent_text = str(intent or "").strip()
    lower = f" {intent_text.lower()} "
    profiles = default_profiles()
    profile = profiles.get(profile_name) or profiles["personal"]

    reasons: List[str] = []
    blocked_terms: List[str] = []
    for term, reason in _RISK_TERMS.items():
        if term in lower:
            blocked_terms.append(term.strip())
            if reason not in reasons:
                reasons.append(reason)

    if "patch" in lower and profile.name != "hermes_engineering":
        blocked_terms.append("patch")
        reasons.append("Code patch work belongs in the hermes_engineering profile.")

    approval_required = bool(blocked_terms or profile.requires_approval)
    allowed = not blocked_terms
    if allowed and profile.name in {"business", "finance", "experimental", "hermes_engineering"}:
        reasons.append("Profile is approval-sensitive; use proposal/draft mode before execution.")

    suggested_mode = "proposal_only" if approval_required else "execute_low_risk"
    if blocked_terms:
        suggested_mode = "draft_plan_then_request_approval"

    return IntentionDecision(
        allowed=allowed,
        approval_required=approval_required,
        profile_name=profile.name,
        intent=intent_text,
        reasons=reasons or ["Low-risk analysis/draft intent inside profile boundaries."],
        suggested_mode=suggested_mode,
        blocked_terms=blocked_terms,
    )


def build_dispatch_plan(*, title: str, intent: str, profile_name: str = "personal") -> Dict[str, Any]:
    """Build a controller/worker/reviewer plan without executing it."""
    decision = evaluate_intention(intent, profile_name=profile_name)
    worker = "codex_sandbox" if profile_name == "hermes_engineering" else "hermes_personal_ops_worker"
    profile = default_profiles().get(decision.profile_name) or default_profiles()["personal"]
    return {
        "title": str(title or "Untitled Hermes job"),
        "intent": decision.intent,
        "profile_name": profile.name,
        "controller": "hermes",
        "worker": worker,
        "reviewer": "hermes",
        "decision": decision.to_dict(),
        "worker_permissions": {
            "may_read": True,
            "may_write_drafts": True,
            "may_patch": "code_patch" in profile.allowed_tools,
            "may_deploy": False,
            "may_contact_external_people": False,
            "may_use_credentials": False,
        },
        "approval_required_before_execution": bool(decision.approval_required),
        "handoff_contract": [
            "Worker produces artifacts, diffs, tests, or proposal summaries only.",
            "Worker does not approve its own work.",
            "Hermes reviews evidence, risk, and user-visible summary before asking approval.",
            "No deploy, external send, destructive edit, or financial action occurs from this plan alone.",
        ],
    }


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS orchestration_jobs (
            job_id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            profile_name TEXT NOT NULL,
            title TEXT NOT NULL,
            intent TEXT NOT NULL,
            controller TEXT NOT NULL,
            worker TEXT NOT NULL,
            reviewer TEXT NOT NULL,
            status TEXT NOT NULL,
            decision_json TEXT NOT NULL,
            plan_json TEXT NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def record_job(
    *,
    db_path: Path,
    profile_name: str,
    title: str,
    intent: str,
    controller: str = "hermes",
    worker: Optional[str] = None,
    status: str = "proposed",
) -> Dict[str, Any]:
    plan = build_dispatch_plan(title=title, intent=intent, profile_name=profile_name)
    if worker:
        plan["worker"] = worker
    if controller:
        plan["controller"] = controller
    now = datetime.now(timezone.utc).isoformat()
    job_id = f"job_{uuid.uuid4().hex[:12]}"
    row = {
        "job_id": job_id,
        "created_at": now,
        "updated_at": now,
        "profile_name": plan["profile_name"],
        "title": plan["title"],
        "intent": plan["intent"],
        "controller": plan["controller"],
        "worker": plan["worker"],
        "reviewer": plan["reviewer"],
        "status": status,
        "decision": plan["decision"],
        "dispatch_plan": plan,
    }
    with _connect(Path(db_path)) as conn:
        conn.execute(
            """
            INSERT INTO orchestration_jobs (
                job_id, created_at, updated_at, profile_name, title, intent,
                controller, worker, reviewer, status, decision_json, plan_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                now,
                now,
                row["profile_name"],
                row["title"],
                row["intent"],
                row["controller"],
                row["worker"],
                row["reviewer"],
                row["status"],
                json.dumps(row["decision"], ensure_ascii=False),
                json.dumps(row["dispatch_plan"], ensure_ascii=False),
            ),
        )
        conn.commit()
    return row


def job_board_status(*, db_path: Path, limit: int = 25) -> Dict[str, Any]:
    with _connect(Path(db_path)) as conn:
        rows = conn.execute(
            """
            SELECT * FROM orchestration_jobs
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
        count = conn.execute("SELECT COUNT(*) AS c FROM orchestration_jobs").fetchone()["c"]
    jobs = []
    for row in rows:
        jobs.append(
            {
                "job_id": row["job_id"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "profile_name": row["profile_name"],
                "title": row["title"],
                "intent": row["intent"],
                "controller": row["controller"],
                "worker": row["worker"],
                "reviewer": row["reviewer"],
                "status": row["status"],
                "decision": json.loads(row["decision_json"]),
                "dispatch_plan": json.loads(row["plan_json"]),
            }
        )
    return {"success": True, "job_count": int(count), "jobs": jobs}

