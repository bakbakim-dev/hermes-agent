from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from zoneinfo import ZoneInfo

try:
    from . import event_bus
except Exception:  # pragma: no cover - event bus is best-effort
    event_bus = None  # type: ignore[assignment]


DEFAULT_TZ = "America/Edmonton"
OPEN_SESSION_TIMEOUT_HOURS = 8
DEFAULT_WORKOUT_TASK_LINKS = {
    0: ("Upper A workout (Monday)", "https://app.todoist.com/app/task/6ghFPf6XX9Hv3h6p"),
    1: ("Lower A workout (Tuesday)", "https://app.todoist.com/app/task/6ghFPf9V2P9xhCPp"),
    3: ("Upper B workout (Thursday)", "https://app.todoist.com/app/task/6ghFPfG2PHvRH8qp"),
    4: ("Lower B workout (Friday)", "https://app.todoist.com/app/task/6ghFPfPPp79w47Wp"),
}


def _hermes_home() -> Path:
    return Path(os.getenv("HERMES_HOME", str(Path.home() / ".hermes")))


def _gym_log_path() -> Path:
    return _hermes_home() / "personal_ops" / "gym_attendance.jsonl"


def _local_tz() -> ZoneInfo:
    tz_name = os.getenv("HERMES_TIMEZONE") or os.getenv("TZ") or DEFAULT_TZ
    try:
        return ZoneInfo(tz_name)
    except Exception:
        return ZoneInfo(DEFAULT_TZ)


def _now_local() -> datetime:
    return datetime.now(_local_tz())


def workout_task_for_day(when: Optional[datetime] = None) -> Optional[tuple[str, str]]:
    current = (when or _now_local()).astimezone(_local_tz())
    return DEFAULT_WORKOUT_TASK_LINKS.get(current.weekday())


def is_location_verified(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    raw = str(value or "").strip().lower()
    return raw in {"1", "true", "yes", "y", "verified", "location", "gps"}


def source_requires_location_verification(source: str) -> bool:
    normalized = str(source or "").strip().lower().replace("_", "-")
    return normalized.startswith("ios-shortcut")


def unverified_shortcut_message(kind: str) -> str:
    noun = "arrival" if kind in {"arrive", "arrived", "arrival"} else "departure"
    return (
        f"Gym {noun} not logged: iOS shortcut did not include verified_location=1. "
        "I am treating this as an unverified automation trigger, not proof you were at the gym."
    )


def _parse_iso(value: str) -> datetime:
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_local_tz())
    return dt.astimezone(_local_tz())


def _append_jsonl(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _read_events() -> List[Dict[str, Any]]:
    path = _gym_log_path()
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except Exception:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def _write_event(kind: str, *, source: str, note: str = "", when: Optional[datetime] = None) -> Dict[str, Any]:
    at = (when or _now_local()).astimezone(_local_tz())
    event = {
        "type": kind,
        "timestamp": at.isoformat(),
        "source": source,
        "note": note.strip(),
    }
    _append_jsonl(_gym_log_path(), event)
    if event_bus is not None:
        try:
            event_bus.log_event(
                source="gym_attendance",
                event_type=f"gym.{kind}",
                payload={"timestamp": event["timestamp"], "source": source, "note": event["note"]},
                dedupe_key=f"gym:{kind}:{event['timestamp']}",
            )
        except Exception:
            pass
    return event


@dataclass(frozen=True)
class GymSession:
    arrived_at: datetime
    left_at: Optional[datetime]
    arrive_source: str = ""
    leave_source: str = ""
    arrive_note: str = ""
    leave_note: str = ""

    @property
    def duration(self) -> Optional[timedelta]:
        if not self.left_at:
            return None
        delta = self.left_at - self.arrived_at
        if delta.total_seconds() < 0:
            return None
        return delta


def build_sessions(events: Optional[Iterable[Dict[str, Any]]] = None) -> List[GymSession]:
    rows = list(events if events is not None else _read_events())
    parsed: List[Dict[str, Any]] = []
    for row in rows:
        kind = str(row.get("type") or "")
        if kind not in {"arrived", "left"}:
            continue
        try:
            ts = _parse_iso(str(row.get("timestamp") or ""))
        except Exception:
            continue
        parsed.append({**row, "parsed_ts": ts})
    parsed.sort(key=lambda item: item["parsed_ts"])

    sessions: List[GymSession] = []
    open_arrival: Optional[Dict[str, Any]] = None
    for row in parsed:
        if row["type"] == "arrived":
            if open_arrival is not None:
                sessions.append(
                    GymSession(
                        arrived_at=open_arrival["parsed_ts"],
                        left_at=None,
                        arrive_source=str(open_arrival.get("source") or ""),
                        arrive_note=str(open_arrival.get("note") or ""),
                    )
                )
            open_arrival = row
            continue

        if open_arrival is None:
            sessions.append(
                GymSession(
                    arrived_at=row["parsed_ts"],
                    left_at=row["parsed_ts"],
                    leave_source=str(row.get("source") or ""),
                    leave_note="left_without_arrival",
                )
            )
            continue

        sessions.append(
            GymSession(
                arrived_at=open_arrival["parsed_ts"],
                left_at=row["parsed_ts"],
                arrive_source=str(open_arrival.get("source") or ""),
                leave_source=str(row.get("source") or ""),
                arrive_note=str(open_arrival.get("note") or ""),
                leave_note=str(row.get("note") or ""),
            )
        )
        open_arrival = None

    if open_arrival is not None:
        sessions.append(
            GymSession(
                arrived_at=open_arrival["parsed_ts"],
                left_at=None,
                arrive_source=str(open_arrival.get("source") or ""),
                arrive_note=str(open_arrival.get("note") or ""),
            )
        )
    return sessions


def _latest_open_session(now: Optional[datetime] = None) -> Optional[GymSession]:
    current = (now or _now_local()).astimezone(_local_tz())
    sessions = build_sessions()
    if not sessions:
        return None
    latest = sessions[-1]
    if latest.left_at is not None:
        return None
    if current - latest.arrived_at > timedelta(hours=OPEN_SESSION_TIMEOUT_HOURS):
        return None
    return latest


def record_arrival(
    *,
    source: str = "manual",
    note: str = "",
    when: Optional[datetime] = None,
    location_verified: Any = None,
) -> str:
    at = (when or _now_local()).astimezone(_local_tz())
    if source_requires_location_verification(source) and not is_location_verified(location_verified):
        return unverified_shortcut_message("arrival")
    open_session = _latest_open_session(at)
    if open_session is not None:
        return (
            "Gym arrival already looks open.\n"
            f"Arrived: {_fmt(open_session.arrived_at, '%b %d, %I:%M %p')}\n"
            "Use /gym left when you leave, or /gym arrived force if this is a new visit."
        )
    _write_event("arrived", source=source, note=note, when=at)
    task = workout_task_for_day(at)
    if task:
        name, url = task
        return f"Logged gym arrival: {_fmt(at, '%b %d, %I:%M %p')}.\nToday's workout: {name}\n{url}"

    day_name = at.strftime('%A')
    return (
        f"Logged gym arrival: {_fmt(at, '%b %d, %I:%M %p')}.\n"
        f"⚠️ <b>Note</b>: Today is {day_name}, which is one of your regular recovery days (Wednesday, Saturday, Sunday). "
        "If this was an accidental GPS drift or false pocket-trigger from your iPhone, you can ignore this or delete it."
    )


def record_departure(
    *,
    source: str = "manual",
    note: str = "",
    when: Optional[datetime] = None,
    location_verified: Any = None,
) -> str:
    at = (when or _now_local()).astimezone(_local_tz())
    if source_requires_location_verification(source) and not is_location_verified(location_verified):
        return unverified_shortcut_message("departure")
    open_session = _latest_open_session(at)
    _write_event("left", source=source, note=note, when=at)
    if open_session is None:
        return f"Logged gym departure: {_fmt(at, '%b %d, %I:%M %p')}. I did not see a matching recent arrival."
    duration = at - open_session.arrived_at
    minutes = max(0, round(duration.total_seconds() / 60))
    return f"Logged gym departure: {_fmt(at, '%b %d, %I:%M %p')}.\nSession length: {minutes} min."


def _month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    start = datetime(year, month, 1, tzinfo=_local_tz())
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=_local_tz())
    else:
        end = datetime(year, month + 1, 1, tzinfo=_local_tz())
    return start, end


def _format_duration(minutes: int) -> str:
    hours, mins = divmod(minutes, 60)
    if hours and mins:
        return f"{hours}h {mins}m"
    if hours:
        return f"{hours}h"
    return f"{mins}m"


def _fmt(dt: datetime, pattern: str) -> str:
    text = dt.strftime(pattern)
    return text.replace(" 0", " ").lstrip("0")


def monthly_report(*, year: Optional[int] = None, month: Optional[int] = None) -> str:
    now = _now_local()
    y = year or now.year
    m = month or now.month
    start, end = _month_bounds(y, m)
    sessions = [s for s in build_sessions() if start <= s.arrived_at < end]

    complete = [s for s in sessions if s.duration is not None and s.duration.total_seconds() > 0]
    open_count = sum(1 for s in sessions if s.left_at is None)
    left_without_arrival = sum(1 for s in sessions if s.leave_note == "left_without_arrival")
    total_minutes = sum(round(s.duration.total_seconds() / 60) for s in complete if s.duration)
    avg_minutes = round(total_minutes / len(complete)) if complete else 0
    days = sorted({s.arrived_at.date() for s in sessions})

    month_name = start.strftime("%B %Y")
    lines = [
        f"Gym monthly report - {month_name}",
        "",
        f"Sessions logged: {len(complete)} complete",
        f"Gym days: {len(days)}",
        f"Total time: {_format_duration(total_minutes)}",
        f"Average session: {_format_duration(avg_minutes) if complete else 'n/a'}",
    ]
    if open_count or left_without_arrival:
        lines.append("")
        lines.append("Data checks:")
        if open_count:
            lines.append(f"- {open_count} arrival event(s) have no matching left event.")
        if left_without_arrival:
            lines.append(f"- {left_without_arrival} left event(s) had no matching arrival.")
    if complete:
        lines.append("")
        lines.append("Recent sessions:")
        for session in complete[-6:]:
            minutes = round(session.duration.total_seconds() / 60) if session.duration else 0
            lines.append(
                f"- {_fmt(session.arrived_at, '%b %d')}: "
                f"{_fmt(session.arrived_at, '%I:%M %p')} -> "
                f"{_fmt(session.left_at, '%I:%M %p') if session.left_at else '?'} "
                f"({_format_duration(minutes)})"
            )
    else:
        lines.append("")
        lines.append("No complete gym sessions logged for this month yet.")
    return "\n".join(lines)


def shortcut_instructions() -> str:
    return (
        "iOS Shortcut setup with URL automation:\n"
        "1. Create an automation for Arrive at Gym: 11501 Buffalo Run Blvd #131, Tsuut'ina, AB T3T 0E1.\n"
        "2. Add action: Get Contents of URL.\n"
        "3. URL: https://YOUR-HERMES-DOMAIN/gym?event=arrived&secret=YOUR_SECRET&verified_location=1\n"
        "4. Add action: Get Dictionary Value workout_task.url from the response.\n"
        "5. If the value exists, Open URL.\n"
        "6. Create another automation for Leave Gym.\n"
        "7. URL: https://YOUR-HERMES-DOMAIN/gym?event=left&secret=YOUR_SECRET&verified_location=1\n\n"
        "Workout task links:\n"
        "- Monday Upper A: https://app.todoist.com/app/task/6ghFPf6XX9Hv3h6p\n"
        "- Tuesday Lower A: https://app.todoist.com/app/task/6ghFPf9V2P9xhCPp\n"
        "- Thursday Upper B: https://app.todoist.com/app/task/6ghFPfG2PHvRH8qp\n"
        "- Friday Lower B: https://app.todoist.com/app/task/6ghFPfPPp79w47Wp\n\n"
        "Optional commands:\n"
        "- /gym report\n"
        "- /gym report 2026-05\n"
        "- /gym status\n\n"
        "If you later expose Hermes webhooks publicly, these same actions can be changed to authenticated HTTP calls."
    )


def _parse_report_month(raw: str) -> tuple[Optional[int], Optional[int]]:
    value = raw.strip()
    if not value:
        return None, None
    try:
        parsed = datetime.strptime(value[:7], "%Y-%m")
        return parsed.year, parsed.month
    except Exception:
        return None, None


def handle_gym_slash_command(raw_args: str) -> str:
    raw = (raw_args or "").strip()
    parts = raw.split()
    action = parts[0].lower() if parts else "status"
    rest = " ".join(parts[1:]).strip()

    if action in {"arrive", "arrived", "in", "checkin", "check-in"}:
        force = rest.lower() == "force"
        if force:
            _write_event("arrived", source="telegram-command", note="forced")
            return f"Logged gym arrival: {_fmt(_now_local(), '%b %d, %I:%M %p')}."
        return record_arrival(source="telegram-command", note=rest)
    if action in {"leave", "left", "out", "checkout", "check-out"}:
        return record_departure(source="telegram-command", note=rest)
    if action in {"report", "month", "monthly"}:
        year, month = _parse_report_month(rest)
        return monthly_report(year=year, month=month)
    if action in {"task", "workout"}:
        task = workout_task_for_day()
        if not task:
            return "No lifting task is scheduled for today."
        name, url = task
        return f"Today's workout: {name}\n{url}"
    if action in {"shortcuts", "ios", "setup"}:
        return shortcut_instructions()
    if action in {"status", ""}:
        open_session = _latest_open_session()
        if open_session is None:
            return "No open gym session right now.\nUse /gym arrived when you get there, /gym left when you leave, or /gym report for the month."
        minutes = round((_now_local() - open_session.arrived_at).total_seconds() / 60)
        return f"Open gym session: arrived {_fmt(open_session.arrived_at, '%b %d, %I:%M %p')} ({minutes} min ago).\nUse /gym left when you leave."
    return "Usage: /gym arrived, /gym left, /gym report, /gym report YYYY-MM, /gym shortcuts"
