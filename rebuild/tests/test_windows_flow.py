from __future__ import annotations

import pytest

from rebuild.installer.platforms.windows.flow import WindowsMigrationFlow


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
    assert calls["primary_destination"] == "E:/backup"
    assert calls["dry_run"] is True


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
