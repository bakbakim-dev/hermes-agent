import json
import os
from pathlib import Path
from plugins.personal_ops.decision_daemon import DecisionDaemon

def test_decision_daemon_cycle(tmp_path, monkeypatch):
    presence_path = tmp_path / "presence_state.json"
    operator_path = tmp_path / "operator_state.json"
    why_quiet_path = tmp_path / "why_quiet.jsonl"
    
    monkeypatch.setattr("plugins.personal_ops.decision_daemon.PRESENCE_STATE_PATH", presence_path)
    monkeypatch.setattr("plugins.personal_ops.decision_daemon.OPERATOR_STATE_PATH", operator_path)
    monkeypatch.setattr("plugins.personal_ops.decision_daemon.WHY_QUIET_LOG_PATH", why_quiet_path)
    
    presence_data = {
        "state": "desk",
        "afk": False,
        "location": "desk",
        "confidence": 1.0
    }
    with open(presence_path, "w", encoding="utf-8") as f:
        json.dump(presence_data, f)
        
    operator_data = {
        "attention": {
            "category": "work"
        }
    }
    with open(operator_path, "w", encoding="utf-8") as f:
        json.dump(operator_data, f)

    from plugins.personal_ops.task_window_engine import get_local_tz
    from datetime import datetime
    local_tz = get_local_tz()
    dt = datetime(2026, 5, 21, 23, 0, 0, tzinfo=local_tz)
    timestamp = dt.timestamp()
    
    daemon = DecisionDaemon(time_provider=lambda: timestamp)
    
    mock_tasks = [
        {
            "id": "task_1",
            "content": "Morning Launch",
            "priority": 1,
            "due": None
        },
        {
            "id": "task_2",
            "content": "Contact VA about work invoice",
            "priority": 3,
            "due": None
        },
        {
            "id": "task_3",
            "content": "Do laundry",
            "priority": 4,
            "due": None
        }
    ]
    monkeypatch.setattr(daemon, "fetch_todoist_tasks", lambda: mock_tasks)
    
    queue = daemon.run_cycle()
    
    assert len(queue) == 3
    
    for item in queue:
        task_id = item["task"]["id"]
        eval_res = item["evaluation"]
        assert eval_res["allowed"] is False
        if task_id == "task_1":
            assert eval_res["reason"] == "morning_routine_expired"
        elif task_id == "task_2":
            assert eval_res["reason"] == "outside_business_hours"
        elif task_id == "task_3":
            assert eval_res["reason"] == "quiet_hours_restriction"
            
    assert why_quiet_path.exists()
    lines = why_quiet_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
