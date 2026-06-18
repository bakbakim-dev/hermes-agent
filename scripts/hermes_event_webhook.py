from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO_ROOT = Path(os.getenv("HERMES_REPO_ROOT", "/home/ubuntu/hermes-agent"))
if REPO_ROOT.exists():
    sys.path.insert(0, str(REPO_ROOT))

from plugins.personal_ops import temp_personal_ops_tools as tools
from plugins.personal_ops.event_ingress_guard import guard_unverified_event


def _env(name: str, default: str = "") -> str:
    value = os.getenv(name, "").strip()
    if value:
        return value
    env_path = Path(os.getenv("HERMES_HOME", str(Path.home() / ".hermes"))) / ".env"
    try:
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            if not raw or raw.lstrip().startswith("#") or "=" not in raw:
                continue
            key, val = raw.split("=", 1)
            if key.strip() == name:
                return val.strip().strip('"').strip("'")
    except Exception:
        pass
    return default


class HermesEventHandler(BaseHTTPRequestHandler):
    server_version = "HermesEventWebhook/1.1"

    def _write_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _is_authorized(self) -> bool:
        token = _env("HERMES_EVENT_WEBHOOK_TOKEN")
        if not token:
            return True
        auth = self.headers.get("Authorization", "").strip()
        if auth == f"Bearer {token}":
            return True
        return self.headers.get("X-Hermes-Token", "").strip() == token

    def do_GET(self) -> None:  # noqa: N802
        if self.path.rstrip("/") == "/health":
            self._write_json(200, {"ok": True, "service": "hermes-event-webhook"})
            return
        self._write_json(404, {"ok": False, "error": "not_found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path.rstrip("/") != "/event":
            self._write_json(404, {"ok": False, "error": "not_found"})
            return
        if not self._is_authorized():
            self._write_json(401, {"ok": False, "error": "unauthorized"})
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._write_json(400, {"ok": False, "error": "invalid_content_length"})
            return
        try:
            raw = self.rfile.read(content_length or 0)
            payload = json.loads(raw.decode("utf-8") or "{}")
            if not isinstance(payload, dict):
                raise ValueError("JSON body must be an object")
        except Exception as exc:
            self._write_json(400, {"ok": False, "error": f"invalid_json: {exc}"})
            return

        payload["action"] = "event_ingest"
        guarded = guard_unverified_event(payload)
        if guarded is not None:
            self._write_json(200, guarded)
            return

        try:
            result = json.loads(tools.handle_runtime(payload))
        except Exception as exc:
            self._write_json(500, {"ok": False, "error": f"runtime_failed: {exc}"})
            return
        status = 200 if result.get("success") else 400
        self._write_json(status, result)

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        print(fmt % args, flush=True)


def main() -> None:
    host = _env("HERMES_EVENT_WEBHOOK_HOST", "127.0.0.1")
    port = int(_env("HERMES_EVENT_WEBHOOK_PORT", "8787"))
    server = ThreadingHTTPServer((host, port), HermesEventHandler)
    print(json.dumps({"ok": True, "service": "hermes-event-webhook", "host": host, "port": port}), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
