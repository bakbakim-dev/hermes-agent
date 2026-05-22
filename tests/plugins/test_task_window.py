from datetime import datetime, timezone, timedelta
from plugins.personal_ops.task_window_engine import evaluate_task, get_local_tz

def test_morning_launch_expiry():
    local_tz = get_local_tz()
    dt = datetime(2026, 5, 21, 21, 0, 0, tzinfo=local_tz)
    task = {"content": "Morning Launch", "labels": []}
    res = evaluate_task(task, dt)
    assert res["allowed"] is False
    assert res["reason"] == "morning_routine_expired"
    assert res["action_guidance"] == "convert_to_tomorrow_prep"

def test_contact_va_outside_business_hours():
    local_tz = get_local_tz()
    dt = datetime(2026, 5, 21, 20, 30, 0, tzinfo=local_tz)
    task = {"content": "Contact VA about invoice", "labels": []}
    res = evaluate_task(task, dt)
    assert res["allowed"] is False
    assert res["reason"] == "outside_business_hours"
    assert res["action_guidance"] == "draft_or_schedule"

def test_breakfast_expiry():
    local_tz = get_local_tz()
    dt = datetime(2026, 5, 21, 12, 0, 0, tzinfo=local_tz)
    task = {"content": "Eat Breakfast", "labels": []}
    res = evaluate_task(task, dt)
    assert res["allowed"] is False
    assert res["reason"] == "breakfast_expired"
    assert res["action_guidance"] == "shunt_to_logging"

def test_laundry_quiet_hours():
    local_tz = get_local_tz()
    dt = datetime(2026, 5, 21, 23, 0, 0, tzinfo=local_tz)
    task = {"content": "Do laundry", "labels": []}
    res = evaluate_task(task, dt)
    assert res["allowed"] is False
    assert res["reason"] == "quiet_hours_restriction"
    assert res["action_guidance"] == "defer"
