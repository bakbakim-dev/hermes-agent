from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from .gym_attendance import (
    is_location_verified,
    source_requires_location_verification,
    unverified_shortcut_message,
)


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _event_kind(event_type: str) -> str:
    if event_type == "gym.arrived":
        return "arrived"
    if event_type == "gym.left":
        return "left"
    return "event"


def guard_unverified_event(payload: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """Block edge-ingress gym events that lack an explicit location proof flag."""

    nested = _as_mapping(payload.get("payload"))
    event_type = str(_first_present(payload.get("event_type"), nested.get("event_type")) or "").strip().lower()
    source = str(_first_present(payload.get("source"), nested.get("source")) or "").strip()
    if not event_type.startswith("gym.") or not source_requires_location_verification(source):
        return None

    verified = _first_present(
        payload.get("location_verified"),
        payload.get("verified_location"),
        nested.get("location_verified"),
        nested.get("verified_location"),
    )
    if is_location_verified(verified):
        return None

    message = unverified_shortcut_message(_event_kind(event_type))
    return {
        "success": True,
        "action": str(payload.get("action") or "event_ingest"),
        "handled": True,
        "event_type": event_type,
        "source": source,
        "message": message,
        "summary": message,
        "logged": False,
        "sent": False,
        "suppressed_reason": "unverified_ios_shortcut",
        "payload": {
            "gym_event": event_type,
            "source": source,
            "note": "Suppressed at HTTP ingress before runtime dispatch.",
        },
    }
