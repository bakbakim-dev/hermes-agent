from __future__ import annotations

from pathlib import Path


def test_cap_large_runtime_log_rotates_file(tmp_path: Path) -> None:
    from plugins.personal_ops.runtime_hygiene import cap_large_runtime_log

    log_path = tmp_path / "activitywatch_forwarder.log"
    log_path.write_bytes(b"a" * 120)

    result = cap_large_runtime_log(log_path, max_bytes=50, backup_count=2)

    assert result["rotated"] is True
    assert log_path.exists()
    assert log_path.stat().st_size == 0
    assert (tmp_path / "activitywatch_forwarder.log.1").stat().st_size == 120


def test_runtime_log_hygiene_ignores_small_logs(tmp_path: Path) -> None:
    from plugins.personal_ops.runtime_hygiene import maintain_runtime_logs

    log_path = tmp_path / "activitywatch_forwarder.log"
    log_path.write_bytes(b"small")

    result = maintain_runtime_logs(tmp_path, max_bytes=50, backup_count=2)

    assert result["rotated_count"] == 0
    assert log_path.read_bytes() == b"small"
