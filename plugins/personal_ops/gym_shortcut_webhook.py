from __future__ import annotations

import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict
from urllib.parse import parse_qs, urlparse

from .gym_attendance import record_arrival, record_departure, workout_task_for_day


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: Dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _configured_secret() -> str:
    return (os.getenv("HERMES_GYM_SHORTCUT_SECRET") or "").strip()


def _authorized(query: Dict[str, list[str]], client_host: str) -> bool:
    secret = _configured_secret()
    if not secret:
        return client_host in {"127.0.0.1", "::1", "localhost"}
    provided = (query.get("secret") or [""])[0].strip()
    return provided == secret


class GymShortcutHandler(BaseHTTPRequestHandler):
    server_version = "HermesGymShortcutWebhook/1.0"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        client_host = self.client_address[0] if self.client_address else ""

        if parsed.path == "/health":
            _json_response(self, 200, {"ok": True, "service": "gym_shortcut_webhook"})
            return

        if parsed.path not in {"/gym", "/gym/"}:
            _json_response(self, 404, {"ok": False, "error": "not_found"})
            return

        if not _authorized(query, client_host):
            _json_response(self, 401, {"ok": False, "error": "unauthorized"})
            return

        event = (query.get("event") or query.get("action") or [""])[0].strip().lower()
        verified_location = (query.get("verified_location") or query.get("location_verified") or [""])[0]
        if event in {"arrived", "arrive", "in", "checkin", "check-in"}:
            message = record_arrival(source="ios-shortcut-url", location_verified=verified_location)
        elif event in {"left", "leave", "out", "checkout", "check-out"}:
            message = record_departure(source="ios-shortcut-url", location_verified=verified_location)
        else:
            _json_response(self, 400, {"ok": False, "error": "invalid_event", "allowed": ["arrived", "left"]})
            return

        logged = "not logged" not in message.lower()
        task = workout_task_for_day() if logged else None
        if task:
            name, url = task
            task_id = url.split("id=")[-1] if "id=" in url else url
            task_payload = {
                "name": name,
                "url": url,
                "app_url": f"todoist://task?id={task_id}"
            }
        else:
            task_payload = None
        _json_response(self, 200, {"ok": True, "event": event, "logged": logged, "message": message, "workout_task": task_payload})


def serve(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> None:
    httpd = ThreadingHTTPServer((host, port), GymShortcutHandler)
    print(f"Hermes gym shortcut webhook listening on http://{host}:{port}")
    httpd.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description="Hermes gym shortcut webhook for iOS Shortcuts URL automations.")
    parser.add_argument("--host", default=os.getenv("HERMES_GYM_SHORTCUT_HOST", DEFAULT_HOST))
    parser.add_argument("--port", type=int, default=int(os.getenv("HERMES_GYM_SHORTCUT_PORT", str(DEFAULT_PORT))))
    args = parser.parse_args()
    serve(args.host, args.port)


if __name__ == "__main__":
    main()
