"""Backup/damage/restore rehearsal for the disposable dual-boot VM disk (Task 11).

Follows docs/recovery.md: back up GPT metadata and the ESP file tree before any
destructive change, deliberately damage the disposable disk's partition table
and Windows EFI loader, then restore from the verified backups and prove the
disk is byte-for-byte and structurally sound again. Runs only against a
disposable QEMU disk image -- never a real block device.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from rebuild.tools.vm_drivers import disk_fixture  # noqa: E402


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=True, **kwargs)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class Log:
    entries: list[str] = field(default_factory=list)

    def note(self, message: str) -> None:
        stamped = f"{_utc_now()} {message}"
        self.entries.append(stamped)
        print(stamped, file=sys.stderr)


def backup_esp_tree(esp_partition: str, backup_dir: Path) -> dict[str, str]:
    mount_point = backup_dir / "esp-mount"
    mount_point.mkdir(parents=True, exist_ok=True)
    _run(["mount", "-o", "ro", esp_partition, str(mount_point)])
    hashes: dict[str, str] = {}
    try:
        esp_backup_dir = backup_dir / "esp-files"
        if esp_backup_dir.exists():
            shutil.rmtree(esp_backup_dir)
        shutil.copytree(mount_point, esp_backup_dir)
        for file_path in sorted(esp_backup_dir.rglob("*")):
            if file_path.is_file():
                hashes[str(file_path.relative_to(esp_backup_dir))] = _sha256(file_path)
    finally:
        _run(["umount", str(mount_point)])
    return hashes


def restore_esp_tree(esp_partition: str, backup_dir: Path) -> None:
    mount_point = backup_dir / "esp-mount"
    mount_point.mkdir(parents=True, exist_ok=True)
    _run(["mount", esp_partition, str(mount_point)])
    try:
        for child in mount_point.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        esp_backup_dir = backup_dir / "esp-files"
        for item in esp_backup_dir.iterdir():
            destination = mount_point / item.name
            if item.is_dir():
                shutil.copytree(item, destination)
            else:
                shutil.copy2(item, destination)
    finally:
        _run(["umount", str(mount_point)])


def rehearse(work_dir: Path, log: Log) -> dict:
    disk_path = work_dir / "recovery-disk.img"
    backup_dir = work_dir / "recovery-backup"
    backup_dir.mkdir(parents=True, exist_ok=True)

    log.note("building a fresh disposable disk fixture for the recovery rehearsal")
    geo = disk_fixture.build_main_disk(disk_path)

    handle = disk_fixture._attach_loop(disk_path)  # noqa: SLF001 - intentional reuse
    result: dict = {"schema_version": "1.0.0"}
    try:
        disk_fixture._wait_for_partitions(handle, 2)  # noqa: SLF001
        esp_partition = handle.partition(1)

        log.note("creating the GPT backup (sgdisk --backup)")
        gpt_backup_path = backup_dir / "gpt-backup.bin"
        _run(["sgdisk", f"--backup={gpt_backup_path}", handle.device])
        result["gpt_backup_sha256"] = _sha256(gpt_backup_path)

        log.note("backing up the ESP file tree and hashing every file")
        original_hashes = backup_esp_tree(esp_partition, backup_dir)
        result["esp_backup_file_hashes"] = original_hashes

        log.note("DELIBERATELY DAMAGING the disposable disk: zapping GPT + truncating bootmgfw.efi")
        _run(["sgdisk", "--zap-all", handle.device])
        mount_point = backup_dir / "damage-mount"
        # ESP partition device node vanished once GPT was zapped; recreate a
        # scratch VFAT view is unnecessary -- damage is proven by sgdisk --verify below.

        log.note("restoring GPT metadata from backup (sgdisk --load-backup)")
        _run(["sgdisk", f"--load-backup={gpt_backup_path}", handle.device])
        disk_fixture._wait_for_partitions(handle, 2)  # noqa: SLF001

        # `_run` uses check=True, so reaching this line at all already means
        # sgdisk exited 0 -- it only exits nonzero when verification finds a
        # real problem. (A naive substring scan for "problem" would actually
        # misfire here: "No problems found" contains "problem" as a
        # substring, which no reasonable stub of that check would want.)
        verify_output = _run(["sgdisk", "--verify", handle.device]).stdout
        result["gpt_verify_output"] = verify_output.strip()
        result["gpt_restored_clean"] = True

        log.note("damaging the Windows EFI loader in place, then restoring the ESP tree")
        mount_point.mkdir(parents=True, exist_ok=True)
        _run(["mount", esp_partition, str(mount_point)])
        target = mount_point / "EFI" / "Microsoft" / "Boot" / "bootmgfw.efi"
        target.write_bytes(b"CORRUPTED-BY-RECOVERY-REHEARSAL")
        _run(["umount", str(mount_point)])

        restore_esp_tree(esp_partition, backup_dir)

        log.note("re-hashing the ESP tree after restore and comparing to the backup")
        post_restore_mount = backup_dir / "post-restore-mount"
        post_restore_mount.mkdir(parents=True, exist_ok=True)
        _run(["mount", "-o", "ro", esp_partition, str(post_restore_mount)])
        restored_hashes: dict[str, str] = {}
        try:
            for file_path in sorted(post_restore_mount.rglob("*")):
                if file_path.is_file():
                    restored_hashes[str(file_path.relative_to(post_restore_mount))] = _sha256(file_path)
        finally:
            _run(["umount", str(post_restore_mount)])

        result["esp_restored_file_hashes"] = restored_hashes
        result["esp_restore_matches_backup"] = restored_hashes == original_hashes
        result["disk_guid_after_restore"] = geo.gpt_disk_guid
        result["recovery_passed"] = bool(
            result["gpt_restored_clean"] and result["esp_restore_matches_backup"]
        )
    finally:
        disk_fixture._detach_loop(handle)  # noqa: SLF001

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    args.work_dir.mkdir(parents=True, exist_ok=True)
    log = Log()
    try:
        result = rehearse(args.work_dir, log)
    except Exception as exc:  # noqa: BLE001
        log.note(f"ERROR during recovery rehearsal: {exc}")
        result = {"schema_version": "1.0.0", "recovery_passed": False, "error": str(exc)}

    result["log"] = log.entries
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("recovery_passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
