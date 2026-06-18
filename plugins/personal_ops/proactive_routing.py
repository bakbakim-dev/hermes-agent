"""Proactive Routing Hook - Self-Awareness Enhancement for Dirdir.

Intercepts incoming user queries containing personal keywords (e.g. goals, workouts)
and automatically queries personal_todoist to inject fresh live task contexts.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional
from plugins.personal_ops.temp_personal_ops_tools import handle_todoist

logger = logging.getLogger(__name__)

# Personal keywords that trigger a proactive check of user operations / Todoist tasks
PERSONAL_KEYWORDS = {
    "workout", "workouts", "gym", "goal", "goals",
    "routine", "routines", "schedule", "schedules",
    "v-taper", "vtaper", "upper", "lower", "exercise", "exercises"
}


def _coerce_mapping(value: Any) -> Dict[str, Any]:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:
            return {"raw": value}
        return _coerce_mapping(parsed)
    if isinstance(value, dict):
        return dict(value)
    return {}

def proactive_personal_query_hook(
    session_id: str,
    user_message: str,
    **kwargs: Any
) -> Optional[str]:
    """Pre-LLM call hook to proactively query and inject live Todoist workouts and goals context."""
    if not isinstance(user_message, str) or not user_message.strip():
        return None

    # Normalise user message and check for keywords
    msg_lower = user_message.lower()
    matched_keywords = [kw for kw in PERSONAL_KEYWORDS if kw in msg_lower]

    if not matched_keywords:
        return None

    logger.info("Proactive personal query hook triggered by keywords: %s", matched_keywords)

    try:
        # Request all tasks labeled with '@MensUpperLower' or due today/overdue
        args = {
            "action": "list_tasks",
            "filter": "@MensUpperLower | today | overdue"
        }
        res_raw = handle_todoist(args)
        if not res_raw:
            return None

        # Parse tool result (either raw dict or json string)
        res = _coerce_mapping(res_raw)

        # If wrapped inside tool_result, unpack it
        if "result" in res:
            res = _coerce_mapping(res["result"])

        success = res.get("success") or res.get("ok")
        if not success:
            logger.warning("Todoist query in proactive hook was not successful: %s", res.get("error"))
            return None

        # Try to use the pre-rendered formatted list from Todoist tool
        formatted_list = res.get("formatted_list") or ""
        tasks = res.get("tasks") or []

        if not formatted_list and not tasks:
            return (
                "<personal-operation-context>\n"
                "[System Note: Checked your Todoist schedule and found no active tasks under @MensUpperLower, today, or overdue.]\n"
                "</personal-operation-context>"
            )

        if not formatted_list:
            # Fallback manual formatting
            formatted_tasks = []
            for task in tasks:
                title = task.get("content") or task.get("title") or "Unnamed Task"
                labels = task.get("labels") or []
                due = task.get("due") or {}
                due_str = due.get("string") or due.get("date") or "No Due Date"
                priority = task.get("priority", 1)
                prio_stars = "⭐" * priority
                formatted_tasks.append(
                    f"- **{title}** (Due: {due_str}) {prio_stars} [Labels: {', '.join(labels)}]"
                )
            formatted_list = "\n".join(formatted_tasks)

        # Wrap in a robust system note to be injected as turn context in the user message
        injected_context = (
            "<personal-operation-context>\n"
            "[System Note: Below is live, verified context fetched proactively from your personal Todoist integration "
            "because your message asked about personal workouts, goals, or routines. Use this to provide highly accurate, "
            "contextual answers regarding workouts and goals. Do not declare you have no information or access to Todoist.]\n\n"
            f"**Your Active Tasks, Workouts & Goals:**\n"
            f"{formatted_list}\n"
            "</personal-operation-context>"
        )
        return injected_context

    except Exception as exc:
        logger.error("Error in proactive personal query hook: %s", exc, exc_info=True)
        return None
