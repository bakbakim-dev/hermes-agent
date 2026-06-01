from __future__ import annotations

from plugins.personal_ops.tool_router import route_tool_call


def test_unknown_tool_fails_closed_even_when_name_looks_harmless():
    decision = route_tool_call(
        tool_name="new_calendar_mutator",
        intent_text="show my tasks today",
        enforce=True,
    )

    assert decision.tool_class == "unclassified"
    assert decision.allowed is False
    assert decision.approval_required is True


def test_known_low_risk_personal_ops_tool_still_allowed():
    decision = route_tool_call(
        tool_name="personal_runtime",
        intent_text="show my operating status",
        enforce=True,
    )

    assert decision.allowed is True
    assert decision.approval_required is False
