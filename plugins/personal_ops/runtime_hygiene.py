"""Runtime hygiene helpers for long-lived personal-ops daemons."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Iterable


DEFAULT_MAX_LOG_BYTES = int(os.getenv("HERMES_RUNTIME_LOG_MAX_BYTES", str(2 * 1024 * 1024)))
DEFAULT_BACKUP_COUNT = int(os.getenv("HERMES_RUNTIME_LOG_BACKUP_COUNT", "1"))
MANAGED_RUNTIME_LOGS = ("activitywatch_forwarder.log",)


def _backup_path(path: Path, index: int) -> Path:
    return path.with_name(f"{path.name}.{index}")


def cap_large_runtime_log(
    log_path: Path,
    *,
    max_bytes: int = DEFAULT_MAX_LOG_BYTES,
    backup_count: int = DEFAULT_BACKUP_COUNT,
) -> Dict[str, Any]:
    """Rotate a runtime log when it grows beyond ``max_bytes``."""
    path = Path(log_path)
    result: Dict[str, Any] = {
        "path": str(path),
        "rotated": False,
        "size_bytes": 0,
        "backup": None,
        "error": None,
    }
    try:
        backup_count = max(1, int(backup_count))
        for stale_index in range(backup_count + 1, backup_count + 20):
            stale = _backup_path(path, stale_index)
            if stale.exists():
                stale.unlink()

        if not path.exists() or not path.is_file():
            return result
        size = path.stat().st_size
        result["size_bytes"] = size
        if size <= max_bytes:
            return result

        path.parent.mkdir(parents=True, exist_ok=True)
        oldest = _backup_path(path, backup_count)
        if oldest.exists():
            oldest.unlink()
        for index in range(backup_count - 1, 0, -1):
            src = _backup_path(path, index)
            if src.exists():
                src.replace(_backup_path(path, index + 1))
        backup = _backup_path(path, 1)
        path.replace(backup)
        path.touch()
        result["rotated"] = True
        result["backup"] = str(backup)
        return result
    except OSError as exc:
        result["error"] = str(exc)
        return result


def maintain_runtime_logs(
    hermes_home: Path,
    *,
    max_bytes: int = DEFAULT_MAX_LOG_BYTES,
    backup_count: int = DEFAULT_BACKUP_COUNT,
    log_names: Iterable[str] = MANAGED_RUNTIME_LOGS,
) -> Dict[str, Any]:
    """Apply runtime log caps under ``hermes_home`` and return a summary."""
    home = Path(hermes_home)
    results = [
        cap_large_runtime_log(home / name, max_bytes=max_bytes, backup_count=backup_count)
        for name in log_names
    ]
    return {
        "success": not any(item.get("error") for item in results),
        "rotated_count": sum(1 for item in results if item.get("rotated")),
        "results": results,
    }
