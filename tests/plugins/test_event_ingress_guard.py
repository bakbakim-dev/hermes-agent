from __future__ import annotations

from plugins.personal_ops.event_ingress_guard import guard_unverified_event


def test_ios_gym_event_without_location_proof_is_suppressed_before_runtime():
    result = guard_unverified_event(
        {
            "event_type": "gym.arrived",
            "source": "ios-shortcut",
            "payload": {"location": "golds_gym"},
        }
    )

    assert result is not None
    assert result["handled"] is True
    assert result["logged"] is False
    assert result["sent"] is False
    assert result["suppressed_reason"] == "unverified_ios_shortcut"
    assert "not logged" in result["message"].lower()


def test_ios_gym_event_with_location_proof_reaches_runtime():
    result = guard_unverified_event(
        {
            "event_type": "gym.left",
            "source": "ios-shortcut",
            "payload": {"verified_location": "1"},
        }
    )

    assert result is None


def test_non_gym_events_are_not_blocked_by_gym_guard():
    result = guard_unverified_event(
        {
            "event_type": "desktop_unlocked",
            "source": "ios-shortcut",
            "payload": {},
        }
    )

    assert result is None
