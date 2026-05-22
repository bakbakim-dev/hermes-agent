"""Todoist task coach.

This module monitors sticky task patterns and generates low-pressure,
evidence-first repair prompts. Repeated misses are treated as task-design
evidence first, not as a character problem.
"""
from __future__ import annotations

import hashlib
import random
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_AVOIDANCE_THRESHOLD = 0.55
DEFAULT_OVERDUE_DAYS_THRESHOLD = 2
DEFAULT_TIMES_SEEN_THRESHOLD = 4

LAW_TEMPLATES: Dict[str, List[str]] = {
    "make_it_obvious": [
        "{title} is still open. Name the next physical action or repair the task if that is unclear.",
        "{title} needs a clearer finish condition. Write the smallest visible next step.",
        "{title} may be too vague. Convert it to verb + object + done condition.",
        "Before nudging {title} again, make the next action explicit.",
    ],
    "make_it_attractive": [
        "{title} has lingered. The useful move is to make it easier to start, not louder.",
        "{title} may need a better time window or a smaller first step.",
        "If {title} keeps sliding, redesign the task instead of carrying guilt forward.",
        "Make {title} friction-aware: what context would make one step realistic?",
    ],
    "make_it_easy": [
        "Shrink {title} to a 2-minute version, or mark the blocker.",
        "{title} may be too large as written. Pick the smallest piece that creates real progress.",
        "For {title}, one visible step is enough for now.",
        "Break {title} into one start action and one done condition.",
    ],
    "make_it_satisfying": [
        "Closing or repairing {title} would reduce Todoist noise.",
        "{title} is still taking attention. Finish, split, defer, or delete it honestly.",
        "A clean decision on {title} is progress: do, repair, reschedule, or remove.",
        "{title} should leave the list clearer after the next step.",
    ],
}

REPEATED_MISS_REPAIRS = [
    "{title} has repeated enough to treat this as task-design evidence.",
    "{title} may need a smaller version, a better time window, or a clearer done condition.",
    "Before another reminder, decide whether {title} should be done, repaired, or removed.",
    "This looks less like a motivation problem and more like a task-shape problem.",
]

ACCOUNTABILITY_NUDGES = [
    "{title} has appeared {times_seen} times. That is a signal to repair the task before more nudges.",
    "{title} is {days_overdue} days overdue. Choose: do one step, reschedule honestly, or rewrite it.",
    "If {title} keeps getting pushed, split it, delegate it, or lower its active priority.",
    "Is {title} still the right task, or should Hermes propose a cleaner version?",
]


def detect_procrastination(
    sticky_tasks: Dict[str, Dict[str, Any]],
    *,
    avoidance_threshold: float = DEFAULT_AVOIDANCE_THRESHOLD,
    overdue_days_threshold: int = DEFAULT_OVERDUE_DAYS_THRESHOLD,
    times_seen_threshold: int = DEFAULT_TIMES_SEEN_THRESHOLD,
) -> List[Dict[str, Any]]:
    """Return sticky tasks that show drift signals, sorted worst-first."""
    flagged: List[Dict[str, Any]] = []
    for task_id, rec in sticky_tasks.items():
        if rec.get("completed"):
            continue
        score = float(rec.get("avoidance_score", 0))
        times_seen = int(rec.get("times_seen", 0))
        times_overdue = int(rec.get("times_overdue", 0))
        signals = []
        if score >= avoidance_threshold:
            signals.append("high_avoidance")
        if times_overdue >= overdue_days_threshold:
            signals.append("repeatedly_overdue")
        if times_seen >= times_seen_threshold:
            signals.append("lingering")
        if signals:
            flagged.append({**rec, "task_id": task_id, "procrastination_signals": signals})
    flagged.sort(key=lambda r: float(r.get("avoidance_score", 0)), reverse=True)
    return flagged


def select_habit_law(
    task: Dict[str, Any],
    *,
    coach_history: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Pick the best repair lens for the given task."""
    del coach_history
    signals = set(task.get("procrastination_signals", []))
    score = float(task.get("avoidance_score", 0))
    shape = float(task.get("shape_score", 1.0))
    blocker = str(task.get("suspected_blocker", ""))

    if blocker == "unclear_next_action" or shape < 0.55:
        return "make_it_obvious"
    if score >= 0.80 and shape >= 0.55:
        return "make_it_easy"
    if "repeatedly_overdue" in signals:
        return "make_it_attractive"
    if "lingering" in signals:
        return "make_it_satisfying"

    laws = ["make_it_obvious", "make_it_attractive", "make_it_easy", "make_it_satisfying"]
    idx = int(hashlib.md5(str(task.get("task_id", "")).encode()).hexdigest(), 16) % len(laws)
    return laws[idx]


def _pick_variant(
    templates: List[str],
    task: Dict[str, Any],
    coach_history: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """Choose a template variant, avoiding recent repeats."""
    recent_hashes = set()
    if coach_history:
        for entry in coach_history[-6:]:
            h = entry.get("template_hash")
            if h:
                recent_hashes.add(h)
    candidates = []
    for template in templates:
        h = hashlib.md5(template.encode()).hexdigest()[:8]
        if h not in recent_hashes:
            candidates.append(template)
    if not candidates:
        candidates = templates
    return random.choice(candidates)


def build_coach_message(
    task: Dict[str, Any],
    law: str,
    *,
    coach_history: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[str, str]:
    """Build a policy-safe coaching nudge message."""
    title = task.get("title", "your task")
    score = float(task.get("avoidance_score", 0))
    times_seen = int(task.get("times_seen", 0))
    times_overdue = int(task.get("times_overdue", 0))

    parts: List[str] = []

    templates = LAW_TEMPLATES.get(law, LAW_TEMPLATES["make_it_obvious"])
    template = _pick_variant(templates, task, coach_history)
    template_hash = hashlib.md5(template.encode()).hexdigest()[:8]
    parts.append(
        template.format(
            title=title,
            times_seen=times_seen,
            days_overdue=times_overdue,
        )
    )

    if score >= 0.75 and times_seen >= 5:
        parts.append(random.choice(REPEATED_MISS_REPAIRS).format(title=title))

    if score >= 0.85:
        parts.append(
            random.choice(ACCOUNTABILITY_NUDGES).format(
                title=title,
                times_seen=times_seen,
                days_overdue=times_overdue,
            )
        )

    return "\n".join(parts), template_hash


def run_coach(
    state: Dict[str, Any],
    focus_state: Dict[str, Any],
    *,
    avoidance_threshold: float = DEFAULT_AVOIDANCE_THRESHOLD,
    max_nudges: int = 1,
) -> Dict[str, Any]:
    """Evaluate sticky tasks and return coaching data."""
    del focus_state, max_nudges
    sticky = dict(state.get("sticky_tasks") or {})
    coach_history = list(state.get("coach_history") or [])

    flagged = detect_procrastination(
        sticky,
        avoidance_threshold=avoidance_threshold,
    )

    if not flagged:
        return {
            "coached": False,
            "message": "",
            "task": None,
            "law": None,
            "flagged_count": 0,
        }

    top = flagged[0]
    law = select_habit_law(top, coach_history=coach_history)
    message, template_hash = build_coach_message(top, law, coach_history=coach_history)

    return {
        "coached": True,
        "message": message,
        "task": {
            "task_id": top.get("task_id"),
            "title": top.get("title"),
            "avoidance_score": top.get("avoidance_score"),
            "times_seen": top.get("times_seen"),
            "times_overdue": top.get("times_overdue"),
            "signals": top.get("procrastination_signals"),
        },
        "law": law,
        "template_hash": template_hash,
        "flagged_count": len(flagged),
    }
