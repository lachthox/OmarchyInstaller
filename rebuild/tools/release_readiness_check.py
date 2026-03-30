#!/usr/bin/env python3
"""Validate release-readiness gates that combine artifact and operational evidence."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ALLOWED_LAUNCHER_POLICIES = {"python-only", "python-then-legacy", "legacy-only"}
REQUIRED_RELEASE_POLICY = "python-then-legacy"

REQUIRED_HARDWARE_CASES = (
    "uefi_nvme_desktop",
    "uefi_laptop_secure_boot_disabled",
    "uefi_dual_disk_nonzero_target",
)

REQUIRED_FIRSTBOOT_CHECKS = (
    "firstboot_service_ran_once",
    "boot_guardian_service_healthy",
    "completion_marker_written",
)


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _find_single(path: Path, pattern: str) -> Path:
    matches = sorted(path.rglob(pattern))
    if not matches:
        raise RuntimeError(f"Missing required file pattern under {path}: {pattern}")
    return matches[0]


def _status_is_pass(payload: Any) -> bool:
    if isinstance(payload, dict):
        return str(payload.get("status", "")).strip().lower() == "pass"
    return str(payload).strip().lower() == "pass"


def check_release_artifact_policy(artifact_dir: Path) -> tuple[list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []
    details: dict[str, Any] = {}

    try:
        manifest_path = _find_single(artifact_dir, "windows-exe-build-manifest.json")
    except RuntimeError as exc:
        return [str(exc)], warnings, details

    payload = _read_json(manifest_path)
    packaging_inputs = payload.get("packaging_inputs", {}) if isinstance(payload, dict) else {}
    policy = str(packaging_inputs.get("launcher_default_policy", "")).strip().lower()

    details["manifest_path"] = str(manifest_path)
    details["launcher_default_policy"] = policy

    if policy not in ALLOWED_LAUNCHER_POLICIES:
        errors.append(
            f"Invalid launcher_default_policy '{policy}' in {manifest_path}; allowed={sorted(ALLOWED_LAUNCHER_POLICIES)}"
        )
        return errors, warnings, details

    if policy != REQUIRED_RELEASE_POLICY:
        errors.append(
            f"Release policy mismatch: expected '{REQUIRED_RELEASE_POLICY}', got '{policy}' in {manifest_path}"
        )

    return errors, warnings, details


def check_hardware_report(report_path: Path) -> tuple[list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []
    details: dict[str, Any] = {"report_path": str(report_path)}

    payload = _read_json(report_path)
    cases = payload.get("cases", {}) if isinstance(payload, dict) else {}
    if not isinstance(cases, dict):
        return [f"Invalid hardware report shape in {report_path}: expected object at .cases"], warnings, details

    case_results: dict[str, str] = {}
    for case_name in REQUIRED_HARDWARE_CASES:
        case_payload = cases.get(case_name)
        if case_payload is None:
            errors.append(f"Missing hardware matrix case '{case_name}' in {report_path}")
            continue
        status = str(case_payload.get("status", "")).strip().lower() if isinstance(case_payload, dict) else ""
        case_results[case_name] = status
        if status != "pass":
            errors.append(f"Hardware matrix case '{case_name}' is '{status or 'unknown'}' (must be pass)")
    details["cases"] = case_results

    return errors, warnings, details


def check_firstboot_report(report_path: Path) -> tuple[list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []
    details: dict[str, Any] = {"report_path": str(report_path)}

    payload = _read_json(report_path)
    checks = payload.get("checks", {}) if isinstance(payload, dict) else {}
    if not isinstance(checks, dict):
        return [f"Invalid firstboot report shape in {report_path}: expected object at .checks"], warnings, details

    check_results: dict[str, str] = {}
    for check_name in REQUIRED_FIRSTBOOT_CHECKS:
        check_payload = checks.get(check_name)
        if check_payload is None:
            errors.append(f"Missing firstboot check '{check_name}' in {report_path}")
            continue
        status = str(check_payload.get("status", "")).strip().lower() if isinstance(check_payload, dict) else ""
        check_results[check_name] = status
        if status != "pass":
            errors.append(f"Firstboot check '{check_name}' is '{status or 'unknown'}' (must be pass)")
    details["checks"] = check_results

    return errors, warnings, details


def audit_release_readiness(
    *,
    artifact_dir: Path | None,
    hardware_report: Path | None,
    firstboot_report: Path | None,
    require_all: bool,
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    checks: dict[str, Any] = {}

    if artifact_dir is None:
        message = "Artifact directory not provided; release policy check skipped"
        if require_all:
            errors.append(message)
        else:
            warnings.append(message)
    else:
        check_errors, check_warnings, details = check_release_artifact_policy(artifact_dir)
        errors.extend(check_errors)
        warnings.extend(check_warnings)
        checks["release_artifact_policy"] = details

    if hardware_report is None:
        message = "Hardware matrix report not provided"
        if require_all:
            errors.append(message)
        else:
            warnings.append(message)
    else:
        check_errors, check_warnings, details = check_hardware_report(hardware_report)
        errors.extend(check_errors)
        warnings.extend(check_warnings)
        checks["hardware_matrix"] = details

    if firstboot_report is None:
        message = "Firstboot validation report not provided"
        if require_all:
            errors.append(message)
        else:
            warnings.append(message)
    else:
        check_errors, check_warnings, details = check_firstboot_report(firstboot_report)
        errors.extend(check_errors)
        warnings.extend(check_warnings)
        checks["firstboot_validation"] = details

    return {
        "schema_version": "1.0.0",
        "generated_at_utc": _utc_now(),
        "can_proceed": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "checks": checks,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit release-readiness gates.")
    parser.add_argument("--artifact-dir", type=Path, default=None, help="Release artifact directory to inspect.")
    parser.add_argument("--hardware-report", type=Path, default=None, help="Completed hardware matrix report JSON.")
    parser.add_argument("--firstboot-report", type=Path, default=None, help="Completed firstboot validation report JSON.")
    parser.add_argument("--require-all", action="store_true", help="Fail when any expected input report is missing.")
    parser.add_argument("--output", type=Path, default=None, help="Optional path to write JSON audit output.")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    try:
        result = audit_release_readiness(
            artifact_dir=args.artifact_dir.resolve() if args.artifact_dir is not None else None,
            hardware_report=args.hardware_report.resolve() if args.hardware_report is not None else None,
            firstboot_report=args.firstboot_report.resolve() if args.firstboot_report is not None else None,
            require_all=args.require_all,
        )
    except Exception as exc:  # pragma: no cover - command line wrapper
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    payload = json.dumps(result, indent=2)
    print(payload)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")

    return 0 if result.get("can_proceed") else 2


if __name__ == "__main__":
    raise SystemExit(main())
