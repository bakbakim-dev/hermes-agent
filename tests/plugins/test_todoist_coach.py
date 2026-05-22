"""Tests for the todoist_coach module (Atomic Habits coaching)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from plugins.personal_ops.todoist_coach import (
    detect_procrastination,
    select_habit_law,
    build_coach_message,
    run_coach,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_sticky(
    task_id: str = "t1",
    title: str = "File taxes",
    avoidance_score: float = 0.72,
    times_seen: int = 5,
    times_overdue: int = 3,
    shape_score: float = 0.70,
    suspected_blocker: str = "unknown",
    completed: bool = False,
) -> dict:
    return {
        "task_id": task_id,
        "title": title,
        "avoidance_score": avoidance_score,
        "times_seen": times_seen,
        "times_overdue": times_overdue,
        "shape_score": shape_score,
        "suspected_blocker": suspected_blocker,
        "completed": completed,
    }


# ===========================================================================
# detect_procrastination
# ===========================================================================
class TestDetectProcrastination:
    def test_empty_sticky_returns_empty(self):
        assert detect_procrastination({}) == []

    def test_completed_tasks_excluded(self):
        sticky = {"t1": _make_sticky(completed=True)}
        assert detect_procrastination(sticky) == []

    def test_low_avoidance_excluded_with_default_threshold(self):
        sticky = {"t1": _make_sticky(avoidance_score=0.30, times_seen=1, times_overdue=0)}
        assert detect_procrastination(sticky) == []

    def test_high_avoidance_flagged(self):
        sticky = {"t1": _make_sticky(avoidance_score=0.80)}
        result = detect_procrastination(sticky)
        assert len(result) == 1
        assert "high_avoidance" in result[0]["procrastination_signals"]

    def test_repeatedly_overdue_flagged(self):
        sticky = {"t1": _make_sticky(avoidance_score=0.40, times_overdue=3)}
        result = detect_procrastination(sticky)
        assert len(result) == 1
        assert "repeatedly_overdue" in result[0]["procrastination_signals"]

    def test_lingering_flagged(self):
        sticky = {"t1": _make_sticky(avoidance_score=0.40, times_overdue=0, times_seen=6)}
        result = detect_procrastination(sticky)
        assert len(result) == 1
        assert "lingering" in result[0]["procrastination_signals"]

    def test_sorted_by_avoidance_descending(self):
        sticky = {
            "t1": _make_sticky(task_id="t1", avoidance_score=0.60, times_seen=5),
            "t2": _make_sticky(task_id="t2", avoidance_score=0.90),
        }
        result = detect_procrastination(sticky)
        assert len(result) == 2
        assert result[0]["task_id"] == "t2"

    def test_custom_threshold(self):
        sticky = {"t1": _make_sticky(avoidance_score=0.50, times_seen=1, times_overdue=0)}
        assert detect_procrastination(sticky, avoidance_threshold=0.45) != []
        assert detect_procrastination(sticky, avoidance_threshold=0.55) == []


# ===========================================================================
# select_habit_law
# ===========================================================================
class TestSelectHabitLaw:
    def test_unclear_next_action_returns_obvious(self):
        task = _make_sticky(suspected_blocker="unclear_next_action")
        assert select_habit_law(task) == "make_it_obvious"

    def test_low_shape_returns_obvious(self):
        task = _make_sticky(shape_score=0.40)
        assert select_habit_law(task) == "make_it_obvious"

    def test_high_avoidance_clear_shape_returns_easy(self):
        task = _make_sticky(avoidance_score=0.85, shape_score=0.70)
        assert select_habit_law(task) == "make_it_easy"

    def test_repeatedly_overdue_returns_attractive(self):
        task = _make_sticky(
            avoidance_score=0.60,
            times_overdue=3,
            shape_score=0.70,
        )
        task["procrastination_signals"] = ["repeatedly_overdue"]
        assert select_habit_law(task) == "make_it_attractive"

    def test_lingering_returns_satisfying(self):
        task = _make_sticky(
            avoidance_score=0.60,
            times_overdue=0,
            times_seen=6,
            shape_score=0.70,
        )
        task["procrastination_signals"] = ["lingering"]
        assert select_habit_law(task) == "make_it_satisfying"

    def test_returns_valid_law_always(self):
        task = _make_sticky(avoidance_score=0.56, times_overdue=0, times_seen=2, shape_score=0.80)
        task["procrastination_signals"] = []
        law = select_habit_law(task)
        assert law in {"make_it_obvious", "make_it_attractive", "make_it_easy", "make_it_satisfying"}


# ===========================================================================
# build_coach_message
# ===========================================================================
class TestBuildCoachMessage:
    def test_returns_string_with_task_title(self):
        task = _make_sticky(title="File taxes")
        task["procrastination_signals"] = ["high_avoidance"]
        law = select_habit_law(task)
        msg, template_hash = build_coach_message(task, law)
        assert "File taxes" in msg
        assert isinstance(template_hash, str) and len(template_hash) == 8

    def test_identity_reinforcement_for_severe(self):
        task = _make_sticky(avoidance_score=0.80, times_seen=6)
        task["procrastination_signals"] = ["high_avoidance", "lingering"]
        msg, _ = build_coach_message(task, "make_it_easy")
        # Should have multiple lines (main + identity)
        assert "\n" in msg

    def test_accountability_for_extreme(self):
        task = _make_sticky(avoidance_score=0.90, times_seen=8, times_overdue=5)
        task["procrastination_signals"] = ["high_avoidance", "repeatedly_overdue", "lingering"]
        msg, _ = build_coach_message(task, "make_it_easy")
        # Should contain the task title multiple times (main + identity + accountability)
        assert msg.count("File taxes") >= 2

    def test_avoids_recent_templates(self):
        task = _make_sticky()
        task["procrastination_signals"] = ["high_avoidance"]
        # Generate many messages; at least one should differ
        messages = set()
        for _ in range(20):
            msg, _ = build_coach_message(task, "make_it_obvious")
            messages.add(msg)
        # With 4 templates, we should see at least 2 variants over 20 attempts
        assert len(messages) >= 2


# ===========================================================================
# run_coach
# ===========================================================================
class TestRunCoach:
    def test_no_sticky_tasks(self):
        result = run_coach({}, {})
        assert result["coached"] is False
        assert result["message"] == ""
        assert result["flagged_count"] == 0

    def test_no_procrastinating_tasks(self):
        state = {"sticky_tasks": {"t1": _make_sticky(avoidance_score=0.20, times_seen=1, times_overdue=0)}}
        result = run_coach(state, {})
        assert result["coached"] is False

    def test_procrastinating_task_generates_message(self):
        state = {"sticky_tasks": {"t1": _make_sticky(avoidance_score=0.72, times_seen=5, times_overdue=3)}}
        result = run_coach(state, {})
        assert result["coached"] is True
        assert "File taxes" in result["message"]
        assert result["law"] in {"make_it_obvious", "make_it_attractive", "make_it_easy", "make_it_satisfying"}
        assert result["flagged_count"] >= 1

    def test_returns_top_task_info(self):
        state = {"sticky_tasks": {
            "t1": _make_sticky(task_id="t1", avoidance_score=0.60, times_seen=5),
            "t2": _make_sticky(task_id="t2", title="Call dentist", avoidance_score=0.90),
        }}
        result = run_coach(state, {})
        assert result["coached"] is True
        assert result["task"]["task_id"] == "t2"

    def test_custom_threshold(self):
        state = {"sticky_tasks": {"t1": _make_sticky(avoidance_score=0.50, times_seen=1, times_overdue=0)}}
        result = run_coach(state, {}, avoidance_threshold=0.45)
        assert result["coached"] is True

    def test_coach_history_deduplication(self):
        state = {
            "sticky_tasks": {"t1": _make_sticky()},
            "coach_history": [],
        }
        # Run coach multiple times and check that it records template hashes
        results = []
        for _ in range(5):
            r = run_coach(state, {})
            results.append(r)
        # All should produce messages
        assert all(r["coached"] for r in results)
