"""Tests for the enhanced Desktop Sentinel (lock detection, category fallback)."""
from __future__ import annotations
import sys
import time
from unittest.mock import MagicMock, patch

import pytest

from plugins.personal_ops.desktop_sentinel import DesktopSentinel


class TestClassifyTitle:
    def test_focus_work_keyword(self):
        s = DesktopSentinel()
        assert s.classify_title("main.py — VSCode", "Code.exe") == "focus_work"

    def test_todoist_keyword(self):
        s = DesktopSentinel()
        assert s.classify_title("Todoist: Today", "chrome.exe") == "todoist_planning"

    def test_communication_keyword(self):
        s = DesktopSentinel()
        assert s.classify_title("General — Slack", "Slack.exe") == "communication"

    def test_distraction_video(self):
        s = DesktopSentinel()
        assert s.classify_title("Funny Cat Video - YouTube", "chrome.exe") == "distraction_video"

    def test_distraction_social(self):
        s = DesktopSentinel()
        assert s.classify_title("Home — Reddit", "chrome.exe") == "distraction_social"

    def test_research_keyword(self):
        s = DesktopSentinel()
        assert s.classify_title("Python docs — MDN", "firefox.exe") == "research"

    def test_work_admin_keyword(self):
        s = DesktopSentinel()
        assert s.classify_title("Budget.xlsx — Excel", "EXCEL.EXE") == "work_admin"

    def test_fallback_communication_via_app(self):
        s = DesktopSentinel()
        assert s.classify_title("Some random window", "Skype.exe") == "communication"

    def test_fallback_distraction_via_app(self):
        s = DesktopSentinel()
        assert s.classify_title("Now Playing...", "Spotify.exe") == "distraction_video"

    def test_default_fallback_is_work_admin(self):
        s = DesktopSentinel()
        # Completely unknown app and title
        assert s.classify_title("Random Unknown App", "mystery.exe") == "work_admin"


class TestIsLocked:
    @pytest.mark.skipif(sys.platform != "win32", reason="Win32-only API")
    def test_is_locked_returns_bool(self):
        s = DesktopSentinel()
        result = s.is_locked()
        assert isinstance(result, bool)

    @pytest.mark.skipif(sys.platform == "win32", reason="Non-Win32 always returns False")
    def test_non_windows_always_unlocked(self):
        s = DesktopSentinel()
        assert s.is_locked() is False


class TestRunCycleLockTransitions:
    """Test that lock/unlock transitions dispatch the correct events."""

    def test_lock_transition_dispatches_event(self):
        s = DesktopSentinel()
        s.window_bucket = "aw-watcher-window_test"
        s.afk_bucket = "aw-watcher-afk_test"
        s.last_locked = False
        s.last_cycle_time = time.time()

        events_sent = []
        s.send_event = lambda et, payload, **kw: events_sent.append((et, payload))
        s.get_latest_event = lambda _: {"data": {"status": "not-afk", "title": "test", "app": "test"}}
        s.is_locked = lambda: True  # Simulate OS locked

        s.run_cycle()

        event_types = [e[0] for e in events_sent]
        assert "desktop.lock" in event_types
        assert s.last_locked is True

    def test_unlock_transition_dispatches_event(self):
        s = DesktopSentinel()
        s.window_bucket = "aw-watcher-window_test"
        s.afk_bucket = "aw-watcher-afk_test"
        s.last_locked = True
        s.last_cycle_time = time.time()

        events_sent = []
        s.send_event = lambda et, payload, **kw: events_sent.append((et, payload))
        s.get_latest_event = lambda _: {"data": {"status": "not-afk", "title": "test", "app": "test"}}
        s.is_locked = lambda: False  # Simulate OS unlocked

        s.run_cycle()

        event_types = [e[0] for e in events_sent]
        assert "desktop.unlock" in event_types
        assert s.last_locked is False


class TestWakeDetection:
    def test_large_gap_dispatches_wake_event(self):
        s = DesktopSentinel()
        s.window_bucket = "aw-watcher-window_test"
        s.afk_bucket = "aw-watcher-afk_test"
        s.last_locked = False
        # Simulate a 2-minute gap (system was asleep)
        s.last_cycle_time = time.time() - 120

        events_sent = []
        s.send_event = lambda et, payload, **kw: events_sent.append((et, payload))
        s.get_latest_event = lambda _: {"data": {"status": "not-afk", "title": "test", "app": "test"}}
        s.is_locked = lambda: False

        s.run_cycle()

        event_types = [e[0] for e in events_sent]
        assert "desktop.wake" in event_types
        wake_payload = next(p for et, p in events_sent if et == "desktop.wake")
        assert wake_payload["gap_sec"] >= 100
