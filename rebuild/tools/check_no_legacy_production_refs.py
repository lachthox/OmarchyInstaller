#!/usr/bin/env python3
"""Fail CI when retired launch paths re-enter production code or workflows."""

from __future__ import annotations

import sys
from pathlib import Path


WORKSPACE = Path(__file__).resolve().parents[2]
PRODUCTION_ROOTS = (
    WORKSPACE / "rebuild" / "installer",
    WORKSPACE / "rebuild" / "assets",
    WORKSPACE / "rebuild" / "tools",
    WORKSPACE / ".github" / "workflows",
)
PRODUCTION_FILES = (WORKSPACE / "build-custom-iso.sh",)
FORBIDDEN = (
    "windows-prep" + ".ps1",
    "setup" + ".sh",
    "/opt/omarchy-" + "setup",
    "firstboot-" + "wrapper",
    "omarchy-" + "firstboot",
)
EXPECTED_WORKFLOWS = {"rebuild-ci.yml", "rebuild-release.yml"}


def iter_production_files() -> list[Path]:
    paths = list(PRODUCTION_FILES)
    for root in PRODUCTION_ROOTS:
        paths.extend(path for path in root.rglob("*") if path.is_file())
    return sorted(set(paths))


def find_violations() -> list[str]:
    violations: list[str] = []
    this_file = Path(__file__).resolve()
    for path in iter_production_files():
        if path.resolve() == this_file or "__pycache__" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for needle in FORBIDDEN:
            if needle in text:
                violations.append(f"{path.relative_to(WORKSPACE)}: contains {needle!r}")

    workflow_dir = WORKSPACE / ".github" / "workflows"
    actual = {path.name for path in workflow_dir.glob("*.yml")}
    if actual != EXPECTED_WORKFLOWS:
        violations.append(
            "workflow set must be exactly "
            f"{sorted(EXPECTED_WORKFLOWS)}, found {sorted(actual)}"
        )
    return violations


def main() -> int:
    violations = find_violations()
    if violations:
        print("Retired production path check failed:", file=sys.stderr)
        for violation in violations:
            print(f"- {violation}", file=sys.stderr)
        return 1
    print("Retired production path check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
