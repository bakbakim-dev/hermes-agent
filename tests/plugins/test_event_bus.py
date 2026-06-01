from __future__ import annotations

import importlib
import json
import sqlite3


def test_event_bus_records_payload_hash_privacy_and_indexes(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    import plugins.personal_ops.event_bus as event_bus

    event_bus = importlib.reload(event_bus)

    result = event_bus.log_event(
        "telegram",
        "nudge.sent",
        {"message": "Laundry", "task_id": "t1"},
        dedupe_key="dedupe-1",
        privacy_class="personal_ops",
    )

    assert result["success"] is True
    conn = sqlite3.connect(tmp_path / "personal_ops" / "event_log.db")
    row = conn.execute(
        "SELECT source, event_type, payload, raw_payload_hash, privacy_class FROM events WHERE dedupe_key = ?",
        ("dedupe-1",),
    ).fetchone()
    indexes = {item[1] for item in conn.execute("PRAGMA index_list(events)").fetchall()}
    journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    conn.close()

    assert row[0] == "telegram"
    assert row[1] == "nudge.sent"
    assert json.loads(row[2])["task_id"] == "t1"
    assert len(row[3]) == 64
    assert row[4] == "personal_ops"
    assert "idx_events_timestamp" in indexes
    assert "idx_events_type_ts" in indexes
    assert journal_mode.lower() == "wal"
