from __future__ import annotations

import importlib
from datetime import datetime
from pathlib import Path


def _module(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    monkeypatch.setenv("HERMES_TIMEZONE", "America/Edmonton")
    import plugins.personal_ops.temp_personal_ops_tools as personal_ops

    return importlib.reload(personal_ops)


def test_runtime_event_ingest_handles_gym_arrival_and_departure(monkeypatch, tmp_path):
    personal_ops = _module(monkeypatch, tmp_path)

    arrive = personal_ops._runtime_event_ingest(
        {
            "event_type": "gym.arrived",
            "source": "ios-shortcut-url",
            "payload": {"when": "2026-05-22T18:00:00-06:00"},
        }
    )
    leave = personal_ops._runtime_event_ingest(
        {
            "event_type": "gym.left",
            "source": "ios-shortcut-url",
            "payload": {"when": "2026-05-22T19:15:00-06:00"},
        }
    )

    assert arrive["handled"] is True
    assert arrive["event_type"] == "gym.arrived"
    assert "Logged gym arrival" in arrive["message"]
    assert leave["handled"] is True
    assert leave["event_type"] == "gym.left"
    assert "Logged gym departure" in leave["message"]
    assert (tmp_path / ".hermes" / "personal_ops" / "gym_attendance.jsonl").exists()
