"""Verified Windows boot, GPT, and selected-ESP backup transaction."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Any, BinaryIO, Callable, Iterator, Protocol, cast

from ...shared.atomic_io import atomic_write_json, atomic_write_text
from .disk_probe import DiskProbeSnapshot, collect_disk_probe_snapshot


DEFAULT_MIN_FREE_BYTES = 256 * 1024 * 1024
MOUNT_LETTER_CANDIDATES = ("S", "R", "Q", "P", "O")
GPT_CAPTURE_BYTES = 1024 * 1024


class BackupError(RuntimeError):
    pass


class CommandRunner(Protocol):
    def run(self, command: list[str]) -> subprocess.CompletedProcess[str]: ...


class SubprocessCommandRunner:
    def run(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(command, capture_output=True, text=True, check=False)


@dataclass(frozen=True, slots=True)
class BackupArtifact:
    name: str
    path: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class BackupResult:
    destination: str
    backup_root: str
    manifest_path: str
    artifacts: tuple[BackupArtifact, ...]
    verified: bool

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["artifacts"] = [asdict(artifact) for artifact in self.artifacts]
        return payload


def _is_ventoy_candidate(path: Path) -> bool:
    return any("ventoy" in part.casefold() for part in path.parts)


def _ensure_writable_destination(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    probe = path / ".omarchy-write-probe"
    atomic_write_text(probe, "ok", mode=0o600)
    probe.unlink()


def _select_backup_destination(
    primary_destination: str,
    fallback_destination: str | None,
    *,
    minimum_free_bytes: int,
) -> Path:
    candidates = [Path(primary_destination).expanduser()]
    if fallback_destination:
        fallback = Path(fallback_destination).expanduser()
        if fallback not in candidates:
            candidates.append(fallback)
    ranked = sorted(candidates, key=lambda item: (not _is_ventoy_candidate(item), str(item).casefold()))
    failures: list[str] = []
    for candidate in ranked:
        try:
            _ensure_writable_destination(candidate)
            if shutil.disk_usage(candidate).free < minimum_free_bytes:
                failures.append(f"{candidate}: insufficient free space")
                continue
            return candidate
        except OSError as exc:
            failures.append(f"{candidate}: {exc}")
    raise BackupError("No valid backup destination is available (" + "; ".join(failures) + ").")


def _run_checked(
    runner: CommandRunner,
    command: list[str],
    *,
    allow_failure: bool = False,
) -> subprocess.CompletedProcess[str]:
    completed = runner.run(command)
    if completed.returncode and not allow_failure:
        detail = completed.stderr.strip() or completed.stdout.strip() or "command failed"
        raise BackupError(f"{' '.join(command)}: {detail}")
    return completed


def _find_mount_letter() -> str:
    for letter in MOUNT_LETTER_CANDIDATES:
        if not Path(f"{letter}:/").exists():
            return letter
    raise BackupError("No free drive letter is available for the selected ESP.")


@contextmanager
def _mounted_selected_efi(
    runner: CommandRunner,
    snapshot: DiskProbeSnapshot,
) -> Iterator[Path]:
    letter = _find_mount_letter()
    access_path = f"{letter}:\\"
    disk_number = snapshot.disk_identity.runtime_disk_number
    partition_number = snapshot.efi_identity.partition_number
    mount_script = (
        f"Add-PartitionAccessPath -DiskNumber {disk_number} "
        f"-PartitionNumber {partition_number} -AccessPath '{access_path}' -ErrorAction Stop"
    )
    remove_script = (
        f"Remove-PartitionAccessPath -DiskNumber {disk_number} "
        f"-PartitionNumber {partition_number} -AccessPath '{access_path}' -ErrorAction SilentlyContinue"
    )
    _run_checked(runner, ["powershell.exe", "-NoProfile", "-Command", mount_script])
    try:
        yield Path(f"{letter}:/")
    finally:
        _run_checked(
            runner,
            ["powershell.exe", "-NoProfile", "-Command", remove_script],
            allow_failure=True,
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_live_bcd_database(relative_path: Path) -> bool:
    """Return whether an ESP-relative path is the live, locked BCD database.

    Windows may deny normal file reads of ``EFI/Microsoft/Boot/BCD`` and its
    transaction logs even to an elevated process. The backup transaction has
    already captured that database through the supported ``bcdedit /export``
    API, so these redundant locked files must not make the independent ESP tree
    copy fail.
    """
    parts = tuple(part.casefold() for part in relative_path.parts)
    if len(parts) != 3 or parts[:2] != ("microsoft", "boot"):
        return False
    return parts[2] == "bcd" or parts[2].startswith("bcd.log")


def _file_manifest(
    root: Path,
    *,
    exclude_live_bcd: bool = False,
) -> tuple[list[dict[str, object]], str]:
    entries: list[dict[str, object]] = []
    for path in sorted((item for item in root.rglob("*") if item.is_file())):
        relative_path = path.relative_to(root)
        if exclude_live_bcd and _is_live_bcd_database(relative_path):
            continue
        entries.append(
            {
                "path": relative_path.as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    if not entries:
        raise BackupError(f"Expected at least one file below {root}.")
    canonical = "".join(
        f"{entry['sha256']}  {entry['size_bytes']}  {entry['path']}\n" for entry in entries
    ).encode()
    return entries, hashlib.sha256(canonical).hexdigest()


def _copy_and_verify_efi(source_mount: Path, destination: Path) -> tuple[list[dict[str, object]], str]:
    source = source_mount / "EFI"
    if not source.is_dir():
        raise BackupError("Selected ESP mount does not contain an EFI directory.")
    source_entries, source_hash = _file_manifest(source, exclude_live_bcd=True)
    for source_path in sorted(source.rglob("*")):
        relative_path = source_path.relative_to(source)
        if _is_live_bcd_database(relative_path):
            continue
        destination_path = destination / relative_path
        if source_path.is_dir():
            destination_path.mkdir(parents=True, exist_ok=True)
        elif source_path.is_file():
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, destination_path)
    destination_entries, destination_hash = _file_manifest(destination)
    if source_entries != destination_entries or source_hash != destination_hash:
        raise BackupError("Copied ESP tree failed per-file hash verification.")
    return destination_entries, destination_hash


def _export_bcd_store(runner: CommandRunner, destination: Path) -> Path:
    path = destination / "bcd-store.bak"
    _run_checked(runner, ["bcdedit", "/export", str(path)])
    return path


def _collect_disk_metadata(
    runner: CommandRunner,
    destination: Path,
    snapshot: DiskProbeSnapshot,
) -> Path:
    path = destination / "disk-metadata.json"
    disk_number = snapshot.disk_identity.runtime_disk_number
    script = (
        f"$disk = Get-Disk -Number {disk_number} -ErrorAction Stop; "
        f"$partitions = Get-Partition -DiskNumber {disk_number} -ErrorAction Stop | Sort-Object Offset; "
        "[PSCustomObject]@{ captured_at_utc=(Get-Date).ToUniversalTime().ToString('o'); "
        "disk=$disk | Select-Object Number,FriendlyName,SerialNumber,PartitionStyle,Guid,Size,LogicalSectorSize; "
        "partitions=$partitions | Select-Object PartitionNumber,DriveLetter,Size,Offset,GptType,Guid } "
        "| ConvertTo-Json -Depth 8 -Compress"
    )
    completed = _run_checked(runner, ["powershell.exe", "-NoProfile", "-Command", script])
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise BackupError(f"Disk metadata command returned invalid JSON: {exc}") from exc
    atomic_write_json(path, payload)
    return path


def _default_raw_open(path: str, mode: str) -> BinaryIO:
    return cast(BinaryIO, open(path, mode, buffering=0))


def _capture_gpt_regions(
    snapshot: DiskProbeSnapshot,
    destination: Path,
    *,
    raw_open: Callable[[str, str], BinaryIO],
) -> tuple[Path, Path]:
    disk_number = snapshot.disk_identity.runtime_disk_number
    disk_size = snapshot.disk_identity.disk_size_bytes
    capture_size = min(GPT_CAPTURE_BYTES, disk_size // 2)
    if capture_size <= 0:
        raise BackupError("Disk is too small for GPT metadata capture.")
    raw_path = rf"\\.\PhysicalDrive{disk_number}"
    with raw_open(raw_path, "rb") as disk:
        primary = disk.read(capture_size)
        disk.seek(disk_size - capture_size)
        backup = disk.read(capture_size)
    if len(primary) != capture_size or len(backup) != capture_size:
        raise BackupError("Short read while capturing GPT metadata regions.")
    primary_path = destination / "gpt-primary.bin"
    backup_path = destination / "gpt-backup.bin"
    primary_path.write_bytes(primary)
    backup_path.write_bytes(backup)
    return primary_path, backup_path


def _artifact(name: str, path: Path, *, digest: str | None = None) -> BackupArtifact:
    if not path.exists() or not path.is_file() or path.stat().st_size <= 0:
        raise BackupError(f"Expected non-empty backup artifact: {path}")
    return BackupArtifact(name, str(path), path.stat().st_size, digest or _sha256(path))


def run_windows_backup_subsystem(
    primary_destination: str,
    *,
    fallback_destination: str | None = None,
    system_drive: str = "C",
    minimum_free_bytes: int = DEFAULT_MIN_FREE_BYTES,
    dry_run: bool = False,
    runner: CommandRunner | None = None,
    snapshot: DiskProbeSnapshot | None = None,
    efi_mount_override: Path | None = None,
    raw_open: Callable[[str, str], BinaryIO] = _default_raw_open,
) -> BackupResult:
    if not primary_destination.strip():
        raise ValueError("Backup destination cannot be empty.")
    active_runner = runner or SubprocessCommandRunner()
    selected_snapshot = snapshot or collect_disk_probe_snapshot(system_drive=system_drive)
    destination = _select_backup_destination(
        primary_destination,
        fallback_destination,
        minimum_free_bytes=minimum_free_bytes,
    )
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    backup_root = destination / "omarchy" / "windows-backup" / timestamp
    backup_root.mkdir(parents=True, exist_ok=False)

    if dry_run:
        bcd_path = atomic_write_text(backup_root / "bcd-store.bak", "simulation only")
        metadata_path = atomic_write_json(backup_root / "disk-metadata.json", {"simulated": True})
        primary_gpt = atomic_write_text(backup_root / "gpt-primary.bin", "simulation only")
        backup_gpt = atomic_write_text(backup_root / "gpt-backup.bin", "simulation only")
        efi_dir = backup_root / "efi"
        efi_dir.mkdir()
        atomic_write_text(efi_dir / "SIMULATION.txt", "No EFI files were read.")
        efi_entries, efi_hash = _file_manifest(efi_dir)
    else:
        bcd_path = _export_bcd_store(active_runner, backup_root)
        metadata_path = _collect_disk_metadata(active_runner, backup_root, selected_snapshot)
        primary_gpt, backup_gpt = _capture_gpt_regions(
            selected_snapshot,
            backup_root,
            raw_open=raw_open,
        )
        efi_dir = backup_root / "efi"
        if efi_mount_override is not None:
            efi_entries, efi_hash = _copy_and_verify_efi(efi_mount_override, efi_dir)
        else:
            with _mounted_selected_efi(active_runner, selected_snapshot) as mounted_efi:
                efi_entries, efi_hash = _copy_and_verify_efi(mounted_efi, efi_dir)

    efi_manifest_path = backup_root / "efi-files.json"
    atomic_write_json(
        efi_manifest_path,
        {"aggregate_sha256": efi_hash, "files": efi_entries},
    )
    restore_path = atomic_write_text(
        backup_root / "RESTORE-INSTRUCTIONS.txt",
        "Do not restore raw GPT regions directly. Use qualified recovery tooling in a disposable clone first.\n",
        mode=0o600,
    )
    artifacts = (
        _artifact("bcd_store", bcd_path),
        _artifact("disk_metadata", metadata_path),
        _artifact("gpt_primary", primary_gpt),
        _artifact("gpt_backup", backup_gpt),
        _artifact("efi_file_manifest", efi_manifest_path),
        _artifact("efi_tree", efi_manifest_path, digest=efi_hash),
        _artifact("restore_instructions", restore_path),
    )

    manifest_path = backup_root / "backup-manifest.json"
    manifest_payload = {
        "schema_version": "1.0.0",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "simulation": dry_run,
        "source": {
            "disk_identity": selected_snapshot.disk_identity.model_dump(mode="json"),
            "efi_identity": selected_snapshot.efi_identity.model_dump(mode="json"),
            "windows_partition_identity": selected_snapshot.windows_partition_identity.model_dump(
                mode="json"
            ),
        },
        "tool_versions": {"python": sys.version.split()[0]},
        "artifacts": [asdict(item) for item in artifacts],
        "verification": {
            "status": "simulated" if dry_run else "verified",
            "efi_aggregate_sha256": efi_hash,
            "all_artifacts_nonempty": True,
        },
    }
    atomic_write_json(manifest_path, manifest_payload)
    return BackupResult(
        destination=str(destination),
        backup_root=str(backup_root),
        manifest_path=str(manifest_path),
        artifacts=artifacts,
        verified=not dry_run,
    )


def backup_boot_state(
    destination: str,
    fallback_destination: str | None = None,
    *,
    system_drive: str = "C",
    dry_run: bool = False,
) -> str:
    return run_windows_backup_subsystem(
        primary_destination=destination,
        fallback_destination=fallback_destination,
        system_drive=system_drive,
        dry_run=dry_run,
    ).backup_root
