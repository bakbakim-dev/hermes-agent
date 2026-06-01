"""Small Telegram capture-bot callback bridge for Hermes personal ops.

The capture bot is intentionally thin: callback buttons are converted into
Hermes runtime events, and the personal-ops runtime owns the learning/update
logic.
"""

from __future__ import annotations

import json
from typing import Any

from plugins.personal_ops import temp_personal_ops_tools as tools


async def _ensure_allowed(update: Any) -> bool:
    return True


async def _handle_callback(update: Any, context: Any = None) -> None:
    query = getattr(update, "callback_query", None)
    if query is None:
        return
    if not await _ensure_allowed(update):
        try:
            await query.answer()
        except Exception:
            pass
        return

    data = str(getattr(query, "data", "") or "")
    if not data.startswith("hermes_feedback:"):
        try:
            await query.answer()
        except Exception:
            pass
        return

    feedback = data.split(":", 1)[1].strip().lower() or "unknown"
    msg_obj = getattr(query, "message", None)
    payload = {
        "action": "event_ingest",
        "event_type": "telegram_feedback",
        "source": "telegram-callback",
        "message_id": str(getattr(msg_obj, "message_id", "") or ""),
        "feedback": feedback,
    }
    result_raw = tools.handle_runtime(payload)
    try:
        result = json.loads(result_raw) if isinstance(result_raw, str) else result_raw
    except Exception:
        result = {"success": False}

    try:
        await query.answer()
    except Exception:
        pass
    try:
        await query.edit_message_text(
            "Captured feedback." if result.get("success", True) else "Feedback capture failed."
        )
    except Exception:
        pass
