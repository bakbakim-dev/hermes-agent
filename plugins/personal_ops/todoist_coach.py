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
        "{title} is still open. Let's make the next step simple and clear so your brain doesn't have to guess.",
        "{title} might need a smaller start point. What is the absolute easiest next step you can see?",
        "If {title} feels a bit vague, let's write down one quick, simple action to begin.",
        "Let's put {title} somewhere you can't miss it, and name one tiny step to start.",
    ],
    "make_it_attractive": [
        "{title} has been waiting a while. Let's make starting easier by pairing it with something you enjoy—like a good cup of coffee or your favorite music.",
        "Could {title} be paired with a comfortable spot or a quiet window to make getting started feel good?",
        "If you keep pushing {title} back, it's not a failure on your part—it just means the task might need a gentler path or a better time window.",
        "Let's make {title} feel welcoming. What is one small, stress-free step you could take right now?",
    ],
    "make_it_easy": [
        "Let's shrink {title} to a simple 2-minute version. Just starting is the goal—momentum will carry you from there.",
        "{title} might feel a bit too big right now. What's the absolute smallest piece we can pick to make easy progress?",
        "For {title}, just one visible, tiny step is more than enough for today.",
        "Let's break {title} down into just one quick start action. No need to worry about finishing the whole thing today.",
    ],
    "make_it_satisfying": [
        "Finishing or simply simplifying {title} will help clear your mind and give you a nice, clean win.",
        "{title} has been on your mind. Let's make a comfortable, stress-free decision: do one tiny step, reschedule it, or let it go honestly.",
        "A clear, honest decision on {title} is wonderful progress. Let's take one tiny step or choose to let it wait.",
        "Let's get {title} off your list so you can enjoy a lighter, clearer day.",
    ],
}

REPEATED_MISS_REPAIRS = [
    "Since {title} has been rescheduled a few times, let's treat this as a sign that it's simply too big or needs a friendlier approach, not as a motivation problem.",
    "If {title} keeps sliding, let's try a smaller version or a more comfortable time of day.",
    "Let's take the pressure off {title}—decide if it's the right time to do a tiny piece, reschedule it with zero guilt, or remove it for now.",
    "This isn't about willpower. Usually, if a task keeps getting pushed, it's just written in a way that feels a bit too heavy. Let's make it lighter.",
]

ACCOUNTABILITY_NUDGES = [
    "I've noticed {title} has popped up {times_seen} times. Let's make it simpler and easier to start before we look at it again.",
    "{title} has been waiting for {days_overdue} days. Let's be gentle: can you do one quick step, reschedule it honestly, or change it to something smaller?",
    "If {title} keeps getting pushed, let's break it into bite-sized pieces or set a lower priority so you don't have to worry about it.",
    "Is {title} still something you want to do right now, or should we give it a fresh, simpler focus?",
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
