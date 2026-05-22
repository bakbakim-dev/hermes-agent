"""Hermes Desktop Sentinel for Windows.

Polls local ActivityWatch, classifies window titles locally, sanitizes
for privacy, and transmits summarized state events to the Hermes ingress.
"""
from __future__ import annotations
import os
import sys
import time
import urllib.request
import urllib.error
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

if sys.platform == "win32":
    import ctypes

# Load env variables from .env if present
def load_env():
    env_paths = [
        Path(__file__).parent.parent.parent / ".env",
        Path.home() / ".hermes" / ".env"
    ]
    for p in env_paths:
        if p.exists():
            for line in p.read_text(encoding="utf-8").splitlines():
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.split("=", 1)
                    os.environ[k.strip()] = v.strip()
            break

load_env()

HERMES_URL = os.getenv("HERMES_EVENT_WEBHOOK_URL", "http://127.0.0.1:8787/event")
HERMES_TOKEN = os.getenv("HERMES_EVENT_WEBHOOK_TOKEN", "")
ACTIVITYWATCH_URL = os.getenv("ACTIVITYWATCH_URL", "http://localhost:5600/api/0")

CATEGORIES = {
    "focus_work": ["vscode", "pycharm", "intellij", "terminal", "powershell", "cmd", "github", "stack overflow", "git", "sublime", "vim"],
    "todoist_planning": ["todoist"],
    "communication": ["slack", "discord", "telegram", "teams", "zoom", "gmail", "outlook", "whatsapp", "mail", "messenger"],
    "distraction_video": ["youtube", "netflix", "twitch", "prime video", "vimeo", "hulu"],
    "distraction_social": ["reddit", "twitter", "facebook", "instagram", "tiktok"],
    "research": ["google scholar", "arxiv", "wikipedia", "documentation", "mdn", "stackexchange"],
    "work_admin": ["explorer", "settings", "control panel", "excel", "word", "powerpoint", "pdf", "acrobat", "document"],
}

class DesktopSentinel:
    def __init__(self):
        self.last_presence = "unknown"
        self.last_afk = False
        self.last_category = "unknown"
        self.category_started_at = time.time()
        self.last_heartbeat_sent = 0
        self.aw_host = None
        self.window_bucket = None
        self.afk_bucket = None
        self.last_locked = False
        self.last_cycle_time = time.time()

    def find_buckets(self) -> bool:
        """Finds active ActivityWatch window and AFK buckets."""
        try:
            req = urllib.request.Request(f"{ACTIVITYWATCH_URL}/buckets")
            with urllib.request.urlopen(req, timeout=3) as resp:
                buckets = json.loads(resp.read().decode("utf-8"))
                for bucket_id in buckets.keys():
                    if "aw-watcher-window" in bucket_id:
                        self.window_bucket = bucket_id
                    elif "aw-watcher-afk" in bucket_id:
                        self.afk_bucket = bucket_id
            return bool(self.window_bucket and self.afk_bucket)
        except Exception as e:
            print(f"Error connecting to ActivityWatch: {e}", file=sys.stderr)
            return False

    def get_latest_event(self, bucket_id: str) -> Optional[Dict[str, Any]]:
        """Fetch the latest event from a specific bucket."""
        try:
            req = urllib.request.Request(f"{ACTIVITYWATCH_URL}/buckets/{bucket_id}/events?limit=1")
            with urllib.request.urlopen(req, timeout=2) as resp:
                events = json.loads(resp.read().decode("utf-8"))
                if events:
                    return events[0]
        except Exception:
            pass
        return None

    def classify_title(self, title: str, app: str = "") -> str:
        """Classifies a window title into a category, stripping private information."""
        title_lower = title.lower()
        app_lower = app.lower()
        for cat, keywords in CATEGORIES.items():
            for kw in keywords:
                if kw in title_lower or kw in app_lower:
                    return cat
        
        # Heuristics for fallback classification
        if any(kw in app_lower for kw in ["slack", "discord", "telegram", "whatsapp", "teams", "zoom", "skype", "webex"]):
            return "communication"
        if any(kw in app_lower for kw in ["vlc", "spotify", "netflix", "youtube", "player", "tv"]):
            return "distraction_video"
        
        # Default fallback
        return "work_admin"

    def is_locked(self) -> bool:
        """Determines if the Windows OS desktop is locked."""
        if sys.platform != "win32":
            return False
        try:
            # DESKTOP_SWITCHDESKTOP = 0x0100
            h_desk = ctypes.windll.user32.OpenInputDesktop(0, False, 0x0100)
            if h_desk == 0:
                return True
            ctypes.windll.user32.CloseDesktop(h_desk)
            return False
        except Exception:
            return False

    def send_event(self, event_type: str, payload: Dict[str, Any], dedupe_key: Optional[str] = None):
        """Sends event summary to Hermes Event Ingress."""
        event_data = {
            "source": "desktop_sentinel",
            "event_type": event_type,
            "payload": payload,
            "dedupe_key": dedupe_key,
        }
        try:
            headers = {"Content-Type": "application/json"}
            if HERMES_TOKEN:
                headers["Authorization"] = f"Bearer {HERMES_TOKEN}"

            req = urllib.request.Request(
                HERMES_URL,
                data=json.dumps(event_data).encode("utf-8"),
                headers=headers,
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                print(f"Event {event_type} sent successfully. Response: {res}")
        except Exception as e:
            print(f"Failed to send event {event_type} to Hermes: {e}", file=sys.stderr)

    def run_cycle(self):
        """Single loop cycle polling ActivityWatch and dispatching state changes."""
        if not self.window_bucket or not self.afk_bucket:
            if not self.find_buckets():
                time.sleep(10)
                return

        # Detect sleep/wake transitions via time gap
        now = time.time()
        if self.last_cycle_time and (now - self.last_cycle_time > 30):
            self.send_event(
                "desktop.wake",
                {
                    "wake_detected": True,
                    "gap_sec": int(now - self.last_cycle_time)
                }
            )
        self.last_cycle_time = now

        # Detect OS lock/unlock transitions
        locked = self.is_locked()
        if locked != self.last_locked:
            self.last_locked = locked
            self.send_event(
                "desktop.lock" if locked else "desktop.unlock",
                {
                    "locked": locked
                }
            )

        # 1. Fetch current status
        window_evt = self.get_latest_event(self.window_bucket)
        afk_evt = self.get_latest_event(self.afk_bucket)

        afk = False
        if afk_evt:
            # ActivityWatch returns status as 'afk' or 'not-afk'
            afk = (afk_evt.get("data") or {}).get("status") == "afk"

        # If OS is locked, presence is always idle/afk
        if locked:
            afk = True

        title = ""
        app = ""
        if window_evt:
            title = (window_evt.get("data") or {}).get("title", "")
            app = (window_evt.get("data") or {}).get("app", "")

        # 2. Determine presence
        current_presence = "idle" if afk else "active_now"
        category = self.classify_title(f"{title} {app}", app)

        # 3. Detect changes
        
        # Dispatch AFK state transitions
        if afk != self.last_afk:
            self.last_afk = afk
            self.last_presence = current_presence
            self.send_event(
                "desktop.active" if not afk else "desktop.idle",
                {
                    "presence_state": current_presence,
                    "afk": afk,
                }
            )

        # Dispatch Category transitions
        if category != self.last_category:
            prev_cat = self.last_category
            dur = int(now - self.category_started_at)
            self.category_started_at = now
            self.last_category = category

            # Log old category change
            if prev_cat != "unknown":
                self.send_event(
                    "desktop.category_ended",
                    {
                        "category": prev_cat,
                        "duration_sec": dur
                    }
                )

            self.send_event(
                "desktop.category_changed",
                {
                    "category": category,
                    "app": app
                }
            )

        # 4. Sustained Distraction Checks (e.g. 15 min, 30 min, 60 min thresholds)
        if category in {"distraction_video", "distraction_social"}:
            dur = int(now - self.category_started_at)
            # Create a unique dedupe key per category/hour so it doesn't trigger multiple times in the same block
            hour_block = int(now // 3600)
            
            if dur >= 900 and dur < 930: # 15 minutes
                self.send_event(
                    "desktop.distraction_15m",
                    {"category": category, "duration_sec": dur},
                    dedupe_key=f"distraction_15m_{category}_{hour_block}"
                )
            elif dur >= 1800 and dur < 1830: # 30 minutes
                self.send_event(
                    "desktop.distraction_30m",
                    {"category": category, "duration_sec": dur},
                    dedupe_key=f"distraction_30m_{category}_{hour_block}"
                )

        # 5. Heartbeat to maintain watchdog freshness (every 60 seconds)
        if now - self.last_heartbeat_sent >= 60:
            self.last_heartbeat_sent = now
            self.send_event(
                "desktop.heartbeat",
                {
                    "presence_state": current_presence,
                    "afk": afk,
                    "active_category": category,
                }
            )

def main():
    print("Starting Hermes Desktop Sentinel...")
    sentinel = DesktopSentinel()
    while True:
        try:
            sentinel.run_cycle()
        except KeyboardInterrupt:
            print("Sentinel stopped.")
            break
        except Exception as e:
            print(f"Sentinel cycle error: {e}", file=sys.stderr)
        time.sleep(10)

if __name__ == "__main__":
    main()
