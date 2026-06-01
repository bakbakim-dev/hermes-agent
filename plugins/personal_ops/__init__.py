from __future__ import annotations

from .temp_personal_ops_tools import (
    ADAPTIVE_COMPANION_SCHEMA,
    CLICKUP_SCHEMA,
    FOCUS_GUARD_SCHEMA,
    RUNTIME_SCHEMA,
    SECURITY_SCHEMA,
    TODOIST_SCHEMA,
    TWILIO_SCHEMA,
    WEATHER_SCHEMA,
    handle_adaptive_companion,
    handle_clickup,
    handle_focus_guard,
    handle_runtime,
    handle_security,
    handle_todoist,
    handle_twilio,
    handle_weather,
    on_post_approval_response,
    on_pre_approval_request,
    handle_location_slash_command,
    handle_briefing_slash_command,
)
from .gym_attendance import handle_gym_slash_command
from .proactive_routing import proactive_personal_query_hook
from .tool_router import pre_tool_call_router


def register(ctx) -> None:
    ctx.register_tool("personal_todoist", "personal-ops", TODOIST_SCHEMA, handle_todoist, emoji="✅")
    ctx.register_tool("personal_focus_guard", "personal-ops", FOCUS_GUARD_SCHEMA, handle_focus_guard, emoji="🎯")
    ctx.register_tool("personal_runtime", "personal-ops", RUNTIME_SCHEMA, handle_runtime, emoji="🧰")
    ctx.register_tool(
        "personal_adaptive_companion",
        "personal-ops",
        ADAPTIVE_COMPANION_SCHEMA,
        handle_adaptive_companion,
        emoji="🧭",
    )
    ctx.register_tool("personal_clickup", "personal-ops", CLICKUP_SCHEMA, handle_clickup, emoji="📋")
    ctx.register_tool("personal_twilio", "personal-ops", TWILIO_SCHEMA, handle_twilio, emoji="📱")
    ctx.register_tool("personal_weather", "personal-ops", WEATHER_SCHEMA, handle_weather, emoji="⛅")
    ctx.register_tool("personal_security", "personal-ops", SECURITY_SCHEMA, handle_security, emoji="🛡️")
    ctx.register_hook("pre_approval_request", on_pre_approval_request)
    ctx.register_hook("post_approval_response", on_post_approval_response)
    ctx.register_hook("pre_llm_call", proactive_personal_query_hook)
    ctx.register_hook("pre_tool_call", pre_tool_call_router)
    ctx.register_command(
        "location",
        handler=handle_location_slash_command,
        description="Update your presence location manually (e.g. /location away)",
    )
    ctx.register_command(
        "show_hidden_tomorrow",
        handler=lambda args: handle_briefing_slash_command("show_hidden_tomorrow", args),
        description="Show hidden/excluded tasks for tomorrow",
    )
    ctx.register_command(
        "show_task_debt",
        handler=lambda args: handle_briefing_slash_command("show_task_debt", args),
        description="Show active overdue task debt and stale backlog",
    )
    ctx.register_command(
        "why_suppressed",
        handler=lambda args: handle_briefing_slash_command("why_suppressed", args),
        description="Explain why items were suppressed/hidden from your briefing workload",
    )
    ctx.register_command(
        "health_score",
        handler=lambda args: handle_briefing_slash_command("health_score", args),
        description="Compute real-time Todoist system health score and repair advice",
    )
    ctx.register_command(
        "entropy_check",
        handler=lambda args: handle_briefing_slash_command("entropy_check", args),
        description="Run detailed Todoist entropy audit for duplicates, stale, and postponed tasks",
    )
    ctx.register_command(
        "gym",
        handler=handle_gym_slash_command,
        description="Log gym arrival/departure and monthly gym attendance reports",
        args_hint="arrived | left | report [YYYY-MM] | shortcuts",
    )
