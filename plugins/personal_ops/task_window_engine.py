"""Hermes Task-Window Engine.

Implements temporal boundary rules for task evaluation (routine expiry, business hours, quiet hours).
"""
from __future__ import annotations
import os
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List

try:
    from zoneinfo import ZoneInfo
except ImportError:
    ZoneInfo = None

def get_local_tz() -> Any:
    tz_str = os.getenv("HERMES_LOCAL_TIMEZONE", "America/Edmonton")
    if ZoneInfo is not None:
        try:
            return ZoneInfo(tz_str)
        except Exception:
            pass
    # Fallback to standard America/Edmonton GMT-7 Mountain timezone
    return timezone(timedelta(hours=-7))

def evaluate_task(task: Dict[str, Any], now_dt: datetime) -> Dict[str, Any]:
    """Evaluates a task against temporal boundary rules and returns guidance."""
    local_tz = get_local_tz()
    local_dt = now_dt.astimezone(local_tz)
    local_hour = local_dt.hour
    local_weekday = local_dt.weekday()  # 0 = Monday, 6 = Sunday
    
    title = str(task.get("content") or task.get("title") or "").strip().lower()
    labels = [str(l).strip().lower() for l in (task.get("labels") or task.get("tags") or [])]
    
    # 1. Routine Expiry
    if "morning launch" in title or "morning routine" in title:
        if local_hour >= 13:  # After 1:00 PM
            return {
                "allowed": False,
                "reason": "morning_routine_expired",
                "action_guidance": "convert_to_tomorrow_prep"
            }
            
    if "breakfast" in title:
        if local_hour >= 11:  # After 11:00 AM
            return {
                "allowed": False,
                "reason": "breakfast_expired",
                "action_guidance": "shunt_to_logging"
            }
            
    # 2. Business Boundaries
    has_business_tag = any(t in labels or t in title for t in ["business", "va", "staff"])
    if has_business_tag:
        is_business_hours = False
        if local_weekday == 6:  # Sunday
            if 9 <= local_hour < 15:
                is_business_hours = True
        else:  # Monday-Saturday
            if 8 <= local_hour < 20:
                is_business_hours = True
                
        if not is_business_hours:
            return {
                "allowed": False,
                "reason": "outside_business_hours",
                "action_guidance": "draft_or_schedule"
            }
            
    # 3. Domestic Quiet Hours
    if "laundry" in title:
        if not (7 <= local_hour < 22):  # Outside 7 AM - 10 PM
            return {
                "allowed": False,
                "reason": "quiet_hours_restriction",
                "action_guidance": "defer"
            }
            
    return {
        "allowed": True,
        "reason": "within_bounds",
        "action_guidance": "none"
    }
