from pathlib import Path
import subprocess
import shutil

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SETUP_SCRIPT = REPO_ROOT / "setup-hermes.sh"


def _require_working_bash():
    if not shutil.which("bash"):
        pytest.skip("bash is not installed")
    probe = subprocess.run(["bash", "-c", "exit 0"], capture_output=True)
    if probe.returncode != 0:
        pytest.skip("bash is present but not usable in this environment")


def test_setup_hermes_script_is_valid_shell():
    _require_working_bash()
    result = subprocess.run(["bash", "-n", str(SETUP_SCRIPT)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_setup_hermes_script_has_termux_path():
    content = SETUP_SCRIPT.read_text(encoding="utf-8")

    assert "is_termux()" in content
    assert ".[termux]" in content
    assert "constraints-termux.txt" in content
    assert "$PREFIX/bin" in content
