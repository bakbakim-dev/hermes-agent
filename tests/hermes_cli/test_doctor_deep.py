from __future__ import annotations


def test_run_deep_checks_returns_truth_and_safety_checks(monkeypatch):
    from hermes_cli import doctor

    monkeypatch.setattr(
        doctor,
        "build_capability_matrix",
        lambda: [{"id": "toolset:terminal", "enabled": True}],
        raising=False,
    )
    monkeypatch.setattr(
        doctor,
        "audit_plugin_permissions",
        lambda: {"ok": True, "issues": []},
        raising=False,
    )
    monkeypatch.setattr(
        doctor,
        "check_pytest_preflight",
        lambda: {"ok": True, "message": "pytest preflight ok"},
        raising=False,
    )
    monkeypatch.setattr(
        doctor,
        "check_source_archive_hygiene",
        lambda: {"ok": True, "message": "source archive hygiene ok"},
        raising=False,
    )

    checks = doctor.run_deep_checks()
    ids = {check["id"] for check in checks}

    assert "capability_matrix" in ids
    assert "plugin_permissions" in ids
    assert "pytest_preflight" in ids
    assert "source_archive_hygiene" in ids
