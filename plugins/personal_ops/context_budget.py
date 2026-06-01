"""Context-budget auditing for Hermes personal operations.

The goal is not to stuff more into every prompt. It is to make the hidden
context load visible: prompt memory, enabled plugins, large skills, and any
recommendations that should be approval-gated before pruning.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional


DEFAULT_KEEP_PLUGINS = {
    "personal-ops",
    "personal_ops",
    "memory",
    "todoist",
    "telegram",
    "activitywatch",
    "langfuse",
}


def estimate_tokens(text: str) -> int:
    """Return a rough token estimate without importing model tokenizers."""
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _skill_files(repo_path: Path) -> Iterable[Path]:
    for root in ("skills", "optional-skills", "plugins"):
        base = repo_path / root
        if not base.exists():
            continue
        yield from base.rglob("SKILL.md")


def _skill_name(path: Path, repo_path: Path) -> str:
    try:
        rel = path.relative_to(repo_path)
    except ValueError:
        rel = path
    if rel.parts and rel.parts[0] == "skills" and len(rel.parts) >= 2:
        return rel.parts[-2]
    parent = rel.parent
    return str(parent).replace("\\", "/")


def audit_context_budget(
    *,
    hermes_home: Path,
    repo_path: Path,
    write_event: bool = False,
) -> Dict[str, Any]:
    """Measure major prompt/context contributors and return recommendations."""
    hermes_home = Path(hermes_home)
    repo_path = Path(repo_path)
    memory_text = _read_text(hermes_home / "memories" / "MEMORY.md")
    user_text = _read_text(hermes_home / "memories" / "USER.md")

    skills: List[Dict[str, Any]] = []
    for path in _skill_files(repo_path):
        text = _read_text(path)
        skills.append(
            {
                "name": _skill_name(path, repo_path),
                "path": str(path),
                "chars": len(text),
                "estimated_tokens": estimate_tokens(text),
            }
        )
    skills.sort(key=lambda item: int(item["estimated_tokens"]), reverse=True)

    recommendations: List[Dict[str, Any]] = []
    for skill in skills:
        if int(skill["estimated_tokens"]) >= 3000:
            recommendations.append(
                {
                    "kind": "split_large_skill",
                    "target": skill["name"],
                    "estimated_tokens": skill["estimated_tokens"],
                    "reason": "Large skills should be tiny routers plus on-demand references.",
                    "approval_required": True,
                }
            )
    if len(user_text) > 6000 or len(memory_text) > 9000:
        recommendations.append(
            {
                "kind": "compact_prompt_memory",
                "reason": "Prompt memory is useful but should stay curated; structured stores handle bulk history better.",
                "approval_required": True,
            }
        )

    total_estimated_tokens = (
        estimate_tokens(memory_text)
        + estimate_tokens(user_text)
        + sum(int(item["estimated_tokens"]) for item in skills)
    )
    report = {
        "success": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "prompt_memory": {
            "memory_chars": len(memory_text),
            "memory_estimated_tokens": estimate_tokens(memory_text),
            "user_chars": len(user_text),
            "user_estimated_tokens": estimate_tokens(user_text),
        },
        "skills": {
            "skill_count": len(skills),
            "largest_skills": skills[:10],
        },
        "total_estimated_tokens": total_estimated_tokens,
        "recommendations": recommendations,
    }
    if write_event:
        event_path = hermes_home / "context_budget_events.jsonl"
        event_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "type": "context_budget_audit",
            "created_at": report["generated_at"],
            "summary": {
                "total_estimated_tokens": total_estimated_tokens,
                "skill_count": len(skills),
                "recommendation_count": len(recommendations),
            },
        }
        with open(event_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return report


def _messages_chars(messages: Iterable[Mapping[str, Any]]) -> int:
    total = 0
    for msg in messages:
        content = msg.get("content") if isinstance(msg, Mapping) else ""
        if isinstance(content, str):
            total += len(content)
        elif content is not None:
            total += len(str(content))
    return total


def log_turn_context_contributors(
    *,
    hermes_home: Path,
    platform: str,
    session_key: str,
    message_id: str = "",
    model: str = "",
    context_prompt: str = "",
    history: Optional[List[Mapping[str, Any]]] = None,
    agent_result: Optional[Mapping[str, Any]] = None,
    injected_skills: Optional[List[str]] = None,
    injected_files: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Write a per-turn context accounting event.

    This records deterministic contributors visible to the gateway. It does
    not pretend to know provider-side internals; unknown fields stay explicit.
    """
    hermes_home = Path(hermes_home)
    history = history or []
    agent_result = agent_result or {}
    memory_text = _read_text(hermes_home / "memories" / "MEMORY.md")
    user_text = _read_text(hermes_home / "memories" / "USER.md")
    history_chars = _messages_chars(history)
    tools = agent_result.get("tools") or []
    if not isinstance(tools, list):
        tools = []
    last_prompt_tokens = int(agent_result.get("last_prompt_tokens") or 0)
    context_length = int(agent_result.get("context_length") or 0)
    context_pct = round((last_prompt_tokens / context_length) * 100, 1) if context_length else None
    record = {
        "type": "turn_context_contributors",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "platform": platform,
        "session_key": session_key,
        "message_id": str(message_id or ""),
        "model": model or str(agent_result.get("model") or ""),
        "contributors": {
            "prompt_memory": {
                "memory_chars": len(memory_text),
                "memory_estimated_tokens": estimate_tokens(memory_text),
                "user_chars": len(user_text),
                "user_estimated_tokens": estimate_tokens(user_text),
            },
            "context_prompt": {
                "chars": len(context_prompt or ""),
                "estimated_tokens": estimate_tokens(context_prompt or ""),
            },
            "history": {
                "message_count": len(history),
                "chars": history_chars,
                "estimated_tokens": estimate_tokens("x" * history_chars),
            },
            "tools": {
                "schema_count": len(tools),
                "names": [str((item or {}).get("name") or "") for item in tools if isinstance(item, Mapping)][:50],
            },
            "skills": {
                "known_injected": injected_skills or [],
                "observability_limit": "gateway records explicitly injected skills only; skill auto-loader internals may need separate instrumentation",
            },
            "files": {
                "known_injected": injected_files or [],
            },
        },
        "runtime": {
            "last_prompt_tokens": last_prompt_tokens,
            "context_length": context_length,
            "context_pct": context_pct,
            "input_tokens": int(agent_result.get("input_tokens") or 0),
            "output_tokens": int(agent_result.get("output_tokens") or 0),
            "compression_exhausted": bool(agent_result.get("compression_exhausted")),
        },
    }
    event_path = hermes_home / "turn_context_events.jsonl"
    event_path.parent.mkdir(parents=True, exist_ok=True)
    with open(event_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record


def prune_profile_recommendations(
    *,
    config_data: Mapping[str, Any],
    keep_plugins: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Return an approval-gated plugin pruning plan without mutating config."""
    keep = {str(item) for item in (keep_plugins or DEFAULT_KEEP_PLUGINS)}
    plugins_cfg = config_data.get("plugins") if isinstance(config_data, Mapping) else {}
    enabled = []
    if isinstance(plugins_cfg, Mapping):
        raw = plugins_cfg.get("enabled") or []
        if isinstance(raw, list):
            enabled = [str(item) for item in raw]
    keep_enabled = [item for item in enabled if item in keep]
    disable_candidates = [item for item in enabled if item not in keep]
    return {
        "success": True,
        "enabled_count": len(enabled),
        "keep_enabled": keep_enabled,
        "disable_candidates": disable_candidates,
        "approval_required": bool(disable_candidates),
        "reason": "Pruning should be explicit because plugins can expose tools and shape prompt context.",
    }


def summarize_turn_context_contributors(*, hermes_home: Path, limit: int = 200) -> Dict[str, Any]:
    """Summarize recent per-turn context accounting events."""
    path = Path(hermes_home) / "turn_context_events.jsonl"
    events: List[Dict[str, Any]] = []
    if path.exists():
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("type") == "turn_context_contributors":
                events.append(record)

    totals = {
        "memory_estimated_tokens": 0,
        "user_estimated_tokens": 0,
        "context_prompt_estimated_tokens": 0,
        "history_estimated_tokens": 0,
        "last_prompt_tokens": 0,
    }
    tool_counts: Dict[str, int] = {}
    max_context_pct: float | None = None
    for event in events:
        contributors = event.get("contributors") or {}
        prompt_memory = contributors.get("prompt_memory") or {}
        context_prompt = contributors.get("context_prompt") or {}
        history = contributors.get("history") or {}
        runtime = event.get("runtime") or {}
        totals["memory_estimated_tokens"] += int(prompt_memory.get("memory_estimated_tokens") or 0)
        totals["user_estimated_tokens"] += int(prompt_memory.get("user_estimated_tokens") or 0)
        totals["context_prompt_estimated_tokens"] += int(context_prompt.get("estimated_tokens") or 0)
        totals["history_estimated_tokens"] += int(history.get("estimated_tokens") or 0)
        totals["last_prompt_tokens"] += int(runtime.get("last_prompt_tokens") or 0)
        pct = runtime.get("context_pct")
        if isinstance(pct, (int, float)):
            max_context_pct = float(pct) if max_context_pct is None else max(max_context_pct, float(pct))
        tools = (contributors.get("tools") or {}).get("names") or []
        if isinstance(tools, list):
            for name in tools:
                if name:
                    tool_counts[str(name)] = tool_counts.get(str(name), 0) + 1

    count = len(events)
    averages = {
        key: round(value / count, 1) if count else 0
        for key, value in totals.items()
    }
    top_tools = sorted(tool_counts.items(), key=lambda item: item[1], reverse=True)[:20]
    recommendations: List[str] = []
    if averages["last_prompt_tokens"] >= 12000:
        recommendations.append("Average prompt load is high; narrow toolsets and compact memory before adding capabilities.")
    if averages["history_estimated_tokens"] > averages["context_prompt_estimated_tokens"] * 2 and count:
        recommendations.append("Conversation history dominates recent turns; summarize or reset stale sessions sooner.")
    if not events:
        recommendations.append("No turn context events found yet; send a gateway turn after this build to populate the report.")
    return {
        "success": True,
        "action": "context_contributors_report",
        "event_count": count,
        "averages": averages,
        "max_context_pct": max_context_pct,
        "top_tools": [{"name": name, "count": seen} for name, seen in top_tools],
        "recommendations": recommendations,
        "event_path": str(path),
    }


def build_secret_inventory(*, hermes_home: Path, repo_path: Path) -> Dict[str, Any]:
    """Inventory configured secret names without exposing values."""
    candidates = [
        Path(hermes_home) / ".env",
        Path(repo_path) / ".env",
        Path(repo_path) / ".env.example",
    ]
    rows: List[Dict[str, Any]] = []
    risky_files: List[str] = []
    for path in candidates:
        if not path.exists():
            continue
        if path.name == ".env" and path.is_relative_to(Path(repo_path)):
            risky_files.append(str(path))
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            key = key.strip()
            if any(marker in key.upper() for marker in ("KEY", "TOKEN", "SECRET", "PASSWORD", "WEBHOOK")):
                rows.append(
                    {
                        "name": key,
                        "file": str(path),
                        "configured": bool(value.strip().strip('"').strip("'")),
                        "value_redacted": True,
                    }
                )
    return {
        "success": True,
        "action": "secret_inventory",
        "secret_count": len(rows),
        "secrets": rows,
        "risky_files": risky_files,
        "recommendations": [
            "Keep real .env files out of source archives.",
            "Prefer a secret broker or service-specific environment files for high-risk integrations.",
            "Never write secret values into traces, capability dossiers, or Telegram replies.",
        ],
    }


def build_no_agent_cron_plan() -> Dict[str, Any]:
    """Return deterministic maintenance jobs that do not need an LLM turn."""
    jobs = [
        {
            "name": "hermes-health-snapshot",
            "cadence": "every 15 minutes",
            "command": "hermes doctor --deep",
            "purpose": "Detect gateway, Todoist MCP, tracing, and plugin health regressions without asking the model.",
        },
        {
            "name": "context-budget-audit",
            "cadence": "daily",
            "command": "personal_runtime action=context_budget_audit",
            "purpose": "Track memory, skill, and prompt-size drift.",
        },
        {
            "name": "unused-tool-skill-report",
            "cadence": "weekly",
            "command": "personal_runtime action=context_contributors_report",
            "purpose": "Recommend profile pruning based on observed use.",
        },
        {
            "name": "secret-inventory-check",
            "cadence": "weekly",
            "command": "personal_runtime action=secret_inventory",
            "purpose": "Confirm configured secret names are known and real .env files are not exported.",
        },
    ]
    return {
        "success": True,
        "action": "no_agent_cron_plan",
        "jobs": jobs,
        "approval_required_to_install": True,
        "reason": "These are deterministic checks; Hermes should run them without spending LLM context, but install still changes runtime behavior.",
    }


def classify_memory_destination(content: str, *, memory_type: str = "note") -> Dict[str, Any]:
    """Choose the right memory tier for a new fact/rule."""
    lowered_type = memory_type.strip().lower()
    lowered_content = content.strip().lower()
    if lowered_type in {"common_sense_rule", "policy_rule", "todoist_rule", "rollover_policy"}:
        return {
            "destination": "operator_rule_store",
            "inject_into_prompt": False,
            "reason": "structured behavior rules should live in the Hermes rule store and be retrieved/applied by code",
        }
    if any(word in lowered_content for word in ("temporary", "today", "done", "completed", "log")):
        return {
            "destination": "event_log",
            "inject_into_prompt": False,
            "reason": "temporary/session facts belong in events, not durable prompt memory",
        }
    if lowered_type in {"explicit_preference", "stable_user_fact", "communication_preference"}:
        return {
            "destination": "prompt_user_memory",
            "inject_into_prompt": True,
            "reason": "stable user preferences are useful in the prompt when kept compact",
        }
    return {
        "destination": "pending_memory_review",
        "inject_into_prompt": False,
        "reason": "unclear memory candidates should be reviewed before prompt injection",
    }
