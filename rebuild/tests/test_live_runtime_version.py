"""Live runtime version resolution + shipped compatibility floor regression tests.

Regression context: v0.1.9 booted with the hardcoded `0.1.0-dev` fallback while the
shipped plan template demanded a 1.0.0 minimum, so every real USB was blocked at
preflight even though CI passed (its drivers overrode `--runtime-version`).
"""

from __future__ import annotations

import json
from pathlib import Path

from rebuild.installer.main import (
    FALLBACK_RUNTIME_VERSION,
    resolve_runtime_version,
)
from rebuild.installer.shared.versioning import is_version_at_least


REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE_PATH = REPO_ROOT / "rebuild" / "assets" / "templates" / "plan.template.json"


def write_metadata(path: Path, payload: object) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_explicit_version_wins(tmp_path: Path) -> None:
    metadata = write_metadata(tmp_path / "build-metadata.json", {"release_version": "9.9.9"})
    assert resolve_runtime_version("2.0.0", metadata_path=metadata) == "2.0.0"


def test_resolves_release_version_from_build_metadata(tmp_path: Path) -> None:
    metadata = write_metadata(tmp_path / "build-metadata.json", {"release_version": "0.1.9"})
    assert resolve_runtime_version(None, metadata_path=metadata) == "0.1.9"


def test_missing_metadata_falls_back(tmp_path: Path) -> None:
    assert (
        resolve_runtime_version(None, metadata_path=tmp_path / "absent.json")
        == FALLBACK_RUNTIME_VERSION
    )


def test_malformed_metadata_falls_back(tmp_path: Path) -> None:
    broken = tmp_path / "build-metadata.json"
    broken.write_text("{not json", encoding="utf-8")
    assert resolve_runtime_version(None, metadata_path=broken) == FALLBACK_RUNTIME_VERSION


def test_blank_release_version_falls_back(tmp_path: Path) -> None:
    metadata = write_metadata(tmp_path / "build-metadata.json", {"release_version": "  "})
    assert resolve_runtime_version(None, metadata_path=metadata) == FALLBACK_RUNTIME_VERSION


def test_template_minimums_accept_current_release_line(tmp_path: Path) -> None:
    """The shipped template floors must be clearable by a real same-tag pairing.

    Uses the actual current release line (0.1.x) as resolved from ISO build
    metadata; bump this version alongside any intentional floor increase.
    """
    compatibility = json.loads(TEMPLATE_PATH.read_text(encoding="utf-8"))["compatibility"]
    metadata = write_metadata(tmp_path / "build-metadata.json", {"release_version": "0.1.9"})
    live_runtime_version = resolve_runtime_version(None, metadata_path=metadata)

    assert is_version_at_least(
        live_runtime_version, compatibility["minimum_live_runtime_version"]
    )
    assert is_version_at_least("0.1.9.0", compatibility["minimum_windows_prep_version"])
