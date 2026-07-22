from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from rebuild.tools.vm_install_test import validate_evidence, validate_iso_provenance


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_vm_gate_rejects_dry_run_iso(tmp_path: Path) -> None:
    iso = tmp_path / "test-omarchy-auto.iso"
    iso.write_bytes(b"iso")
    (tmp_path / "iso-build-manifest.json").write_text(
        json.dumps({"dry_run": True, "output_iso": {"name": iso.name, "sha256": _sha(iso)}})
    )
    with pytest.raises(RuntimeError, match="dry-run"):
        validate_iso_provenance(iso)


def test_vm_gate_requires_install_reboot_and_matching_iso(tmp_path: Path) -> None:
    iso = tmp_path / "test.iso"
    iso.write_bytes(b"real iso")
    evidence = {
        "schema_version": "1.0.0",
        "iso_sha256": _sha(iso),
        "windows_prep_simulation": True,
        "uefi_iso_booted": True,
        "python_live_tui_started": True,
        "installation_completed": True,
        "reboot_completed": True,
        "windows_efi_preserved": True,
        # This single-driver session never drives a first-login flow or a
        # recovery rehearsal itself -- those are proven by the separate
        # first-login-pty and recovery-rehearsal CI jobs -- so they're
        # correctly False here and validate_evidence must not require them.
        "normal_user_first_login_reached": False,
        "recovery_restore_tested": False,
    }
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(evidence), encoding="utf-8")
    assert validate_evidence(path, iso=iso, require_install=True, require_reboot=True) == evidence
    evidence["reboot_completed"] = False
    path.write_text(json.dumps(evidence), encoding="utf-8")
    with pytest.raises(RuntimeError, match="reboot_completed"):
        validate_evidence(path, iso=iso, require_install=True, require_reboot=True)
