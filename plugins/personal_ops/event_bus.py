"""Append-only event bus for Hermes Personal Ops.

The event log is the durable ground truth for "what changed?" style operator
cycles. It stores canonical payload hashes and privacy classes so downstream
state reducers can audit which facts came from which subsystem.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


def _get_db_path() -> Path:
    hermes_home = Path(os.getenv("HERMES_HOME", str(Path.home() / ".hermes")))
    path = hermes_home / "personal_ops" / "event_log.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_get_db_path(), timeout=5.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


SCHEMA = {
    "source": str,
    "event_type": str,
    "timestamp": str,
    "payload": dict,
    "dedupe_key": str,
}


def _init_db() -> None:
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            event_type TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            payload TEXT NOT NULL,
            dedupe_key TEXT UNIQUE,
            raw_payload_hash TEXT,
            privacy_class TEXT NOT NULL DEFAULT 'internal'
        )
        """
    )
    cur.execute("PRAGMA table_info(events)")
    columns = {row[1] for row in cur.fetchall()}
    if "raw_payload_hash" not in columns:
        cur.execute("ALTER TABLE events ADD COLUMN raw_payload_hash TEXT")
    if "privacy_class" not in columns:
        cur.execute("ALTER TABLE events ADD COLUMN privacy_class TEXT NOT NULL DEFAULT 'internal'")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_events_type_ts ON events(event_type, timestamp)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_events_source_ts ON events(source, timestamp)")
    conn.commit()
    conn.close()


_init_db()

_subscribers: List[Callable[[Dict[str, Any]], None]] = []


def _canonical_payload(payload: Dict[str, Any]) -> str:
    return json.dumps(payload or {}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _payload_hash(payload: Dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_payload(payload).encode("utf-8")).hexdigest()


def validate_event(event: Dict[str, Any]) -> bool:
    for key, typ in SCHEMA.items():
        if key not in event or not isinstance(event[key], typ):
            return False
    if "privacy_class" in event and not isinstance(event["privacy_class"], str):
        return False
    return True


def ingest_event(event: Dict[str, Any]) -> bool:
    """Insert an event into the SQLite log if it validates and is not duplicate."""
    if not validate_event(event):
        return False
    payload = event["payload"] or {}
    privacy_class = str(event.get("privacy_class") or "internal")
    conn = _connect()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO events
                (source, event_type, timestamp, payload, dedupe_key, raw_payload_hash, privacy_class)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event["source"],
                event["event_type"],
                event["timestamp"],
                _canonical_payload(payload),
                event["dedupe_key"],
                event.get("raw_payload_hash") or _payload_hash(payload),
                privacy_class,
            ),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return False
    conn.close()
    for cb in list(_subscribers):
        cb(event)
    return True


def publish(event: Dict[str, Any]) -> bool:
    return ingest_event(event)


def log_event(
    source: str,
    event_type: str,
    payload: dict,
    dedupe_key: Optional[str] = None,
    privacy_class: str = "internal",
) -> Dict[str, Any]:
    if not dedupe_key:
        dedupe_key = str(uuid.uuid4())
    event = {
        "source": source,
        "event_type": event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": payload or {},
        "dedupe_key": dedupe_key,
        "privacy_class": privacy_class,
    }
    success = ingest_event(event)
    if not success:
        conn = _connect()
        cur = conn.cursor()
        cur.execute("SELECT id FROM events WHERE dedupe_key = ?", (dedupe_key,))
        row = cur.fetchone()
        conn.close()
        if row:
            return {"success": False, "duplicate": True}
        return {"success": False, "duplicate": False}
    return {"success": True, "duplicate": False}


def subscribe(callback: Callable[[Dict[str, Any]], None]) -> None:
    _subscribers.append(callback)


def get_all_events() -> List[Dict[str, Any]]:
    conn = _connect()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT source, event_type, timestamp, payload, dedupe_key, raw_payload_hash, privacy_class
        FROM events
        ORDER BY id ASC
        """
    )
    rows = cur.fetchall()
    conn.close()
    events: List[Dict[str, Any]] = []
    for source, event_type, ts, payload, dedupe_key, raw_payload_hash, privacy_class in rows:
        events.append(
            {
                "source": source,
                "event_type": event_type,
                "timestamp": ts,
                "payload": json.loads(payload),
                "dedupe_key": dedupe_key,
                "raw_payload_hash": raw_payload_hash,
                "privacy_class": privacy_class,
            }
        )
    return events
