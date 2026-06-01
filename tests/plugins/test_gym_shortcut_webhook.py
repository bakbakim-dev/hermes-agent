from __future__ import annotations

import importlib
import json
import socket
import threading
import urllib.error
import urllib.request
from pathlib import Path


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _start_server(monkeypatch, tmp_path: Path, secret: str = "test-secret"):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / ".hermes"))
    monkeypatch.setenv("HERMES_GYM_SHORTCUT_SECRET", secret)
    import plugins.personal_ops.gym_shortcut_webhook as webhook

    webhook = importlib.reload(webhook)
    port = _free_port()
    server = webhook.ThreadingHTTPServer(("127.0.0.1", port), webhook.GymShortcutHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port


def test_gym_shortcut_webhook_logs_arrival(monkeypatch, tmp_path):
    import plugins.personal_ops.gym_attendance as gym_attendance
    monkeypatch.setattr(gym_attendance, "workout_task_for_day", lambda *a: ("Upper A", "https://app.todoist.com/app/task/123"))
    server, port = _start_server(monkeypatch, tmp_path)
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/gym?event=arrived&secret=test-secret",
            timeout=5,
        ) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    finally:
        server.shutdown()

    assert payload["ok"] is True
    assert payload["event"] == "arrived"
    assert "Logged gym arrival" in payload["message"]
    assert payload["workout_task"]["url"].startswith("https://app.todoist.com/app/task/")


def test_gym_shortcut_webhook_logs_departure(monkeypatch, tmp_path):
    server, port = _start_server(monkeypatch, tmp_path)
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/gym?event=left&secret=test-secret",
            timeout=5,
        ) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    finally:
        server.shutdown()

    assert payload["ok"] is True
    assert payload["event"] == "left"
    assert "Logged gym departure" in payload["message"]


def test_gym_shortcut_webhook_rejects_bad_secret(monkeypatch, tmp_path):
    server, port = _start_server(monkeypatch, tmp_path)
    try:
        try:
            urllib.request.urlopen(
                f"http://127.0.0.1:{port}/gym?event=arrived&secret=wrong",
                timeout=5,
            )
            assert False, "expected HTTP 401"
        except urllib.error.HTTPError as exc:
            assert exc.code == 401
    finally:
        server.shutdown()
