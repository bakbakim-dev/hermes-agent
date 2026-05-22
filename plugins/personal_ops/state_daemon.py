"""Hermes State Daemon.

Consumes events from the sqlite event_bus log, updates presence/operator states,
and implements presence confidence decay when heartbeats are stale.
"""
from __future__ import annotations
import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

HERMES_HOME = Path(os.getenv("HERMES_HOME", str(Path.home() / ".hermes")))
DB_PATH = HERMES_HOME / "personal_ops" / "event_log.db"
PRESENCE_STATE_PATH = HERMES_HOME / "presence_state.json"
OPERATOR_STATE_PATH = HERMES_HOME / "operator_state.json"

class StateDaemon:
    def __init__(self, db_path: Path = DB_PATH, time_provider=time.time):
        self.db_path = db_path
        self.time_provider = time_provider
        self.last_processed_id = 0
        self.init_db()
        self.load_last_processed_id()

    def init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS state_meta (
                key TEXT PRIMARY KEY,
                val TEXT NOT NULL
            )
            """
        )
        conn.commit()
        conn.close()

    def load_last_processed_id(self) -> None:
        val = self.get_state_meta("last_processed_event_id")
        if val is not None:
            self.last_processed_id = int(val)

    def save_last_processed_id(self, event_id: int) -> None:
        self.last_processed_id = event_id
        self.set_state_meta("last_processed_event_id", event_id)

    def get_state_meta(self, key: str, default: Any = None) -> Any:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT val FROM state_meta WHERE key = ?", (key,))
        row = cur.fetchone()
        conn.close()
        if row:
            try:
                return json.loads(row[0])
            except Exception:
                return default
        return default

    def set_state_meta(self, key: str, val: Any) -> None:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO state_meta (key, val) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET val=excluded.val",
            (key, json.dumps(val)),
        )
        conn.commit()
        conn.close()

    def _read_json(self, path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default

    def _write_json(self, path: Path, val: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(val, f, indent=2)

    def process_event(self, event: Dict[str, Any], now_ts: int) -> None:
        event_type = event.get("event_type")
        source = event.get("source")
        payload = event.get("payload") or {}
        
        presence_state = self._read_json(PRESENCE_STATE_PATH, {})
        if not isinstance(presence_state, dict):
            presence_state = {}
            
        operator_state = self._read_json(OPERATOR_STATE_PATH, {})
        if not isinstance(operator_state, dict):
            operator_state = {}
            
        heartbeats = operator_state.setdefault("last_sensor_heartbeats", {})
        if source:
            heartbeats[source] = now_ts

        category = payload.get("category") or payload.get("active_category") or "unknown"

        # 1. Desktop Sentinel events
        if event_type == "desktop.active":
            presence_state["state"] = "desk"
            presence_state["confidence"] = 1.0
            presence_state["last_seen_ts"] = now_ts
            presence_state["afk"] = False
        elif event_type == "desktop.idle":
            if presence_state.get("state") == "desk":
                presence_state["state"] = presence_state.get("location", "home")
            presence_state["confidence"] = 1.0
            presence_state["last_seen_ts"] = now_ts
            presence_state["afk"] = True
        elif event_type in {"desktop.heartbeat", "desktop.category_changed"}:
            payload_state = payload.get("presence_state")
            if payload_state == "active_now":
                presence_state["state"] = "desk"
                presence_state["afk"] = False
            elif payload_state == "idle":
                if presence_state.get("state") == "desk":
                    presence_state["state"] = presence_state.get("location", "home")
                presence_state["afk"] = True
            presence_state["confidence"] = 1.0
            presence_state["last_seen_ts"] = now_ts

            att = operator_state.setdefault("attention", {})
            if category and category != "unknown":
                att["category"] = category
                att["last_updated_at"] = now_ts
        elif event_type == "desktop.category_ended":
            att = operator_state.setdefault("attention", {})
            att["category"] = "unknown"
            att["last_updated_at"] = now_ts
        elif event_type == "desktop.lock":
            if presence_state.get("state") == "desk":
                presence_state["state"] = presence_state.get("location", "home")
            presence_state["confidence"] = 1.0
            presence_state["last_seen_ts"] = now_ts
            presence_state["afk"] = True
            presence_state["locked"] = True
        elif event_type == "desktop.unlock":
            presence_state["state"] = "desk"
            presence_state["confidence"] = 1.0
            presence_state["last_seen_ts"] = now_ts
            presence_state["afk"] = False
            presence_state["locked"] = False
        elif event_type == "desktop.wake":
            presence_state["state"] = "desk"
            presence_state["confidence"] = 1.0
            presence_state["last_seen_ts"] = now_ts
            presence_state["afk"] = False

        # 2. iOS Focus & Sleep Events
        elif event_type == "ios.sleep_focus_on":
            presence_state["state"] = "sleep"
            presence_state["confidence"] = 1.0
            presence_state["last_seen_ts"] = now_ts
            operator_state["day_phase"] = "quiet_hours"
        elif event_type == "ios.sleep_focus_off":
            presence_state["state"] = "home"
            presence_state["confidence"] = 0.8
            presence_state["last_seen_ts"] = now_ts
            operator_state["day_phase"] = "morning_horizon"
            operator_state["wake_candidate_ts"] = now_ts
        elif event_type == "ios.work_focus_on":
            operator_state["day_phase"] = "work_window"
        elif event_type == "ios.work_focus_off":
            operator_state["day_phase"] = "evening"

        # 3. Location events
        elif event_type == "location_update":
            loc = payload.get("location") or payload.get("value") or "home"
            presence_state["location"] = loc
            presence_state["state"] = loc
            presence_state["confidence"] = 1.0
            presence_state["last_seen_ts"] = now_ts

        self._write_json(PRESENCE_STATE_PATH, presence_state)
        self._write_json(OPERATOR_STATE_PATH, operator_state)
        self.set_state_meta("presence_state", presence_state)
        self.set_state_meta("operator_state", operator_state)

    def run_decay(self, now_ts: int) -> bool:
        presence_state = self._read_json(PRESENCE_STATE_PATH, {})
        if not isinstance(presence_state, dict):
            presence_state = {}
            
        operator_state = self._read_json(OPERATOR_STATE_PATH, {})
        if not isinstance(operator_state, dict):
            operator_state = {}
            
        heartbeats = operator_state.get("last_sensor_heartbeats", {})
        sentinel_last = heartbeats.get("desktop_sentinel")
        
        if sentinel_last and (now_ts - int(sentinel_last) > 600):
            current_confidence = float(presence_state.get("confidence", 1.0))
            if current_confidence > 0.0 or presence_state.get("state") == "desk":
                if presence_state.get("state") == "desk":
                    presence_state["state"] = presence_state.get("location", "home")
                
                presence_state["confidence"] = max(0.0, current_confidence - 0.5)
                presence_state["last_decay_ts"] = now_ts
                
                self._write_json(PRESENCE_STATE_PATH, presence_state)
                self.set_state_meta("presence_state", presence_state)
                return True
        return False

    def step(self) -> int:
        """Fetch and process new events, and run decay. Returns number of processed events."""
        now_ts = int(self.time_provider())
        
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "SELECT id, source, event_type, timestamp, payload, dedupe_key FROM events WHERE id > ? ORDER BY id ASC",
            (self.last_processed_id,),
        )
        rows = cur.fetchall()
        conn.close()
        
        processed = 0
        for row in rows:
            event = {
                "id": row[0],
                "source": row[1],
                "event_type": row[2],
                "timestamp": row[3],
                "payload": json.loads(row[4]),
                "dedupe_key": row[5],
            }
            self.process_event(event, now_ts)
            self.save_last_processed_id(event["id"])
            processed += 1
            
        self.run_decay(now_ts)
        return processed

    def loop(self, interval: float = 1.0) -> None:
        """Continuous execution loop."""
        print("Hermes State Daemon started...")
        while True:
            try:
                self.step()
            except Exception as e:
                print(f"Error in state daemon loop: {e}")
            time.sleep(interval)

if __name__ == "__main__":
    daemon = StateDaemon()
    daemon.loop()
