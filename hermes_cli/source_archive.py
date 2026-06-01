from __future__ import annotations

import argparse
import fnmatch
import os
import stat
import zipfile
from pathlib import Path


EXCLUDED_DIR_NAMES = {
    ".git",
    ".hg",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "venv",
}

EXCLUDED_FILE_NAMES = {
    ".env",
    ".env.local",
    ".env.production",
    ".envrc",
}

EXCLUDED_GLOBS = (
    "*.bak",
    "*.bak-*",
    "*.log",
    "*.pyc",
    "*.pyo",
    "*.tmp",
    "*~",
)

EXECUTABLE_ARCHIVE_PATHS = {
    "hermes",
    "setup-hermes.sh",
    "scripts/install.sh",
}


def _should_exclude(path: Path, root: Path) -> bool:
    rel = path.relative_to(root)
    if any(part in EXCLUDED_DIR_NAMES for part in rel.parts):
        return True
    if path.name in EXCLUDED_FILE_NAMES:
        return True
    return any(fnmatch.fnmatch(path.name, pattern) for pattern in EXCLUDED_GLOBS)


def _archive_name(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _zip_info_for(path: Path, arcname: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo.from_file(path, arcname)
    mode = path.stat().st_mode
    if arcname in EXECUTABLE_ARCHIVE_PATHS or arcname.endswith(".sh"):
        mode = (mode & ~0o777) | 0o755
    elif path.is_file():
        mode = (mode & ~0o777) | 0o644
    info.external_attr = (stat.S_IMODE(mode) & 0xFFFF) << 16
    return info


def iter_source_files(root: Path):
    root = root.resolve()
    for current, dirnames, filenames in os.walk(root):
        current_path = Path(current)
        dirnames[:] = sorted(
            name
            for name in dirnames
            if not _should_exclude(current_path / name, root)
        )
        for filename in sorted(filenames):
            path = current_path / filename
            if _should_exclude(path, root):
                continue
            try:
                if path.is_file():
                    yield path
            except OSError:
                continue


def create_source_archive(*, root: Path, output: Path) -> Path:
    root = root.resolve()
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for path in iter_source_files(root):
            if path.resolve() == output:
                continue
            arcname = _archive_name(path, root)
            zf.writestr(_zip_info_for(path, arcname), path.read_bytes())
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a clean Hermes source ZIP.")
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Repository root to archive.")
    parser.add_argument("--output", type=Path, required=True, help="Output .zip path.")
    args = parser.parse_args(argv)
    created = create_source_archive(root=args.root, output=args.output)
    print(created)
    return 0
