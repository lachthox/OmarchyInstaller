from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from rebuild.installer.platforms.windows.disk_probe import DiskProbeSnapshot
from rebuild.installer.platforms.windows.flow import WindowsMigrationFlow
from rebuild.installer.shared import validate_plan_contract


WORKSPACE = Path(__file__).resolve().parents[2]


class _BackupStub:
    def __init__(self) -> None:
        self.artifacts = ("a", "b")
        self.backup_root = "D:/media/omarchy/windows-backup/ts"
        self.manifest_path = "D:/media/omarchy/windows-backup/ts/backup-manifest.json"
        self.verified = True

    def to_dict(self) -> dict[str, str]:
        return {"backup_root": self.backup_root}


class _PartitionStub:
    current_free_space_bytes = 80 * 1024**3
    final_free_space_bytes = 120 * 1024**3
    resized = True
    after_snapshot = None

    def to_dict(self) -> dict[str, str]:
        return {"result": "ok"}


def test_run_backup_success(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}
    flow_module = WindowsMigrationFlow.__module__

    def _fake_backup(**kwargs: object) -> _BackupStub:
        calls.update(kwargs)
        return _BackupStub()

    monkeypatch.setattr(f"{flow_module}.run_windows_backup_subsystem", _fake_backup)

    flow = WindowsMigrationFlow(apply_changes=False, target_free_gib=120, backup_destination="E:/backup")
    result = flow.run_backup()

    assert result.ok is True
    assert "DRY-RUN" in result.summary
    # `E:/backup` is a Windows drive-letter path. It is already absolute in
    # Windows terms, so `_resolve_backup_destination` (via `pathlib.Path`)
    # returns it unchanged on a real Windows host. On a POSIX CI host,
    # `pathlib.Path` has no concept of drive letters and treats it as
    # relative, so `.resolve()` legitimately prepends the CWD there instead.
    # Comparing the tail keeps this assertion meaningful and host-agnostic.
    destination = str(calls["primary_destination"]).replace("\\", "/")
    assert destination.endswith("E:/backup")
    assert calls["dry_run"] is True


def test_apply_backup_uses_managed_recovery_destination(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}
    flow_module = WindowsMigrationFlow.__module__

    def _fake_backup(**kwargs: object) -> _BackupStub:
        calls.update(kwargs)
        return _BackupStub()

    monkeypatch.setattr(f"{flow_module}.run_windows_backup_subsystem", _fake_backup)
    monkeypatch.setenv("SystemDrive", "C:")
    monkeypatch.setenv("ProgramData", "C:/ProgramData")

    result = WindowsMigrationFlow(apply_changes=True).run_backup()

    assert result.ok is True
    destination = str(calls["primary_destination"]).replace("\\", "/")
    assert destination.endswith("C:/ProgramData")
    assert calls["dry_run"] is False


def test_apply_backup_rejects_explicit_system_disk_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SystemDrive", "C:")
    result = WindowsMigrationFlow(
        apply_changes=True, backup_destination="C:/same-disk-backup"
    ).run_backup()
    assert result.ok is False
    assert "off the Windows system disk" in result.summary


def test_run_partition_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    flow_module = WindowsMigrationFlow.__module__

    def _raise_partition(*args: object, **kwargs: object) -> _PartitionStub:
        raise ValueError("boom")

    monkeypatch.setattr(f"{flow_module}.prepare_unallocated_space", _raise_partition)

    flow = WindowsMigrationFlow(apply_changes=True, target_free_gib=200)
    flow._verified_backup_manifest = "D:/backup/backup-manifest.json"
    flow._backup_root = "D:/backup"
    result = flow.run_partition_prep()

    assert result.ok is False
    assert "boom" in result.summary


def test_run_partition_success(monkeypatch: pytest.MonkeyPatch) -> None:
    flow_module = WindowsMigrationFlow.__module__

    def _fake_partition(*args: object, **kwargs: object) -> _PartitionStub:
        return _PartitionStub()

    monkeypatch.setattr(f"{flow_module}.prepare_unallocated_space", _fake_partition)

    flow = WindowsMigrationFlow(apply_changes=True, target_free_gib=120)
    flow._verified_backup_manifest = "D:/backup/backup-manifest.json"
    flow._backup_root = "D:/backup"
    result = flow.run_partition_prep()

    assert result.ok is True
    assert "APPLY" in result.summary
    assert "80.0 GiB -> 120.0 GiB" in result.summary


def test_dry_run_handoff_validates_pair_and_emits_out_of_band_key(tmp_path: Path) -> None:
    payload = json.loads(
        (WORKSPACE / "rebuild/assets/templates/plan.template.json").read_text(encoding="utf-8")
    )
    iso = tmp_path / "paired.iso"
    release = tmp_path / "release_manifest.json"
    iso.write_bytes(b"paired iso")
    release.write_text('{"paired":true}\n', encoding="utf-8")
    payload["provenance"]["iso_name"] = iso.name
    payload["provenance"]["iso_sha256"] = hashlib.sha256(iso.read_bytes()).hexdigest()
    payload["provenance"]["release_manifest_sha256"] = hashlib.sha256(
        release.read_bytes()
    ).hexdigest()
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(json.dumps(payload), encoding="utf-8")
    plan = validate_plan_contract(payload)
    snapshot = DiskProbeSnapshot(
        disk_identity=plan.disk_identity,
        efi_identity=plan.efi_identity,
        windows_partition_identity=plan.windows_partition_identity,
        prepared_free_space_range=plan.prepared_free_space_range,
        partitions=(plan.efi_identity, plan.windows_partition_identity),
    )
    flow = WindowsMigrationFlow(apply_changes=False)
    flow._prepared_snapshot = snapshot

    result = flow.run_ventoy_handoff(
        plan_path=str(plan_path),
        iso_path=str(iso),
        release_manifest_path=str(release),
        usb_disk_number=7,
        usb_confirmation="ERASE ignored-in-dry-run",
    )

    assert result.ok is True
    assert result.payload is not None
    assert "integrity_key_hex" not in result.payload
