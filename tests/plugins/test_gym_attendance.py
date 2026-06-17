from __future__ import annotations

import importlib
from datetime import datetime
from pathlib import Path


def _module(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    monkeypatch.setenv("HERMES_TIMEZONE", "America/Edmonton")
    import plugins.personal_ops.gym_attendance as gym

    return importlib.reload(gym)


def test_gym_arrival_and_departure_create_complete_session(monkeypatch, tmp_path):
    gym = _module(monkeypatch, tmp_path)

    arrive = datetime.fromisoformat("2026-05-22T18:00:00-06:00")
    leave = datetime.fromisoformat("2026-05-22T19:15:00-06:00")

    arrival_msg = gym.record_arrival(source="test", when=arrive)
    assert "Logged gym arrival" in arrival_msg
    assert "Lower B workout (Friday)" in arrival_msg
    assert "app.todoist.com/app/task" in arrival_msg
    msg = gym.record_departure(source="test", when=leave)

    assert "Logged gym departure" in msg
    assert "Session length: 75 min" in msg
    sessions = gym.build_sessions()
    assert len(sessions) == 1
    assert sessions[0].duration.total_seconds() == 75 * 60


def test_ios_shortcut_gym_events_require_location_verification(monkeypatch, tmp_path):
    gym = _module(monkeypatch, tmp_path)

    arrive = datetime.fromisoformat("2026-06-16T18:00:00-06:00")
    leave = datetime.fromisoformat("2026-06-16T22:00:00-06:00")

    arrival_msg = gym.record_arrival(source="ios-shortcut", when=arrive)
    departure_msg = gym.record_departure(source="ios-shortcut", when=leave)

    assert "not logged" in arrival_msg.lower()
    assert "verified_location=1" in arrival_msg
    assert "not logged" in departure_msg.lower()
    assert gym.build_sessions() == []

    verified_msg = gym.record_arrival(source="ios-shortcut", when=arrive, location_verified=True)
    assert "Logged gym arrival" in verified_msg
    assert len(gym.build_sessions()) == 1


def test_monthly_report_summarizes_sessions(monkeypatch, tmp_path):
    gym = _module(monkeypatch, tmp_path)

    gym.record_arrival(source="test", when=datetime.fromisoformat("2026-05-04T18:00:00-06:00"))
    gym.record_departure(source="test", when=datetime.fromisoformat("2026-05-04T19:00:00-06:00"))
    gym.record_arrival(source="test", when=datetime.fromisoformat("2026-05-08T18:10:00-06:00"))
    gym.record_departure(source="test", when=datetime.fromisoformat("2026-05-08T19:40:00-06:00"))

    report = gym.monthly_report(year=2026, month=5)

    assert "Gym monthly report - May 2026" in report
    assert "Sessions logged: 2 complete" in report
    assert "Gym days: 2" in report
    assert "Total time: 2h 30m" in report
    assert "Average session: 1h 15m" in report


def test_gym_slash_command_shortcuts(monkeypatch, tmp_path):
    gym = _module(monkeypatch, tmp_path)

    msg = gym.handle_gym_slash_command("shortcuts")

    assert "event=arrived" in msg
    assert "event=left" in msg
    assert "/gym report" in msg
    assert "11501 Buffalo Run Blvd" in msg
    assert "Upper A" in msg


def test_workout_task_for_day(monkeypatch, tmp_path):
    gym = _module(monkeypatch, tmp_path)

    monday = datetime.fromisoformat("2026-05-25T18:00:00-06:00")
    wednesday = datetime.fromisoformat("2026-05-27T18:00:00-06:00")

    assert gym.workout_task_for_day(monday)[0] == "Upper A workout (Monday)"
    assert gym.workout_task_for_day(wednesday) is None
