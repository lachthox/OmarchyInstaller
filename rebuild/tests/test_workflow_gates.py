from __future__ import annotations

from pathlib import Path


WORKSPACE = Path(__file__).resolve().parents[2]


def test_no_legacy_self_publishing_workflow_exists() -> None:
    assert not (WORKSPACE / ".github/workflows/build-iso.yml").exists()
    assert {path.name for path in (WORKSPACE / ".github/workflows").glob("*.yml")} == {
        "rebuild-ci.yml",
        "rebuild-release.yml",
    }


def test_release_publish_requires_every_safety_gate() -> None:
    workflow = (WORKSPACE / ".github/workflows/rebuild-release.yml").read_text(encoding="utf-8")
    publish = workflow.split("  publish-release:", 1)[1]
    required = (
        "quality", "shell", "contracts", "first-login-pty", "build-iso",
        "build-windows-exe", "vm-install-reboot",
    )
    needs_line = next(line for line in publish.splitlines() if "needs:" in line)
    assert all(job in needs_line for job in required)
    assert "if: ${{ inputs.publish }}" in publish
    assert "--publish --publish-only" in publish
    assert "--require-install --require-reboot" in workflow


def test_ci_covers_quality_shell_contracts_and_windows_package() -> None:
    workflow = (WORKSPACE / ".github/workflows/rebuild-ci.yml").read_text(encoding="utf-8")
    for required in (
        "python -m ruff", "python -m mypy", "python -m pytest", "shellcheck",
        "bats rebuild/tests-shell", "archinstall-4.4-1", "build_windows_exe.py",
        "check_no_legacy_production_refs.py",
    ):
        assert required in workflow
