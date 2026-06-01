"""Hermes Telegram Live Card (Disabled).

This module is disabled to keep the Telegram chat interface purely conversational.
System metrics are routed to the Web Dashboard.
"""
from __future__ import annotations
import os
import json
from pathlib import Path
from typing import Any, Dict, Tuple
import httpx

HERMES_HOME = Path(os.getenv("HERMES_HOME", str(Path.home() / ".hermes")))
STATE_PATH = HERMES_HOME / "live_card_state.json"

def _env_file() -> Dict[str, str]:
    values: Dict[str, str] = {}
    env_path = HERMES_HOME / ".env"
    if env_path.exists():
        for raw in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values

def _telegram_config() -> Tuple[str, str]:
    env = _env_file()
    token = os.getenv("TELEGRAM_BOT_TOKEN") or env.get("TELEGRAM_BOT_TOKEN") or env.get("HERMES_TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID") or env.get("TELEGRAM_CHAT_ID") or env.get("HERMES_TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be configured")
    return token, chat_id

def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default

def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

def _post(method: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    token, _ = _telegram_config()
    with httpx.Client(timeout=30) as client:
        response = client.post(f"https://api.telegram.org/bot{token}/{method}", json=payload)
        response.raise_for_status()
        return response.json() or {"ok": True}

def update_live_card(*, pin: bool = False) -> Dict[str, Any]:
    state = _read_json(STATE_PATH, {})
    message_id = state.get("message_id")
    if message_id:
        try:
            _, chat_id = _telegram_config()
            _post("deleteMessage", {"chat_id": chat_id, "message_id": int(message_id)})
            print(f"Deleted old Telegram Live Card message ID: {message_id}")
        except Exception as e:
            print(f"Failed to delete old Live Card message: {e}")

    if state:
        state["message_id"] = None
        _write_json(STATE_PATH, state)
    return {}

if __name__ == "__main__":
    update_live_card()
