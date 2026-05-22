"""Hermes Decision Daemon.

Calculates the Initiative Queue by scoring potential tasks, intercepts nudges
using the Task-Window Engine, and logs reasoning to why_quiet.jsonl.
"""
from __future__ import annotations
import json
import os
import time
import httpx
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from plugins.personal_ops.task_window_engine import evaluate_task

HERMES_HOME = Path(os.getenv("HERMES_HOME", str(Path.home() / ".hermes")))
PRESENCE_STATE_PATH = HERMES_HOME / "presence_state.json"
OPERATOR_STATE_PATH = HERMES_HOME / "operator_state.json"
WHY_QUIET_LOG_PATH = HERMES_HOME / "personal_ops" / "why_quiet.jsonl"
TODOIST_BASE = "https://api.todoist.com/rest/v2"

def get_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if value:
        return value
    env_path = HERMES_HOME / ".env"
    try:
        for raw in env_path.read_text(encoding="utf-8").splitlines():
            if not raw or raw.lstrip().startswith("#") or "=" not in raw:
                continue
            key, val = raw.split("=", 1)
            if key.strip() == name:
                return val.strip()
    except Exception:
        pass
    return ""

class DecisionDaemon:
    def __init__(self, time_provider=time.time):
        self.time_provider = time_provider
        WHY_QUIET_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

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

    def fetch_todoist_tasks(self) -> List[Dict[str, Any]]:
        token = get_env("TODOIST_API_TOKEN")
        if not token:
            return []
        try:
            headers = {"Authorization": f"Bearer {token}"}
            with httpx.Client(timeout=10.0) as client:
                resp = client.get(f"{TODOIST_BASE}/tasks", headers=headers)
                if resp.status_code == 200:
                    return resp.json()
        except Exception as e:
            print(f"Error fetching Todoist tasks: {e}")
        return []

    def score_task(self, task: Dict[str, Any], presence_state: Dict[str, Any], operator_state: Dict[str, Any]) -> float:
        priority = int(task.get("priority", 1))
        urgency = float(priority * 2.5)
        
        due = task.get("due")
        if due:
            due_date = due.get("datetime") or due.get("date")
            if due_date:
                try:
                    dt = datetime.fromisoformat(due_date.replace("Z", "+00:00"))
                    if dt.timestamp() < self.time_provider():
                        urgency = min(10.0, urgency + 3.0)
                except Exception:
                    pass

        usefulness = 5.0
        title = str(task.get("content") or task.get("title") or "").lower()
        attention = operator_state.get("attention", {})
        active_category = str(attention.get("category") or "").lower()
        if active_category and active_category != "unknown" and active_category in title:
            usefulness = min(10.0, usefulness + 3.0)

        presence_val = presence_state.get("state", "home")
        afk = presence_state.get("afk", True)
        
        if presence_val == "desk" and not afk:
            interruption_cost = 8.0
        elif presence_val == "desk" and afk:
            interruption_cost = 4.0
        else:
            interruption_cost = 2.0

        return (urgency * usefulness) / max(0.1, interruption_cost)

    def log_quiet(self, task: Dict[str, Any], score: float, evaluation: Dict[str, Any]) -> None:
        log_entry = {
            "timestamp": datetime.fromtimestamp(self.time_provider(), timezone.utc).isoformat(),
            "task_id": task.get("id"),
            "content": task.get("content"),
            "score": score,
            "allowed": evaluation.get("allowed"),
            "reason": evaluation.get("reason"),
            "action_guidance": evaluation.get("action_guidance")
        }
        with open(WHY_QUIET_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry) + "\n")

    def run_cycle(self) -> List[Dict[str, Any]]:
        presence_state = self._read_json(PRESENCE_STATE_PATH, {})
        operator_state = self._read_json(OPERATOR_STATE_PATH, {})
        
        tasks = self.fetch_todoist_tasks()
        if not tasks:
            return []
            
        now_dt = datetime.fromtimestamp(self.time_provider(), timezone.utc)
        
        scored_tasks = []
        for task in tasks:
            score = self.score_task(task, presence_state, operator_state)
            scored_tasks.append((task, score))
            
        scored_tasks.sort(key=lambda x: x[1], reverse=True)
        
        initiative_queue = []
        for task, score in scored_tasks:
            evaluation = evaluate_task(task, now_dt)
            
            if not evaluation["allowed"]:
                self.log_quiet(task, score, evaluation)
            
            initiative_queue.append({
                "task": task,
                "score": score,
                "evaluation": evaluation
            })
            
        operator_state["initiative_queue"] = [
            {
                "task_id": item["task"].get("id"),
                "content": item["task"].get("content"),
                "score": item["score"],
                "allowed": item["evaluation"]["allowed"],
                "reason": item["evaluation"]["reason"],
                "action_guidance": item["evaluation"]["action_guidance"]
            }
            for item in initiative_queue
        ]
        self._write_json(OPERATOR_STATE_PATH, operator_state)
        
        return initiative_queue

    def loop(self, interval: float = 60.0) -> None:
        print("Hermes Decision Daemon started...")
        while True:
            try:
                self.run_cycle()
            except Exception as e:
                print(f"Error in decision daemon loop: {e}")
            time.sleep(interval)

if __name__ == "__main__":
    daemon = DecisionDaemon()
    daemon.loop()
