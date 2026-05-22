# plugins/personal_ops/event_bus.py
"""Hermes Personal Ops Event Bus.

Provides event schema validation, an append‑only SQLite log, and a simple subscription mechanism.
"""
import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List

# Determine location for the SQLite DB (inside the Herm​es home directory)
HERMES_HOME = Path(os.getenv("HERMES_HOME", str(Path.home() / ".hermes")))
DB_PATH = HERMES_HOME / "personal_ops" / "event_log.db"

# Ensure the directory exists
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

# Event schema definition (basic type checking)
SCHEMA = {
    "source": str,
    "event_type": str,
    "timestamp": str,
    "payload": dict,
    "dedupe_key": str,
}

# Initialize the SQLite database with an events table
def _init_db() -> None:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            event_type TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            payload TEXT NOT NULL,
            dedupe_key TEXT UNIQUE
        )
        """
    )
    conn.commit()
    conn.close()

_init_db()

# In‑memory list of subscriber callbacks
_subscribers: List[Callable[[Dict[str, Any]], None]] = []

def validate_event(event: Dict[str, Any]) -> bool:
    """Validate an event against the simple SCHEMA.
    Returns True if all required keys exist and have the correct type.
    """
    for key, typ in SCHEMA.items():
        if key not in event or not isinstance(event[key], typ):
            return False
    return True

def ingest_event(event: Dict[str, Any]) -> bool:
    """Insert an event into the SQLite log if it validates and is not a duplicate.
    Returns True on successful insertion, False otherwise (validation failure or duplicate).
    """
    if not validate_event(event):
        return False
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO events (source, event_type, timestamp, payload, dedupe_key) VALUES (?, ?, ?, ?, ?)",
            (
                event["source"],
                event["event_type"],
                event["timestamp"],
                json.dumps(event["payload"]),
                event["dedupe_key"],
            ),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return False  # duplicate dedupe_key
    conn.close()
    # Notify subscribers after successful insertion
    for cb in _subscribers:
        cb(event)
    return True


def publish(event: Dict[str, Any]) -> bool:
    """Publish an event to the event bus. Alias for ingest_event."""
    return ingest_event(event)


def log_event(source: str, event_type: str, payload: dict, dedupe_key: str = None) -> Dict[str, Any]:
    """Log an event to the event bus, returning a dict with duplicate status."""
    if not dedupe_key:
        import uuid
        dedupe_key = str(uuid.uuid4())
    event = {
        "source": source,
        "event_type": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": payload or {},
        "dedupe_key": dedupe_key
    }
    success = ingest_event(event)
    if not success:
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT id FROM events WHERE dedupe_key = ?", (dedupe_key,))
        row = cur.fetchone()
        conn.close()
        if row:
            return {"success": False, "duplicate": True}
        return {"success": False, "duplicate": False}
    return {"success": True, "duplicate": False}


def subscribe(callback: Callable[[Dict[str, Any]], None]) -> None:
    """Register a callback to be invoked for each newly ingested event.
    The callback receives the raw event dictionary.
    """
    _subscribers.append(callback)

def get_all_events() -> List[Dict[str, Any]]:
    """Return a list of all stored events ordered by insertion time.
    Payloads are deserialized back into Python dictionaries.
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT source, event_type, timestamp, payload, dedupe_key FROM events ORDER BY id ASC")
    rows = cur.fetchall()
    conn.close()
    events: List[Dict[str, Any]] = []
    for source, event_type, ts, payload, dedupe_key in rows:
        events.append({
            "source": source,
            "event_type": event_type,
            "timestamp": ts,
            "payload": json.loads(payload),
            "dedupe_key": dedupe_key,
        })
    return events
