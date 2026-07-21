from __future__ import annotations

from pathlib import Path

from rebuild.tools.check_no_legacy_production_refs import (
    EXPECTED_WORKFLOWS,
    WORKSPACE,
    find_violations,
)


def test_retired_paths_are_absent_from_production() -> None:
    assert find_violations() == []


def test_only_one_ci_and_one_release_workflow_remain() -> None:
    workflows = WORKSPACE / ".github" / "workflows"
    assert {path.name for path in workflows.glob("*.yml")} == EXPECTED_WORKFLOWS


def test_archived_shell_entrypoints_are_inert_text() -> None:
    archive = Path(WORKSPACE / "legacy" / "unsupported")
    assert (archive / "setup.sh.txt").is_file()
    assert (archive / "windows-prep.ps1.txt").is_file()
    assert not list(archive.glob("*.sh"))
    assert not list(archive.glob("*.ps1"))
