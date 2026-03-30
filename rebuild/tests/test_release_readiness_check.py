from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any, Callable


def _load_audit_release_readiness() -> Callable[..., dict[str, Any]]:
    module_path = Path(__file__).resolve().parents[1] / "tools" / "release_readiness_check.py"
    spec = importlib.util.spec_from_file_location("release_readiness_check", module_path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive import guard
        raise RuntimeError(f"Unable to load module spec from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.audit_release_readiness


audit_release_readiness = _load_audit_release_readiness()


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _artifact_dir(tmp_path: Path, *, policy: str = "python-then-legacy") -> Path:
    artifact_dir = tmp_path / "artifacts"
    manifest = {
        "schema_version": "1.0.0",
        "packaging_inputs": {
            "launcher_default_policy": policy,
        },
    }
    _write_json(artifact_dir / "windows-exe-build-manifest.json", manifest)
    return artifact_dir


def _hardware_report(tmp_path: Path, *, case_overrides: dict[str, str] | None = None) -> Path:
    statuses = {
        "uefi_nvme_desktop": "pass",
        "uefi_laptop_secure_boot_disabled": "pass",
        "uefi_dual_disk_nonzero_target": "pass",
    }
    if case_overrides:
        statuses.update(case_overrides)

    payload = {
        "schema_version": "1.0.0",
        "cases": {name: {"status": status} for name, status in statuses.items()},
    }
    path = tmp_path / "hardware.json"
    _write_json(path, payload)
    return path


def _firstboot_report(tmp_path: Path, *, check_overrides: dict[str, str] | None = None) -> Path:
    statuses = {
        "firstboot_service_ran_once": "pass",
        "boot_guardian_service_healthy": "pass",
        "completion_marker_written": "pass",
    }
    if check_overrides:
        statuses.update(check_overrides)

    payload = {
        "schema_version": "1.0.0",
        "checks": {name: {"status": status} for name, status in statuses.items()},
    }
    path = tmp_path / "firstboot.json"
    _write_json(path, payload)
    return path


def test_readiness_audit_passes_with_all_required_inputs(tmp_path: Path) -> None:
    result = audit_release_readiness(
        artifact_dir=_artifact_dir(tmp_path),
        hardware_report=_hardware_report(tmp_path),
        firstboot_report=_firstboot_report(tmp_path),
        require_all=True,
    )
    assert result["can_proceed"] is True
    assert result["errors"] == []


def test_readiness_audit_fails_on_wrong_release_policy(tmp_path: Path) -> None:
    result = audit_release_readiness(
        artifact_dir=_artifact_dir(tmp_path, policy="python-only"),
        hardware_report=_hardware_report(tmp_path),
        firstboot_report=_firstboot_report(tmp_path),
        require_all=True,
    )
    assert result["can_proceed"] is False
    assert any("Release policy mismatch" in error for error in result["errors"])


def test_readiness_audit_fails_when_hardware_case_missing(tmp_path: Path) -> None:
    report_path = tmp_path / "hardware.json"
    _write_json(
        report_path,
        {
            "schema_version": "1.0.0",
            "cases": {
                "uefi_nvme_desktop": {"status": "pass"},
                "uefi_laptop_secure_boot_disabled": {"status": "pass"},
            },
        },
    )

    result = audit_release_readiness(
        artifact_dir=_artifact_dir(tmp_path),
        hardware_report=report_path,
        firstboot_report=_firstboot_report(tmp_path),
        require_all=True,
    )
    assert result["can_proceed"] is False
    assert any("Missing hardware matrix case 'uefi_dual_disk_nonzero_target'" in error for error in result["errors"])


def test_readiness_audit_fails_when_firstboot_check_not_passed(tmp_path: Path) -> None:
    result = audit_release_readiness(
        artifact_dir=_artifact_dir(tmp_path),
        hardware_report=_hardware_report(tmp_path),
        firstboot_report=_firstboot_report(tmp_path, check_overrides={"boot_guardian_service_healthy": "fail"}),
        require_all=True,
    )
    assert result["can_proceed"] is False
    assert any("Firstboot check 'boot_guardian_service_healthy'" in error for error in result["errors"])
