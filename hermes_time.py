"""
Timezone-aware clock for Hermes.

Provides a single ``now()`` helper that returns a timezone-aware datetime
based on the user's configured IANA timezone (e.g. ``Asia/Kolkata``).

Resolution order:
  1. ``HERMES_TIMEZONE`` environment variable
  2. ``timezone`` key in ``~/.hermes/config.yaml``
  3. Falls back to the server's local time (``datetime.now().astimezone()``)

Invalid timezone values log a warning and fall back safely — Hermes never
crashes due to a bad timezone string.
"""

import logging
import os
from datetime import datetime
from hermes_constants import get_config_path
from typing import Optional

logger = logging.getLogger(__name__)

_CANONICAL_TIMEZONE_ALIASES = {
    "Canada/Mountain": "America/Edmonton",
}

try:
    from zoneinfo import ZoneInfo
except ImportError:
    # Python 3.8 fallback (shouldn't be needed — Hermes requires 3.9+)
    from backports.zoneinfo import ZoneInfo  # type: ignore[no-redef]

# Cached state — resolved once, reused on every call.
# Call reset_cache() to force re-resolution (e.g. after config changes).
_cached_tz: Optional[ZoneInfo] = None
_cached_tz_name: Optional[str] = None
_cache_resolved: bool = False


def _resolve_timezone_name() -> str:
    """Read the configured IANA timezone string (or empty string).

    This does file I/O when falling through to config.yaml, so callers
    should cache the result rather than calling on every ``now()``.
    """
    # 1. Environment variable (highest priority — set by Supervisor, etc.)
    tz_env = os.getenv("HERMES_TIMEZONE", "").strip()
    if tz_env:
        return _canonicalize_timezone_name(tz_env)

    # 2. config.yaml ``timezone`` key
    try:
        import yaml
        config_path = get_config_path()
        if config_path.exists():
            with open(config_path, encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            tz_cfg = cfg.get("timezone", "")
            if isinstance(tz_cfg, str) and tz_cfg.strip():
                return _canonicalize_timezone_name(tz_cfg.strip())
    except Exception:
        pass

    return ""


def _canonicalize_timezone_name(name: str) -> str:
    """Normalize known aliases to a canonical IANA timezone string."""
    return _CANONICAL_TIMEZONE_ALIASES.get(name, name)


def _get_zoneinfo(name: str) -> Optional[ZoneInfo]:
    """Validate and return a ZoneInfo, or None if invalid."""
    if not name:
        return None
    try:
        return ZoneInfo(name)
    except (KeyError, Exception) as exc:
        logger.warning(
            "Invalid timezone '%s': %s. Falling back to server local time.",
            name, exc,
        )
        return None


def get_timezone() -> Optional[ZoneInfo]:
    """Return the user's configured ZoneInfo, or None (meaning server-local).

    Resolved once and cached. Call ``reset_cache()`` after config changes.
    """
    global _cached_tz, _cached_tz_name, _cache_resolved
    if not _cache_resolved:
        _cached_tz_name = _resolve_timezone_name()
        _cached_tz = _get_zoneinfo(_cached_tz_name)
        _cache_resolved = True
    return _cached_tz


def reset_cache() -> None:
    """Clear cached timezone resolution so config/env changes take effect."""
    global _cached_tz, _cached_tz_name, _cache_resolved
    _cached_tz = None
    _cached_tz_name = None
    _cache_resolved = False


def now() -> datetime:
    """
    Return the current time as a timezone-aware datetime.

    If a valid timezone is configured, returns wall-clock time in that zone.
    Otherwise returns the server's local time (via ``astimezone()``).
    """
    tz = get_timezone()
    if tz is not None:
        return datetime.now(tz)
    # No timezone configured — use server-local (still tz-aware)
    return datetime.now().astimezone()


def _format_utc_offset(dt: datetime) -> str:
    """Return +HH:MM or -HH:MM for a timezone-aware datetime."""
    offset = dt.strftime("%z")
    if len(offset) == 5:
        return f"{offset[:3]}:{offset[3:]}"
    return offset or "local"


def format_current_time_context() -> str:
    """Return an API-only context line with exact local time for the model."""
    current = now()
    tz = get_timezone()
    if tz is not None and _cached_tz_name:
        tz_label = _cached_tz_name
    else:
        tz_label = current.tzname() or "server-local"

    from datetime import timedelta
    today_str = current.strftime('%A, %B %d, %Y')
    tomorrow_str = (current + timedelta(days=1)).strftime('%A, %B %d, %Y')
    yesterday_str = (current - timedelta(days=1)).strftime('%A, %B %d, %Y')

    post_midnight_hint = ""
    if 0 <= current.hour < 5:
        post_midnight_hint = (
            "⚠️ CRITICAL POST-MIDNIGHT CONTEXT:\n"
            f"The current local hour is {current.hour:02d}:{current.minute:02d} AM. Since it is past midnight, when the user says 'tomorrow' or 'today', they may "
            "be thinking in terms of their waking cycle (meaning 'this morning/later today' when they wake up). "
            "Please check both: the upcoming waking morning (today, calendar "
            f"{today_str}) AND the literal calendar tomorrow (tomorrow, calendar {tomorrow_str}). "
            "Be explicitly clear in your response about which day you are referring to (e.g. 'this morning, Saturday' vs 'tomorrow, Sunday').\n\n"
        )

    return (
        "Current local time: "
        f"{current.strftime('%Y-%m-%d %H:%M %A')} "
        f"{tz_label} ({_format_utc_offset(current)})\n"
        f"Today is {today_str}.\n"
        f"Tomorrow is {tomorrow_str}.\n"
        f"Yesterday was {yesterday_str}.\n\n"
        f"{post_midnight_hint}"
        "Use these values for relative dates and times unless the user "
        "explicitly gives another timezone. Always verify that calendar date numbers match the weekday names (e.g. Friday is May 22, Saturday is May 23, Sunday is May 24)."
    )

