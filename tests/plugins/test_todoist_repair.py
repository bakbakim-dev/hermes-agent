"""Tests for the Todoist repair queue heuristics."""
from __future__ import annotations

import pytest
from plugins.personal_ops.todoist_repair import (
    detect_duplicate_routines,
    detect_junk_drawer,
    detect_vague_tasks,
    format_repair_summary,
    run_full_repair_scan,
)


# ---------------------------------------------------------------------------
# Duplicate routine detection
# ---------------------------------------------------------------------------
class TestDuplicateRoutines:
    def test_no_duplicates(self):
        tasks = [
            {"id": "1", "content": "Morning Launch", "due": {"date": "2026-05-21"}},
            {"id": "2", "content": "Evening Reset", "due": {"date": "2026-05-21"}},
        ]
        assert detect_duplicate_routines(tasks) == []

    def test_detects_exact_duplicates(self):
        tasks = [
            {"id": "1", "content": "Morning Launch", "due": {"date": "2026-05-21"}},
            {"id": "2", "content": "Morning Launch", "due": {"date": "2026-05-22"}},
        ]
        results = detect_duplicate_routines(tasks)
        assert len(results) == 1
        assert results[0]["type"] == "duplicate_routine"
        assert len(results[0]["tasks"]) == 2

    def test_detects_fuzzy_duplicates_with_emoji(self):
        tasks = [
            {"id": "1", "content": "☀️ Morning Launch", "due": {"date": "2026-05-21"}},
            {"id": "2", "content": "Morning Launch", "due": {"date": "2026-05-21"}},
        ]
        results = detect_duplicate_routines(tasks)
        assert len(results) == 1

    def test_ignores_completed_tasks(self):
        tasks = [
            {"id": "1", "content": "Morning Launch", "completed": True},
            {"id": "2", "content": "Morning Launch"},
        ]
        assert detect_duplicate_routines(tasks) == []


# ---------------------------------------------------------------------------
# Vague title detection
# ---------------------------------------------------------------------------
class TestVagueTasks:
    def test_flags_vague_starts(self):
        tasks = [
            {"id": "1", "content": "Check stuff"},
            {"id": "2", "content": "Do things later"},
        ]
        results = detect_vague_tasks(tasks)
        assert len(results) == 2
        assert all(r["type"] == "vague_title" for r in results)

    def test_flags_placeholder_titles(self):
        tasks = [
            {"id": "1", "content": "test"},
            {"id": "2", "content": "asdf"},
            {"id": "3", "content": "tbd"},
        ]
        results = detect_vague_tasks(tasks)
        assert len(results) == 3

    def test_does_not_flag_actionable_tasks(self):
        tasks = [
            {"id": "1", "content": "Call dentist at 3pm"},
            {"id": "2", "content": "Email Alice the Q2 report"},
            {"id": "3", "content": "Buy groceries for dinner"},
        ]
        results = detect_vague_tasks(tasks)
        assert len(results) == 0

    def test_override_protects_actionable(self):
        # "Check" is vague, but "Call" overrides
        tasks = [
            {"id": "1", "content": "Call the plumber before 5"},
        ]
        results = detect_vague_tasks(tasks)
        assert len(results) == 0

    def test_very_short_title_flagged(self):
        tasks = [{"id": "1", "content": "hi"}]
        results = detect_vague_tasks(tasks)
        assert len(results) == 1


# ---------------------------------------------------------------------------
# Junk-drawer detection
# ---------------------------------------------------------------------------
class TestJunkDrawer:
    def test_flags_inbox_no_due_low_priority(self):
        tasks = [
            {"id": "1", "content": "Random idea", "project_id": "inbox123", "priority": 1},
        ]
        results = detect_junk_drawer(tasks, inbox_project_id="inbox123")
        assert len(results) == 1
        assert results[0]["type"] == "junk_drawer"

    def test_skips_tasks_with_due_dates(self):
        tasks = [
            {
                "id": "1",
                "content": "Random idea",
                "project_id": "inbox123",
                "priority": 1,
                "due": {"date": "2026-05-22"},
            },
        ]
        results = detect_junk_drawer(tasks, inbox_project_id="inbox123")
        assert len(results) == 0

    def test_skips_high_priority(self):
        tasks = [
            {"id": "1", "content": "Important thing", "project_id": "inbox123", "priority": 4},
        ]
        results = detect_junk_drawer(tasks, inbox_project_id="inbox123")
        assert len(results) == 0

    def test_calculates_age(self):
        tasks = [
            {
                "id": "1",
                "content": "Old task",
                "project_id": "inbox123",
                "priority": 1,
                "created_at": "2026-01-01T00:00:00Z",
            },
        ]
        results = detect_junk_drawer(tasks, inbox_project_id="inbox123")
        assert len(results) == 1
        assert results[0]["age_days"] > 100


# ---------------------------------------------------------------------------
# Integration: full scan + format
# ---------------------------------------------------------------------------
class TestFullScan:
    def test_combined_scan_returns_all_categories(self):
        tasks = [
            {"id": "1", "content": "Morning Launch", "due": {"date": "2026-05-21"}},
            {"id": "2", "content": "Morning Launch", "due": {"date": "2026-05-22"}},
            {"id": "3", "content": "Do stuff later"},
            {"id": "4", "content": "Random note", "project_id": "inbox", "priority": 1},
        ]
        results = run_full_repair_scan(tasks, inbox_project_id="inbox")
        assert len(results["duplicates"]) == 1
        assert len(results["vague"]) >= 1
        assert len(results["junk_drawer"]) >= 1

    def test_format_summary_clean(self):
        proposals = {"duplicates": [], "vague": [], "junk_drawer": []}
        summary = format_repair_summary(proposals)
        assert "No issues found" in summary

    def test_format_summary_with_issues(self):
        tasks = [
            {"id": "1", "content": "Morning Launch", "due": {"date": "2026-05-21"}},
            {"id": "2", "content": "Morning Launch", "due": {"date": "2026-05-22"}},
        ]
        proposals = run_full_repair_scan(tasks)
        summary = format_repair_summary(proposals)
        assert "Duplicate Routines" in summary
        assert "Morning Launch" in summary
