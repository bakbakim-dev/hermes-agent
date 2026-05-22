import json
import os
import sqlite3
from pathlib import Path
from plugins.personal_ops.state_daemon import StateDaemon

def test_state_decay(tmp_path, monkeypatch):
    db_path = tmp_path / "event_log.db"
    presence_path = tmp_path / "presence_state.json"
    operator_path = tmp_path / "operator_state.json"
    
    monkeypatch.setattr("plugins.personal_ops.state_daemon.DB_PATH", db_path)
    monkeypatch.setattr("plugins.personal_ops.state_daemon.PRESENCE_STATE_PATH", presence_path)
    monkeypatch.setattr("plugins.personal_ops.state_daemon.OPERATOR_STATE_PATH", operator_path)
    
    conn = sqlite3.connect(db_path)
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

    current_time = 1000000000
    def time_provider():
        return current_time

    daemon = StateDaemon(db_path=db_path, time_provider=time_provider)
    
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO events (source, event_type, timestamp, payload, dedupe_key) VALUES (?, ?, ?, ?, ?)",
        ("desktop_sentinel", "desktop.active", "2026-05-21T00:00:00Z", json.dumps({}), "dedupe_1")
    )
    conn.commit()
    conn.close()
    
    daemon.step()
    
    with open(presence_path, "r", encoding="utf-8") as f:
        presence = json.load(f)
    assert presence["state"] == "desk"
    assert presence["confidence"] == 1.0
    assert presence["afk"] is False
    
    with open(operator_path, "r", encoding="utf-8") as f:
        operator = json.load(f)
    assert operator["last_sensor_heartbeats"]["desktop_sentinel"] == 1000000000
    
    current_time += 660
    
    daemon.step()
    
    with open(presence_path, "r", encoding="utf-8") as f:
        presence_after = json.load(f)
    
    assert presence_after["state"] == "home"
    assert presence_after["confidence"] == 0.5
