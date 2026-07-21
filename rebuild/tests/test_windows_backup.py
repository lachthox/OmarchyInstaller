from __future__ import annotations

import io
import json
from pathlib import Path
import subprocess

from rebuild.installer.platforms.windows.backup import run_windows_backup_subsystem
from rebuild.tests.test_windows_tui_pilot import snapshot


class BackupRunner:
    def run(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        if command[:2] == ["bcdedit", "/export"]:
            Path(command[2]).write_bytes(b"bcd backup")
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[0] == "powershell.exe":
            return subprocess.CompletedProcess(command, 0, '{"disk":{"Guid":"disk-guid"}}', "")
        return subprocess.CompletedProcess(command, 1, "", "unexpected command")


class FakeRawDisk(io.BytesIO):
    def __init__(self) -> None:
        super().__init__(b"x" * (2 * 1024 * 1024))

    def seek(self, _offset: int, _whence: int = 0) -> int:
        return super().seek(1024 * 1024)


def test_backup_verifies_selected_esp_and_per_file_manifest(tmp_path: Path) -> None:
    source_mount = tmp_path / "selected-esp"
    (source_mount / "EFI" / "Microsoft" / "Boot").mkdir(parents=True)
    (source_mount / "EFI" / "Microsoft" / "Boot" / "bootmgfw.efi").write_bytes(b"windows")
    (source_mount / "EFI" / "Boot").mkdir(parents=True)
    (source_mount / "EFI" / "Boot" / "bootx64.efi").write_bytes(b"fallback")

    result = run_windows_backup_subsystem(
        str(tmp_path / "destination"),
        runner=BackupRunner(),
        snapshot=snapshot(),
        efi_mount_override=source_mount,
        raw_open=lambda _path, _mode: FakeRawDisk(),
        minimum_free_bytes=0,
    )

    assert result.verified is True
    manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    assert manifest["verification"]["status"] == "verified"
    assert manifest["source"]["disk_identity"]["gpt_disk_guid"].endswith("0010")
    efi_manifest = json.loads(
        (Path(result.backup_root) / "efi-files.json").read_text(encoding="utf-8")
    )
    assert [item["path"] for item in efi_manifest["files"]] == [
        "Boot/bootx64.efi",
        "Microsoft/Boot/bootmgfw.efi",
    ]
    assert len(efi_manifest["aggregate_sha256"]) == 64


def test_dry_run_is_simulated_not_verified(tmp_path: Path) -> None:
    result = run_windows_backup_subsystem(
        str(tmp_path / "destination"),
        dry_run=True,
        snapshot=snapshot(),
        minimum_free_bytes=0,
    )

    manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    assert result.verified is False
    assert manifest["verification"]["status"] == "simulated"
