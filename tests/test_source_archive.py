from __future__ import annotations

import importlib.util
import stat
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_SCRIPT = REPO_ROOT / "scripts" / "create_source_archive.py"


def _load_archive_script():
    spec = importlib.util.spec_from_file_location("create_source_archive", ARCHIVE_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _zip_mode(info: zipfile.ZipInfo) -> int:
    return (info.external_attr >> 16) & 0o777


def test_source_archive_excludes_sensitive_and_generated_files_and_uses_posix_names(tmp_path):
    script = _load_archive_script()
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".env").write_text("SECRET=do-not-ship\n", encoding="utf-8")
    (root / ".env.example").write_text("SECRET=\n", encoding="utf-8")
    (root / "hermes").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    (root / "scripts").mkdir()
    (root / "scripts" / "install.sh").write_text("#!/usr/bin/env sh\n", encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "app.py").write_text("print('ok')\n", encoding="utf-8")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "junk.js").write_text("ignored\n", encoding="utf-8")
    (root / "run_agent.py.bak-20260516093340").write_text("ignored\n", encoding="utf-8")

    out = tmp_path / "source.zip"
    script.create_source_archive(root=root, output=out)

    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        assert all("\\" not in name for name in names)
        assert ".env" not in names
        assert ".env.example" in names
        assert "src/app.py" in names
        assert "node_modules/junk.js" not in names
        assert "run_agent.py.bak-20260516093340" not in names
        assert stat.S_IMODE(_zip_mode(zf.getinfo("hermes"))) == 0o755
        assert stat.S_IMODE(_zip_mode(zf.getinfo("scripts/install.sh"))) == 0o755
