from __future__ import annotations

import argparse
import importlib.util
import subprocess
from pathlib import Path


def _has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def build_pytest_command(
    paths: list[str],
    *,
    has_xdist: bool | None = None,
    has_timeout: bool | None = None,
) -> list[str]:
    if has_xdist is None:
        has_xdist = _has_module("xdist")
    if has_timeout is None:
        has_timeout = _has_module("pytest_timeout")
    cmd = ["pytest", "-m", "not integration"]
    if has_xdist:
        cmd.extend(["-n", "auto"])
    if has_timeout:
        cmd.extend(["--timeout=30", "--timeout-method=signal"])
    cmd.extend(paths or ["tests"])
    return cmd


def check_pytest_preflight() -> dict:
    missing = []
    if not _has_module("xdist"):
        missing.append("pytest-xdist")
    if not _has_module("pytest_timeout"):
        missing.append("pytest-timeout")
    if missing:
        return {
            "ok": True,
            "message": "Optional pytest plugins missing; raw pytest still works, runner will skip advanced flags: "
            + ", ".join(missing),
            "missing_optional": missing,
        }
    return {"ok": True, "message": "pytest preflight ok", "missing_optional": []}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Hermes tests with optional plugin-aware flags.")
    parser.add_argument("paths", nargs="*", default=["tests"])
    args = parser.parse_args(argv)
    cmd = build_pytest_command([str(Path(p)) for p in args.paths])
    return subprocess.call(cmd)
