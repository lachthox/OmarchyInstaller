"""Windows backup subsystem for EFI/BCD and disk metadata snapshots."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any, Iterator, Protocol


DEFAULT_MIN_FREE_BYTES = 256 * 1024 * 1024
MOUNT_LETTER_CANDIDATES = ("S", "R", "Q", "P", "O")


class BackupError(RuntimeError):
    """Raised when a mandatory backup step cannot complete safely."""


class CommandRunner(Protocol):
    """Minimal command execution protocol for deterministic stubbing."""

    def run(self, command: list[str]) -> subprocess.CompletedProcess[str]: ...


class SubprocessCommandRunner:
    """Default command runner based on subprocess."""

    def run(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )


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
    artifacts: tuple[BackupArtifact, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["artifacts"] = [asdict(artifact) for artifact in self.artifacts]
        return payload


def _is_ventoy_candidate(path: Path) -> bool:
    return any("ventoy" in part.lower() for part in path.parts)


def _ensure_writable_destination(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    probe = path / ".omarchy-write-probe"
    probe.write_text("ok", encoding="utf-8")
    probe.unlink()


def _has_min_free_space(path: Path, minimum_bytes: int) -> bool:
    usage = shutil.disk_usage(path)
    return usage.free >= minimum_bytes


def _select_backup_destination(
    primary_destination: str,
    fallback_destination: str | None,
    *,
    minimum_free_bytes: int,
) -> Path:
    candidates: list[Path] = []
    primary = Path(primary_destination).expanduser()
    candidates.append(primary)
    if fallback_destination:
        fallback = Path(fallback_destination).expanduser()
        if fallback != primary:
            candidates.append(fallback)

    ranked = sorted(
        candidates,
        key=lambda candidate: (0 if _is_ventoy_candidate(candidate) else 1, str(candidate).lower()),
    )

    failures: list[str] = []
    for candidate in ranked:
        try:
            _ensure_writable_destination(candidate)
            if not _has_min_free_space(candidate, minimum_free_bytes):
                failures.append(f"{candidate}: insufficient free space")
                continue
            return candidate
        except OSError as exc:
            failures.append(f"{candidate}: {exc}")

    details = "; ".join(failures) if failures else "no destination candidates provided"
    raise BackupError(f"No valid backup destination is available ({details}).")


def _run_checked(
    runner: CommandRunner,
    command: list[str],
    *,
    allow_failure: bool = False,
) -> subprocess.CompletedProcess[str]:
    completed = runner.run(command)
    if completed.returncode != 0 and not allow_failure:
        message = completed.stderr.strip() or completed.stdout.strip() or "command failed"
        raise BackupError(f"{' '.join(command)}: {message}")
    return completed


def _find_mount_letter() -> str:
    for letter in MOUNT_LETTER_CANDIDATES:
        if not Path(f"{letter}:/").exists():
            return letter
    raise BackupError("No free drive letter available for temporary EFI mount.")


@contextmanager
def _mounted_efi_partition(runner: CommandRunner) -> Iterator[Path]:
    mount_letter = _find_mount_letter()
    mount_target = f"{mount_letter}:"
    _run_checked(runner, ["mountvol", mount_target, "/S"])
    try:
        yield Path(f"{mount_target}/")
    finally:
        _run_checked(runner, ["mountvol", mount_target, "/D"], allow_failure=True)


def _export_bcd_store(runner: CommandRunner, destination: Path) -> Path:
    bcd_path = destination / "bcd-store.bak"
    _run_checked(runner, ["bcdedit", "/export", str(bcd_path)])
    return bcd_path


def _collect_disk_metadata(runner: CommandRunner, destination: Path, system_drive: str) -> Path:
    output_path = destination / "disk-metadata.json"
    drive_letter = system_drive.strip().rstrip(":").upper()
    if len(drive_letter) != 1:
        raise ValueError(f"Invalid system drive: {system_drive!r}")

    script = rf"""
$drive = '{drive_letter}'
$systemPartition = Get-Partition -DriveLetter $drive -ErrorAction Stop
$disk = Get-Disk -Number $systemPartition.DiskNumber -ErrorAction Stop
$partitions = Get-Partition -DiskNumber $disk.Number -ErrorAction Stop | Sort-Object Offset | Select-Object PartitionNumber,DriveLetter,Size,Offset,GptType,Guid
[PSCustomObject]@{{
  captured_at_utc = (Get-Date).ToUniversalTime().ToString('o')
  disk = $disk | Select-Object Number,FriendlyName,SerialNumber,PartitionStyle,Guid,Size,LargestFreeExtent,LogicalSectorSize
  partitions = $partitions
}} | ConvertTo-Json -Depth 8 -Compress
"""
    completed = _run_checked(runner, ["powershell.exe", "-NoProfile", "-Command", script])
    output_path.write_text(completed.stdout, encoding="utf-8")
    return output_path


def _copy_efi_tree(runner: CommandRunner, destination: Path) -> Path:
    efi_destination = destination / "efi"
    with _mounted_efi_partition(runner) as efi_mount:
        source = efi_mount / "EFI"
        if not source.exists():
            raise BackupError("EFI mount did not expose an EFI directory.")
        shutil.copytree(source, efi_destination, dirs_exist_ok=True)
    return efi_destination


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _directory_size(path: Path) -> int:
    total = 0
    for child in path.rglob("*"):
        if child.is_file():
            total += child.stat().st_size
    return total


def _verify_file(path: Path) -> None:
    if not path.exists():
        raise BackupError(f"Expected backup artifact missing: {path}")
    if path.stat().st_size <= 0:
        raise BackupError(f"Expected backup artifact is empty: {path}")


def _verify_directory(path: Path) -> None:
    if not path.exists() or not path.is_dir():
        raise BackupError(f"Expected backup directory missing: {path}")
    if not any(path.rglob("*")):
        raise BackupError(f"Expected backup directory is empty: {path}")


def run_windows_backup_subsystem(
    primary_destination: str,
    *,
    fallback_destination: str | None = None,
    system_drive: str = "C",
    minimum_free_bytes: int = DEFAULT_MIN_FREE_BYTES,
    dry_run: bool = False,
    runner: CommandRunner | None = None,
) -> BackupResult:
    """Run deterministic Windows backup flow with Ventoy-first destination selection."""
    if not primary_destination.strip():
        raise ValueError("Backup destination cannot be empty.")

    active_runner = runner or SubprocessCommandRunner()
    destination = _select_backup_destination(
        primary_destination,
        fallback_destination,
        minimum_free_bytes=minimum_free_bytes,
    )

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_root = destination / "omarchy" / "windows-backup" / timestamp
    backup_root.mkdir(parents=True, exist_ok=True)

    if dry_run:
        bcd_path = backup_root / "bcd-store.bak"
        bcd_path.write_text("dry-run-bcd", encoding="utf-8")
        disk_metadata_path = backup_root / "disk-metadata.json"
        disk_metadata_path.write_text(json.dumps({"dry_run": True}), encoding="utf-8")
        efi_dir = backup_root / "efi"
        efi_dir.mkdir(parents=True, exist_ok=True)
        (efi_dir / "BOOTX64.EFI").write_text("dry-run-efi", encoding="utf-8")
    else:
        bcd_path = _export_bcd_store(active_runner, backup_root)
        disk_metadata_path = _collect_disk_metadata(active_runner, backup_root, system_drive)
        efi_dir = _copy_efi_tree(active_runner, backup_root)

    _verify_file(bcd_path)
    _verify_file(disk_metadata_path)
    _verify_directory(efi_dir)

    artifacts = (
        BackupArtifact(
            name="bcd_store",
            path=str(bcd_path),
            size_bytes=bcd_path.stat().st_size,
            sha256=_sha256(bcd_path),
        ),
        BackupArtifact(
            name="disk_metadata",
            path=str(disk_metadata_path),
            size_bytes=disk_metadata_path.stat().st_size,
            sha256=_sha256(disk_metadata_path),
        ),
        BackupArtifact(
            name="efi_tree",
            path=str(efi_dir),
            size_bytes=_directory_size(efi_dir),
            sha256="directory",
        ),
    )

    manifest_path = backup_root / "backup-manifest.json"
    manifest_payload = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "destination": str(destination),
        "backup_root": str(backup_root),
        "artifacts": [asdict(artifact) for artifact in artifacts],
    }
    manifest_path.write_text(json.dumps(manifest_payload, indent=2), encoding="utf-8")
    _verify_file(manifest_path)

    return BackupResult(
        destination=str(destination),
        backup_root=str(backup_root),
        artifacts=artifacts,
    )


def backup_boot_state(
    destination: str,
    fallback_destination: str | None = None,
    *,
    system_drive: str = "C",
    dry_run: bool = False,
) -> str:
    """Legacy-compatible wrapper returning the chosen backup root path."""
    result = run_windows_backup_subsystem(
        primary_destination=destination,
        fallback_destination=fallback_destination,
        system_drive=system_drive,
        dry_run=dry_run,
    )
    return result.backup_root
