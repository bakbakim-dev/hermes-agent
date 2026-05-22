"""Hermes Todoist Repair Queue.

Heuristic cleaners that detect duplicate routines, vague/non-actionable titles,
and junk-drawer tasks. Produces structured repair proposals for one-click approval.
"""
from __future__ import annotations
import json
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERMES_HOME = Path(os.getenv("HERMES_HOME", str(Path.home() / ".hermes")))

# ---------------------------------------------------------------------------
# Vagueness patterns — titles that match these are flagged as non-actionable
# ---------------------------------------------------------------------------
VAGUE_PATTERNS = [
    re.compile(r"^(do|check|handle|review|look at|think about|follow up)\b", re.I),
    re.compile(r"\b(stuff|things|misc|later|soon|maybe|possibly|idk|tbd)\b", re.I),
    re.compile(r"^\w{1,3}$"),                          # Very short titles (1-3 chars)
    re.compile(r"^(test|asdf|temp|todo|xxx)\b", re.I),  # Placeholder-ish titles
]

# Titles that are clearly actionable despite matching vague patterns
ACTIONABLE_OVERRIDES = [
    re.compile(r"\b(call|email|message|send|pay|buy|book|schedule|submit|deploy)\b", re.I),
    re.compile(r"\b(at|by|before|after)\s+\d", re.I),  # Contains a time reference
]

# ---------------------------------------------------------------------------
# Routine duplicate detection
# ---------------------------------------------------------------------------
def _normalize_title(title: str) -> str:
    """Normalize a task title for fuzzy duplicate comparison."""
    t = title.lower().strip()
    # Remove leading emojis, bullet markers, common prefixes
    t = re.sub(r"^[\U00002600-\U0001F9FF\s\-\*\•]+", "", t)
    # Collapse whitespace
    t = re.sub(r"\s+", " ", t).strip()
    return t


def detect_duplicate_routines(tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Find groups of tasks with near-identical titles that look like duplicated routines.

    Returns a list of proposal dicts, each containing:
      - group_key: the normalized title
      - tasks: list of {id, content, due, project_id}
      - suggestion: human-readable fix
    """
    # Group by normalized title
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for task in tasks:
        if task.get("completed"):
            continue
        content = str(task.get("content") or "")
        key = _normalize_title(content)
        if not key:
            continue
        groups[key].append({
            "id": task.get("id"),
            "content": content,
            "due": task.get("due"),
            "project_id": task.get("project_id"),
        })

    proposals = []
    for key, members in groups.items():
        if len(members) < 2:
            continue
        # Check if they share overlapping due dates (recurring clones)
        due_dates = set()
        for m in members:
            due = m.get("due")
            if due and isinstance(due, dict):
                due_dates.add(due.get("date") or due.get("datetime"))

        suggestion = (
            f"Found {len(members)} copies of \"{members[0]['content']}\". "
            f"Keep the one with the correct recurrence and archive the rest."
        )
        proposals.append({
            "type": "duplicate_routine",
            "group_key": key,
            "tasks": members,
            "overlapping_due_dates": len(due_dates) < len(members),
            "suggestion": suggestion,
        })

    return proposals


# ---------------------------------------------------------------------------
# Vagueness / non-actionable title detection
# ---------------------------------------------------------------------------
def detect_vague_tasks(tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Flag tasks whose titles are vague or non-actionable.

    Returns a list of proposal dicts with:
      - task: {id, content, project_id}
      - matched_pattern: description of the matched vagueness signal
      - suggestion: proposed rewrite guidance
    """
    proposals = []
    for task in tasks:
        if task.get("completed"):
            continue
        content = str(task.get("content") or "").strip()
        if not content:
            continue

        # Check overrides first — if clearly actionable, skip
        if any(p.search(content) for p in ACTIONABLE_OVERRIDES):
            continue

        matched = None
        for pattern in VAGUE_PATTERNS:
            if pattern.search(content):
                matched = pattern.pattern
                break

        if matched:
            suggestion = (
                f"Rewrite \"{content}\" to start with a concrete verb and "
                f"include a specific outcome (e.g., 'Email Alice the Q2 report by 3pm')."
            )
            proposals.append({
                "type": "vague_title",
                "task": {
                    "id": task.get("id"),
                    "content": content,
                    "project_id": task.get("project_id"),
                },
                "matched_pattern": matched,
                "suggestion": suggestion,
            })

    return proposals


# ---------------------------------------------------------------------------
# Junk-drawer detection — tasks with no project, no due date, low priority
# ---------------------------------------------------------------------------
def detect_junk_drawer(
    tasks: List[Dict[str, Any]],
    *,
    inbox_project_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Flag tasks that are languishing in the inbox with no due date and low priority.

    Returns a list of proposal dicts with:
      - task: {id, content, project_id, priority}
      - age_days: how many days since creation (if available)
      - suggestion: move, schedule, or delete
    """
    proposals = []
    now = datetime.now(timezone.utc)
    for task in tasks:
        if task.get("completed"):
            continue
        project_id = task.get("project_id")
        due = task.get("due")
        priority = int(task.get("priority", 1))
        content = str(task.get("content") or "").strip()

        # Only flag if: inbox project (or no project), no due date, low priority
        in_inbox = (inbox_project_id and project_id == inbox_project_id) or not project_id
        no_due = not due
        low_priority = priority <= 1

        if in_inbox and no_due and low_priority and content:
            # Estimate age from created_at if available
            age_days = None
            created_at = task.get("created_at")
            if created_at:
                try:
                    created_dt = datetime.fromisoformat(
                        created_at.replace("Z", "+00:00")
                    )
                    age_days = (now - created_dt).days
                except Exception:
                    pass

            suggestion = (
                f"\"{content}\" is sitting in Inbox with no due date and low priority. "
                f"Either move it to a project and schedule it, or delete it."
            )
            proposals.append({
                "type": "junk_drawer",
                "task": {
                    "id": task.get("id"),
                    "content": content,
                    "project_id": project_id,
                    "priority": priority,
                },
                "age_days": age_days,
                "suggestion": suggestion,
            })

    return proposals


# ---------------------------------------------------------------------------
# Combined repair scan
# ---------------------------------------------------------------------------
def run_full_repair_scan(
    tasks: List[Dict[str, Any]],
    *,
    inbox_project_id: Optional[str] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """Run all repair heuristics and return categorized proposals."""
    return {
        "duplicates": detect_duplicate_routines(tasks),
        "vague": detect_vague_tasks(tasks),
        "junk_drawer": detect_junk_drawer(tasks, inbox_project_id=inbox_project_id),
    }


def format_repair_summary(proposals: Dict[str, List[Dict[str, Any]]]) -> str:
    """Format the repair proposals into a human-readable Markdown summary."""
    lines = ["🔧 *Todoist Repair Report*\n"]

    dupes = proposals.get("duplicates", [])
    if dupes:
        lines.append(f"*Duplicate Routines ({len(dupes)} groups):*")
        for p in dupes[:5]:
            count = len(p["tasks"])
            title = p["tasks"][0]["content"] if p["tasks"] else "?"
            lines.append(f"  • {title} × {count}")
        if len(dupes) > 5:
            lines.append(f"  _... and {len(dupes) - 5} more_")
        lines.append("")

    vague = proposals.get("vague", [])
    if vague:
        lines.append(f"*Vague/Non-Actionable ({len(vague)} tasks):*")
        for p in vague[:5]:
            lines.append(f"  • {p['task']['content']}")
        if len(vague) > 5:
            lines.append(f"  _... and {len(vague) - 5} more_")
        lines.append("")

    junk = proposals.get("junk_drawer", [])
    if junk:
        lines.append(f"*Inbox Junk Drawer ({len(junk)} tasks):*")
        for p in junk[:5]:
            age = f" ({p['age_days']}d old)" if p.get("age_days") else ""
            lines.append(f"  • {p['task']['content']}{age}")
        if len(junk) > 5:
            lines.append(f"  _... and {len(junk) - 5} more_")
        lines.append("")

    total = len(dupes) + len(vague) + len(junk)
    if total == 0:
        lines.append("✅ No issues found — your Todoist is clean!")
    else:
        lines.append(f"_Total: {total} issues found._")

    return "\n".join(lines)
