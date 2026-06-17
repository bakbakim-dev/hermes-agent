from __future__ import annotations

import importlib
import asyncio
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


def test_long_gym_departure_asks_before_completing_todoist(monkeypatch, tmp_path):
    personal_ops = _module(monkeypatch, tmp_path)
    sent = []
    completed = []
    monkeypatch.setattr(personal_ops, "_safe_send_telegram_message", lambda text, **kw: sent.append((text, kw)) or {"ok": True})
    monkeypatch.setattr(personal_ops, "_execute_todoist", lambda payload: completed.append(payload) or {"success": True})

    personal_ops._runtime_event_ingest(
        {
            "event_type": "gym.arrived",
            "source": "ios-shortcut-url",
            "payload": {"when": "2026-06-16T18:00:00-06:00"},
        }
    )
    leave = personal_ops._runtime_event_ingest(
        {
            "event_type": "gym.left",
            "source": "ios-shortcut-url",
            "payload": {"when": "2026-06-16T22:00:00-06:00"},
        }
    )

    assert leave["handled"] is True
    assert "Session length: 240 min" in leave["message"]
    assert "Automatically completed Todoist task" not in leave["message"]
    assert "confirm" in leave["message"].lower()
    assert completed == []
    assert sent
    assert any((button.get("callback_data") or "").startswith("po:gym:complete:") for button in sent[-1][1].get("buttons", []))


def test_gym_complete_callback_closes_task_after_confirmation(monkeypatch, tmp_path):
    personal_ops = _module(monkeypatch, tmp_path)
    posts = []

    class FakeResponse:
        def raise_for_status(self):
            return None

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, headers=None, json=None):
            posts.append((url, headers, json))
            return FakeResponse()

    class FakeChat:
        id = "chat-1"

    class FakeMessage:
        text = "Confirm this workout?"
        message_id = "msg-1"
        chat = FakeChat()

    class FakeUser:
        id = "user-1"

    class FakeQuery:
        message = FakeMessage()
        from_user = FakeUser()

        def __init__(self):
            self.answers = []
            self.edits = []

        async def answer(self, text="", **kwargs):
            self.answers.append(text)

        async def edit_message_text(self, text, **kwargs):
            self.edits.append((text, kwargs))

    monkeypatch.setattr(personal_ops, "_http_client", lambda: FakeClient())
    monkeypatch.setattr(personal_ops, "_todoist_headers", lambda: {"Authorization": "Bearer test"})

    query = FakeQuery()
    asyncio.run(personal_ops._handle_telegram_callback(None, query, "po:gym:complete:task-123"))

    assert posts == [(f"{personal_ops.TODOIST_BASE}/tasks/task-123/close", {"Authorization": "Bearer test"}, None)]
    assert any("confirmed" in answer.lower() for answer in query.answers)
    assert query.edits
    assert "Todoist task completed" in query.edits[-1][0]
