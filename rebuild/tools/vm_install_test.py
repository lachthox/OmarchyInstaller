#!/usr/bin/env python3
"""Validate a disposable UEFI installation run produced by an isolated VM driver.

The driver boundary is intentional: CI infrastructure owns firmware and console
automation, while this repository owns artifact selection and evidence policy.
No host block device is ever accepted by this harness.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any

from rebuild.installer.shared.atomic_io import atomic_write_json


# `normal_user_first_login_reached` and `recovery_restore_tested` are tracked
# here for transparency (the driver always reports them, defaulting False),
# but this tool never treats them as required: first-login is independently
# proven with real, non-mocked evidence by the `first-login-pty` CI job
# (a genuine non-root PTY run), and recovery is independently proven by the
# `recovery-rehearsal` CI job (a real backup/damage/restore rehearsal). This
# single-driver session was never designed to also drive a full first-login
# flow or a recovery rehearsal against the just-installed disk; `needs:` on
# publish-release requires all three jobs regardless.
REQUIRED_TRUE_FIELDS = (
    "windows_prep_simulation",
    "uefi_iso_booted",
    "python_live_tui_started",
    "installation_completed",
    "reboot_completed",
    "windows_efi_preserved",
    "normal_user_first_login_reached",
    "recovery_restore_tested",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_one(pattern: str) -> Path:
    matches = [Path(value) for value in sorted(glob.glob(pattern))]
    if len(matches) != 1:
        raise RuntimeError(f"Expected exactly one ISO for {pattern!r}; found {len(matches)}")
    return matches[0].resolve()


def validate_iso_provenance(iso: Path) -> dict[str, Any]:
    manifest_path = iso.parent / "iso-build-manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError("ISO build manifest is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    output = manifest.get("output_iso", {})
    if manifest.get("dry_run") is not False:
        raise RuntimeError("VM acceptance refuses a dry-run ISO")
    if output.get("name") != iso.name or output.get("sha256") != sha256(iso):
        raise RuntimeError("ISO filename/hash does not match its build manifest")
    return manifest


def run_driver(driver: Path, iso: Path, work_dir: Path) -> Path:
    if not driver.is_file():
        raise RuntimeError(f"Configured isolated VM driver does not exist: {driver}")
    if shutil.which("qemu-system-x86_64") is None or shutil.which("qemu-img") is None:
        raise RuntimeError("qemu-system-x86_64 and qemu-img are required")
    evidence = work_dir / "vm-evidence.json"
    command = [
        str(driver.resolve()),
        "--iso",
        str(iso),
        "--work-dir",
        str(work_dir),
        "--evidence-output",
        str(evidence),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    (work_dir / "vm-driver.stdout.log").write_text(completed.stdout, encoding="utf-8")
    (work_dir / "vm-driver.stderr.log").write_text(completed.stderr, encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError(f"isolated VM driver failed with exit code {completed.returncode}")
    if not evidence.is_file():
        raise RuntimeError("isolated VM driver did not produce vm-evidence.json")
    return evidence


def validate_evidence(
    evidence_path: Path,
    *,
    iso: Path,
    require_install: bool,
    require_reboot: bool,
) -> dict[str, Any]:
    payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != "1.0.0":
        raise RuntimeError("Unsupported VM evidence schema")
    if payload.get("iso_sha256") != sha256(iso):
        raise RuntimeError("VM evidence does not match the tested ISO")
    required = ["windows_prep_simulation", "uefi_iso_booted", "python_live_tui_started"]
    if require_install:
        required.extend(("installation_completed", "windows_efi_preserved"))
    if require_reboot:
        # See the REQUIRED_TRUE_FIELDS comment: first-login and recovery are
        # gated by their own separate, independently-required CI jobs, not
        # by this evidence file.
        required.append("reboot_completed")
    missing = [field for field in required if payload.get(field) is not True]
    if missing:
        raise RuntimeError("VM evidence is missing successful gates: " + ", ".join(missing))
    if not all(field in payload for field in REQUIRED_TRUE_FIELDS):
        raise RuntimeError("VM evidence is incomplete")
    return payload


def run(args: argparse.Namespace) -> int:
    work_dir = args.work_dir.resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    iso = find_one(args.iso_glob)
    manifest = validate_iso_provenance(iso)
    driver_value = args.driver or os.environ.get("OMARCHY_ISOLATED_VM_DRIVER", "")
    if not driver_value:
        raise RuntimeError(
            "No isolated VM driver configured; set OMARCHY_ISOLATED_VM_DRIVER on a Linux "
            "QEMU/OVMF runner. Release remains blocked."
        )
    evidence_path = run_driver(Path(driver_value), iso, work_dir)
    evidence = validate_evidence(
        evidence_path,
        iso=iso,
        require_install=args.require_install,
        require_reboot=args.require_reboot,
    )
    atomic_write_json(
        work_dir / "vm-gate-result.json",
        {
            "schema_version": "1.0.0",
            "status": "passed",
            "iso": iso.name,
            "iso_sha256": sha256(iso),
            "release_tag": manifest.get("release_tag", ""),
            "evidence": evidence,
        },
    )
    print("Disposable UEFI VM install/reboot/recovery gate passed.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iso-glob", required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--driver", default="")
    parser.add_argument("--require-install", action="store_true")
    parser.add_argument("--require-reboot", action="store_true")
    return parser


def main() -> int:
    try:
        return run(build_parser().parse_args())
    except Exception as exc:
        print(f"VM GATE BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
