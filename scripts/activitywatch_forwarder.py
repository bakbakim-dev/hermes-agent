from __future__ import annotations

import json
import socket
import time
from pathlib import Path
from typing import Any, Dict, Optional

import httpx


HOME = Path.home()
CONFIG_PATH = HOME / ".hermes" / "activitywatch_forwarder.json"
STATE_PATH = HOME / ".hermes" / "activitywatch_forwarder_state.json"
DEFAULT_ACTIVITYWATCH_BASE = "http://127.0.0.1:5600"


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _load_config() -> Dict[str, Any]:
    data = _read_json(CONFIG_PATH, {})
    return data if isinstance(data, dict) else {}


def _http_client() -> httpx.Client:
    return httpx.Client(timeout=5.0, follow_redirects=True)


def _get_bucket_ids(base_url: str) -> tuple[Optional[str], Optional[str]]:
    with _http_client() as client:
        resp = client.get(f"{base_url.rstrip('/')}/api/0/buckets/")
        resp.raise_for_status()
        buckets = resp.json() or {}
    afk_id = None
    window_id = None
    for bucket_id in buckets.keys():
        if not afk_id and str(bucket_id).startswith("aw-watcher-afk_"):
            afk_id = str(bucket_id)
        if not window_id and str(bucket_id).startswith("aw-watcher-window_"):
            window_id = str(bucket_id)
    return afk_id, window_id


def _latest_event(base_url: str, bucket_id: str) -> Dict[str, Any]:
    with _http_client() as client:
        resp = client.get(f"{base_url.rstrip('/')}/api/0/buckets/{bucket_id}/events", params={"limit": 1})
        resp.raise_for_status()
        events = resp.json() or []
    return dict(events[0] or {}) if events else {}


def _classify_category(app_name: str, title: str) -> str:
    lowered_app = app_name.lower()
    lowered_title = title.lower()
    if "todoist" in lowered_app or "todoist" in lowered_title:
        return "todoist"
    if any(token in lowered_app for token in ["chrome", "edge", "firefox", "browser"]):
        return "browser"
    if any(token in lowered_app for token in ["code", "cursor", "studio", "pycharm", "idea"]):
        return "editor"
    if any(token in lowered_app for token in ["telegram", "slack", "discord", "signal"]):
        return "messaging"
    return "unknown"


def _build_presence_signal(base_url: str) -> Dict[str, Any]:
    afk_id, window_id = _get_bucket_ids(base_url)
    if not afk_id or not window_id:
        raise RuntimeError("Required ActivityWatch buckets were not found.")
    afk = _latest_event(base_url, afk_id)
    window = _latest_event(base_url, window_id)
    afk_data = dict(afk.get("data") or {})
    window_data = dict(window.get("data") or {})
    status = str(afk_data.get("status") or "").strip().lower()
    active = status == "not-afk"
    app_name = str(window_data.get("app") or "").strip()
    title = str(window_data.get("title") or "").strip()
    category = _classify_category(app_name, title)
    timestamp = str(afk.get("timestamp") or "")
    age_seconds = 0
    if timestamp:
        try:
            import datetime as _dt

            parsed = _dt.datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=_dt.timezone.utc)
            age_seconds = max(int((_dt.datetime.now(_dt.timezone.utc) - parsed).total_seconds()), 0)
        except Exception:
            age_seconds = 0
    return {
        "confidence": 0.83 if active else 0.15,
        "label": "ActivityWatch active_now" if active else "ActivityWatch idle",
        "active": active,
        "active_category": category,
        "last_activity_age_seconds": age_seconds,
        "hostname": socket.gethostname(),
    }


def _should_send(signal: Dict[str, Any]) -> bool:
    state = _read_json(STATE_PATH, {})
    if not isinstance(state, dict):
        return True
    previous = dict(state.get("last_signal") or {})
    if not previous:
        return True
    now_ts = int(time.time())
    last_sent = int(state.get("last_sent_unix") or 0)
    if now_ts - last_sent >= 55:
        return True
    keys = ["active", "active_category", "confidence", "label"]
    return any(previous.get(key) != signal.get(key) for key in keys)


def _post_heartbeat(webhook_url: str, webhook_token: str, signal: Dict[str, Any]) -> Dict[str, Any]:
    payload = {
        "event_type": "activitywatch_heartbeat",
        "source": "activitywatch-forwarder",
        "presence_signal": signal,
    }
    headers = {"Authorization": f"Bearer {webhook_token}"}
    with _http_client() as client:
        resp = client.post(webhook_url, headers=headers, json=payload)
        resp.raise_for_status()
        return resp.json()


def _record_unavailable(reason: str) -> None:
    now_ts = int(time.time())
    state = _read_json(STATE_PATH, {})
    if not isinstance(state, dict):
        state = {}
    previous = dict(state.get("activitywatch_unavailable") or {})
    last_logged = int(previous.get("last_logged_unix") or 0)
    payload = {
        "ok": True,
        "posted": False,
        "activitywatch_available": False,
        "reason": reason,
    }
    state["activitywatch_unavailable"] = {
        "last_seen_unix": now_ts,
        "last_logged_unix": now_ts if now_ts - last_logged >= 300 else last_logged,
        "reason": reason,
    }
    state["last_signal"] = None
    state["last_result"] = None
    _write_json(STATE_PATH, state)
    if now_ts - last_logged >= 300:
        print(json.dumps(payload))


def main() -> None:
    cfg = _load_config()
    base_url = str(cfg.get("activitywatch_base_url") or DEFAULT_ACTIVITYWATCH_BASE).strip()
    webhook_url = str(cfg.get("hermes_webhook_url") or "").strip()
    webhook_token = str(cfg.get("hermes_webhook_token") or "").strip()
    if not webhook_url or not webhook_token:
        raise SystemExit("Missing hermes_webhook_url or hermes_webhook_token in ~/.hermes/activitywatch_forwarder.json")
    try:
        signal = _build_presence_signal(base_url)
    except (httpx.HTTPError, RuntimeError, OSError) as exc:
        _record_unavailable(f"ActivityWatch unavailable at {base_url}: {exc}")
        return
    if not _should_send(signal):
        print(json.dumps({"ok": True, "skipped": True, "reason": "recent_duplicate", "signal": signal}))
        return
    result = _post_heartbeat(webhook_url, webhook_token, signal)
    _write_json(
        STATE_PATH,
        {
            "last_sent_unix": int(time.time()),
            "last_signal": signal,
            "last_result": result,
            "activitywatch_unavailable": None,
        },
    )
    print(json.dumps({"ok": True, "posted": True, "signal": signal, "result": result}))


if __name__ == "__main__":
    main()
