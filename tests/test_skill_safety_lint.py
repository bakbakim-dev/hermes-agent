from __future__ import annotations

import re
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SKILLS_ROOT = REPO_ROOT / "skills"
WEBSITE_DOCS_ROOT = REPO_ROOT / "website" / "docs" / "user-guide" / "skills"

DISALLOWED_DEFAULT_SKILL_PATTERNS = [
    re.compile(r"\bbypass(?:ing)? safety filters\b", re.IGNORECASE),
    re.compile(r"\bpersistent jailbreak(?:ing)?\b", re.IGNORECASE),
    re.compile(r"\bauto[- ]?jailbreak\b", re.IGNORECASE),
    re.compile(r"\buncensored model\b", re.IGNORECASE),
    re.compile(r"\bunrestricted ai assistant\b", re.IGNORECASE),
]


def test_default_bundled_skills_do_not_ship_operational_jailbreak_instructions():
    offenders: list[str] = []
    for skill_path in DEFAULT_SKILLS_ROOT.rglob("*"):
        if not skill_path.is_file():
            continue
        if skill_path.suffix.lower() not in {".md", ".py", ".json", ".yaml", ".yml"}:
            continue
        if ".archive" in skill_path.parts:
            continue
        text = skill_path.read_text(encoding="utf-8", errors="ignore")
        matched = [
            pattern.pattern
            for pattern in DISALLOWED_DEFAULT_SKILL_PATTERNS
            if pattern.search(text)
        ]
        if matched:
            offenders.append(f"{skill_path.relative_to(REPO_ROOT)}: {', '.join(matched)}")

    assert offenders == []


def test_public_skill_docs_do_not_advertise_operational_jailbreak_workflows():
    if not WEBSITE_DOCS_ROOT.exists():
        return
    offenders: list[str] = []
    for doc_path in WEBSITE_DOCS_ROOT.rglob("*.md"):
        text = doc_path.read_text(encoding="utf-8", errors="ignore")
        matched = [
            pattern.pattern
            for pattern in DISALLOWED_DEFAULT_SKILL_PATTERNS
            if pattern.search(text)
        ]
        if matched:
            offenders.append(f"{doc_path.relative_to(REPO_ROOT)}: {', '.join(matched)}")

    assert offenders == []
