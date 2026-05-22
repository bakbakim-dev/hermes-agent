"""Hermes Telegram Live Card.

Formats and maintains the pinned status dashboard in Telegram.
Sends push warnings for prolonged distraction.
"""
from __future__ import annotations
import os
import sys
import json
import time
import sqlite3
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime

HERMES_HOME = Path(os.getenv("HERMES_HOME", str(Path.home() / ".hermes")))
PRESENCE_STATE_PATH = HERMES_HOME / "presence_state.json"
OPERATOR_STATE_PATH = HERMES_HOME / "operator_state.json"
DB_PATH = HERMES_HOME / "personal_ops" / "event_log.db"

def _env(name: str, default: str = "") -> str:
    val = os.getenv(name)
    if val:
        return val.strip()
    env_path = HERMES_HOME / ".env"
    if env_path.exists():
        try:
            for line in env_path.read_text(encoding="utf-8").splitlines():
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.split("=", 1)
                    if k.strip() == name:
                        return v.strip()
        except Exception:
            pass
    return default

def get_telegram_config() -> tuple[str, str]:
    bot_token = _env("TELEGRAM_BOT_TOKEN")
    chat_id = _env("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id:
        raise ValueError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be configured")
    return bot_token, chat_id

def telegram_post(method: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    bot_token, _ = get_telegram_config()
    url = f"https://api.telegram.org/bot{bot_token}/{method}"
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))

def get_state_meta(key: str, default: Any = None) -> Any:
    if not DB_PATH.exists():
        return default
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT val FROM state_meta WHERE key = ?", (key,))
        row = cur.fetchone()
        conn.close()
        if row:
            return json.loads(row[0])
    except Exception:
        pass
    return default

def set_state_meta(key: str, val: Any) -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS state_meta (
                key TEXT PRIMARY KEY,
                val TEXT NOT NULL
            )
            """
        )
        cur.execute(
            "INSERT INTO state_meta (key, val) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET val=excluded.val",
            (key, json.dumps(val)),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error setting state meta: {e}", file=sys.stderr)

def generate_live_card_markdown() -> str:
    try:
        presence = json.loads(PRESENCE_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        presence = {}
        
    try:
        operator = json.loads(OPERATOR_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        operator = {}

    presence_val = presence.get("state", "unknown").upper()
    confidence = presence.get("confidence", 1.0)
    afk = presence.get("afk", False)
    locked = presence.get("locked", False)
    
    status_str = presence_val
    if locked:
        status_str += " (LOCKED)"
    elif afk:
        status_str += " (AFK)"
    else:
        status_str += " (ACTIVE)"

    attention = operator.get("attention", {})
    attention_category = attention.get("category", "unknown")
    last_updated_at = attention.get("last_updated_at", time.time())
    attention_duration = int((time.time() - last_updated_at) // 60)
    
    day_phase = operator.get("day_phase", "unknown").upper().replace("_", " ")

    queue = operator.get("initiative_queue", [])
    recommendation = "No actions scheduled."
    if queue:
        allowed_tasks = [t for t in queue if t.get("allowed")]
        if allowed_tasks:
            top_task = allowed_tasks[0]
            recommendation = f"*{top_task.get('content')}* (Score: {top_task.get('score', 0):.1f})"
        else:
            recommendation = "All tasks deferred due to quiet hours / boundaries."

    last_updated_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    markdown = (
        f"📋 *Hermes Live Status Dashboard*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🟢 *Presence:* {status_str} (Confidence: {confidence:.0%})\n"
        f"🎯 *Attention:* {attention_category} (for {attention_duration} min)\n"
        f"📅 *Day Phase:* {day_phase}\n"
        f"💡 *Initiative:* {recommendation}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"_Last Updated: {last_updated_time}_"
    )
    return markdown

def update_live_card(force_new: bool = False) -> None:
    try:
        bot_token, chat_id = get_telegram_config()
    except Exception as e:
        print(f"Telegram config not available: {e}", file=sys.stderr)
        return
        
    markdown = generate_live_card_markdown()
    msg_id = get_state_meta("live_card_message_id")
    
    success = False
    if msg_id and not force_new:
        try:
            payload = {
                "chat_id": chat_id,
                "message_id": msg_id,
                "text": markdown,
                "parse_mode": "Markdown"
            }
            res = telegram_post("editMessageText", payload)
            if res.get("ok"):
                success = True
        except Exception:
            pass

    if not success:
        try:
            payload = {
                "chat_id": chat_id,
                "text": markdown,
                "parse_mode": "Markdown",
                "disable_notification": True
            }
            res = telegram_post("sendMessage", payload)
            if res.get("ok"):
                new_msg_id = res["result"]["message_id"]
                set_state_meta("live_card_message_id", new_msg_id)
                print(f"Created new Live Card message with ID {new_msg_id}")
        except Exception as e:
            print(f"Failed to create Live Card message: {e}", file=sys.stderr)

    check_distraction_alerts()

def check_distraction_alerts() -> None:
    try:
        operator = json.loads(OPERATOR_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return

    attention = operator.get("attention", {})
    attention_category = attention.get("category", "unknown")
    last_updated_at = attention.get("last_updated_at", time.time())
    attention_duration = int((time.time() - last_updated_at) // 60)

    if attention_category in {"distraction_video", "distraction_social"} and attention_duration >= 15:
        now = time.time()
        last_alert = get_state_meta("last_distraction_alert_ts", 0)
        
        if now - last_alert >= 900:
            try:
                bot_token, chat_id = get_telegram_config()
                alert_text = (
                    f"🚨 *Hermes Distraction Warning*\n"
                    f"You have been focused on distraction category *{attention_category}* for *{attention_duration} minutes*.\n"
                    f"Is it time to redirect your attention to focus work?"
                )
                payload = {
                    "chat_id": chat_id,
                    "text": alert_text,
                    "parse_mode": "Markdown",
                    "disable_notification": False
                }
                telegram_post("sendMessage", payload)
                set_state_meta("last_distraction_alert_ts", now)
                print("Distraction alert sent to Telegram.")
            except Exception as e:
                print(f"Failed to send distraction alert: {e}", file=sys.stderr)

if __name__ == "__main__":
    update_live_card()
