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
)


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
    ctx.register_command(
        "location",
        handler=handle_location_slash_command,
        description="Update your presence location manually (e.g. /location away)",
    )
