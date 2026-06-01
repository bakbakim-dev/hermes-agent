from __future__ import annotations

import tomllib
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_pyproject_default_pytest_addopts_do_not_require_optional_plugins():
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    addopts = data["tool"]["pytest"]["ini_options"].get("addopts", "")
    assert "-n" not in addopts
    assert "--timeout" not in addopts


def test_run_tests_adds_optional_parallel_and_timeout_flags_only_when_available():
    from scripts.run_tests import build_pytest_command

    plain = build_pytest_command(["tests"], has_xdist=False, has_timeout=False)
    assert plain == ["pytest", "-m", "not integration", "tests"]

    rich = build_pytest_command(["tests"], has_xdist=True, has_timeout=True)
    assert rich[:3] == ["pytest", "-m", "not integration"]
    assert "-n" in rich
    assert "--timeout=30" in rich
    assert "--timeout-method=signal" in rich


def test_conftest_exposes_opt_in_thread_leak_check():
    conftest = (REPO_ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")
    assert "HERMES_TEST_LEAK_CHECK" in conftest
    assert "leaked non-daemon threads" in conftest
