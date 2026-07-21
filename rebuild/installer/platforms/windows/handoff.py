"""Ventoy acquisition, prep, and handoff validation helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import hashlib
import hmac
import os
from pathlib import Path
import shutil
import subprocess
from typing import Any, Protocol, Sequence

from ...shared import PlanContract, validate_plan_contract
from ...shared.atomic_io import atomic_write_json, atomic_write_text


DEFAULT_VENTOY_WINGET_ID = "Ventoy.Ventoy"
DEFAULT_VENTOY_MIN_FREE_BYTES = 64 * 1024 * 1024
DEFAULT_VENTOY_DATA_FILESYSTEMS = {"EXFAT", "NTFS", "FAT32"}
FAT32_MAX_FILE_BYTES = 4 * 1024**3 - 1


class VentoyError(RuntimeError):
    """Raised when Ventoy acquisition, install, or validation fails safely."""


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
class VentoyCliInfo:
    path: str
    source: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class VentoyUsbValidation:
    disk_number: int
    bus_type: str
    partition_style: str
    partition_count: int
    data_drive_letter: str
    data_root: str
    filesystem: str
    free_bytes: int
    required_bytes: int
    payload_bytes: int
    writable: bool
    structure_verified: bool
    warnings: tuple[str, ...]
    stable_identifier: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["warnings"] = list(self.warnings)
        return payload


@dataclass(frozen=True, slots=True)
class VentoyPrepResult:
    cli: VentoyCliInfo
    validation: VentoyUsbValidation
    install_output: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "cli": self.cli.to_dict(),
            "validation": self.validation.to_dict(),
            "install_output": self.install_output,
        }


@dataclass(frozen=True, slots=True)
class VentoyPayloadResult:
    iso_path: str
    plan_path: str
    wifi_path: str | None
    install_log_path: str | None
    backup_info_path: str | None
    written_files: tuple[str, ...]
    handoff_manifest_path: str | None = None
    handoff_manifest_sha256: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["written_files"] = list(self.written_files)
        return payload


def _run_checked(
    runner: CommandRunner,
    command: list[str],
    *,
    allow_failure: bool = False,
) -> subprocess.CompletedProcess[str]:
    completed = runner.run(command)
    if completed.returncode != 0 and not allow_failure:
        message = completed.stderr.strip() or completed.stdout.strip() or "command failed"
        raise VentoyError(f"{' '.join(command)}: {message}")
    return completed


def _run_powershell_checked(runner: CommandRunner, script: str) -> str:
    completed = _run_checked(runner, ["powershell.exe", "-NoProfile", "-Command", script])
    return completed.stdout.strip()


def _normalize_drive_letter(system_drive: str) -> str:
    value = system_drive.strip().rstrip(":").upper()
    if len(value) != 1 or not value.isalpha():
        raise ValueError(f"Invalid drive letter: {system_drive!r}")
    return value


def _default_ventoy_roots() -> tuple[Path, ...]:
    roots: list[Path] = []
    for env_name, relative in (
        ("LOCALAPPDATA", ("Microsoft", "WinGet", "Packages")),
        ("ProgramFiles", ("Ventoy",)),
        ("ProgramFiles(x86)", ("Ventoy",)),
    ):
        env_value = os.environ.get(env_name)
        if not env_value:
            continue
        roots.append(Path(env_value).joinpath(*relative))
    return tuple(roots)


def find_ventoy_cli_path(search_roots: Sequence[str | Path] | None = None) -> Path | None:
    """Locate Ventoy2Disk.exe via PATH or known installation roots."""
    candidate = shutil.which("Ventoy2Disk.exe")
    if candidate:
        return Path(candidate)

    roots = tuple(Path(root) for root in search_roots) if search_roots is not None else _default_ventoy_roots()
    for root in roots:
        if not root.exists():
            continue
        try:
            for path in root.rglob("Ventoy2Disk.exe"):
                if path.is_file():
                    return path
        except OSError:
            continue
    return None


def acquire_ventoy_cli(
    *,
    allow_install: bool = False,
    runner: CommandRunner | None = None,
) -> VentoyCliInfo:
    """Locate Ventoy2Disk.exe or install Ventoy via winget when explicitly allowed."""
    path = find_ventoy_cli_path()
    if path:
        return VentoyCliInfo(path=str(path), source="existing")

    if not allow_install:
        raise VentoyError("Ventoy2Disk.exe was not found. Install Ventoy or enable allow_install to acquire it.")

    winget = shutil.which("winget")
    if not winget:
        raise VentoyError("Ventoy2Disk.exe was not found and winget is unavailable.")

    active_runner = runner or SubprocessCommandRunner()
    _run_checked(
        active_runner,
        [
            winget,
            "install",
            "--id",
            DEFAULT_VENTOY_WINGET_ID,
            "--exact",
            "--silent",
            "--accept-package-agreements",
            "--accept-source-agreements",
        ],
    )

    path = find_ventoy_cli_path()
    if not path:
        raise VentoyError("Ventoy appears installed but Ventoy2Disk.exe was not found afterward.")
    return VentoyCliInfo(path=str(path), source="winget")


def _collect_usb_layout(disk_number: int, runner: CommandRunner) -> dict[str, Any]:
    script = rf"""
$disk = Get-Disk -Number {disk_number} -ErrorAction Stop
$partitions = Get-Partition -DiskNumber $disk.Number -ErrorAction Stop | Sort-Object PartitionNumber
$partitionPayload = foreach ($partition in $partitions) {{
  $volume = $null
  try {{
    $volume = $partition | Get-Volume -ErrorAction Stop
  }} catch {{
  }}

  [PSCustomObject]@{{
    partition_number = [int]$partition.PartitionNumber
    drive_letter = if ($volume -and $volume.DriveLetter) {{ [string]$volume.DriveLetter }} else {{ '' }}
    filesystem = if ($volume -and $volume.FileSystem) {{ [string]$volume.FileSystem }} else {{ '' }}
    size_bytes = [int64]$partition.Size
    offset_bytes = [int64]$partition.Offset
    gpt_type = [string]$partition.GptType
  }}
}}

[PSCustomObject]@{{
  disk_number = [int]$disk.Number
  bus_type = [string]$disk.BusType
  partition_style = [string]$disk.PartitionStyle
  size_bytes = [int64]$disk.Size
  partition_count = [int]@($partitions).Count
  model = [string]$disk.FriendlyName
  serial = [string]$disk.SerialNumber
  size_bytes = [int64]$disk.Size
  disk_guid = [string]$disk.Guid
  is_boot = [bool]$disk.IsBoot
  is_system = [bool]$disk.IsSystem
  contains_pagefile = [bool](@($partitions | Where-Object {{ $_.DriveLetter -and (Get-CimInstance Win32_PageFileUsage -ErrorAction SilentlyContinue).Name -like "$($_.DriveLetter):*" }}).Count -gt 0)
  partitions = $partitionPayload
}} | ConvertTo-Json -Depth 8 -Compress
"""
    output = _run_powershell_checked(runner, script)
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as exc:
        raise VentoyError(f"Failed to parse Ventoy disk metadata: {exc}") from exc
    if not isinstance(payload, dict):
        raise VentoyError("Ventoy disk metadata did not return an object payload.")
    return payload


def _assign_drive_letter(disk_number: int, partition_number: int, runner: CommandRunner) -> str:
    script = rf"""
Add-PartitionAccessPath -DiskNumber {disk_number} -PartitionNumber {partition_number} -AssignDriveLetter -ErrorAction Stop
Start-Sleep -Seconds 2
$updated = Get-Partition -DiskNumber {disk_number} -PartitionNumber {partition_number} -ErrorAction Stop | Get-Volume -ErrorAction SilentlyContinue
if ($updated -and $updated.DriveLetter) {{ [string]$updated.DriveLetter }} else {{ '' }}
"""
    drive_letter = _run_powershell_checked(runner, script)
    if not drive_letter:
        raise VentoyError(f"Could not assign a drive letter to Ventoy partition {partition_number} on disk {disk_number}.")
    return drive_letter.strip().upper()


def _choose_data_partition(partitions: list[dict[str, Any]]) -> dict[str, Any]:
    if not partitions:
        raise VentoyError("Ventoy disk returned no partition records.")

    candidates = [
        partition
        for partition in partitions
        if str(partition.get("drive_letter", "")).strip()
        and str(partition.get("filesystem", "")).strip().upper() in DEFAULT_VENTOY_DATA_FILESYSTEMS
    ]
    if candidates:
        return max(candidates, key=lambda partition: int(partition.get("size_bytes", 0)))

    return max(partitions, key=lambda partition: int(partition.get("size_bytes", 0)))


def _probe_volume_root(drive_letter: str) -> Path:
    root = Path(f"{drive_letter}:/")
    if not root.exists():
        raise VentoyError(f"Ventoy data volume is not accessible: {root}")
    return root


def _ensure_writable_root(root: Path) -> None:
    probe = root / ".omarchy-write-probe"
    probe.write_text("ok", encoding="utf-8")
    probe.unlink()


def _payload_size_bytes(payload_paths: Sequence[str | Path] | None) -> int:
    total = 0
    for payload_path in payload_paths or ():
        path = Path(payload_path)
        if path.exists() and path.is_file():
            total += path.stat().st_size
    return total


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_device_identifier(payload: dict[str, Any]) -> str:
    material = "|".join(
        [
            str(payload.get("serial", "")).strip(),
            str(payload.get("model", "")).strip(),
            str(int(payload.get("size_bytes", 0))),
            str(payload.get("disk_guid", "")).strip(),
        ]
    )
    return hashlib.sha256(material.encode()).hexdigest()[:12].upper()


def _validate_prewrite_target(payload: dict[str, Any], disk_number: int) -> str:
    if int(payload.get("disk_number", -1)) != disk_number:
        raise VentoyError("Disk number changed during Ventoy target validation.")
    bus_type = str(payload.get("bus_type", "")).strip().upper()
    if bus_type != "USB":
        raise VentoyError(f"Refusing Ventoy write to non-USB disk: {bus_type or 'unknown'}")
    blockers = [name for name in ("is_boot", "is_system", "contains_pagefile") if payload.get(name) is True]
    if blockers:
        raise VentoyError("Refusing Ventoy write to protected disk: " + ", ".join(blockers))
    if int(payload.get("size_bytes", 0)) <= 0:
        raise VentoyError("Ventoy target did not report a valid size.")
    if not str(payload.get("serial", "")).strip() and not str(payload.get("disk_guid", "")).strip():
        raise VentoyError("Ventoy target lacks both serial and disk GUID; identity is unstable.")
    return _stable_device_identifier(payload)


def _write_json_file(path: Path, payload: dict[str, Any]) -> None:
    atomic_write_json(path, payload)


def _verify_file_readable(path: Path) -> None:
    if not path.exists():
        raise VentoyError(f"Expected Ventoy payload file missing: {path}")
    if path.stat().st_size <= 0:
        raise VentoyError(f"Expected Ventoy payload file is empty: {path}")


def copy_iso_to_ventoy_root(
    source_iso: str | Path,
    data_root: str | Path,
    *,
    destination_name: str | None = None,
    filesystem: str = "EXFAT",
) -> Path:
    """Copy the ISO to the Ventoy data partition using a deterministic filename."""
    source = Path(source_iso)
    if not source.exists() or not source.is_file():
        raise VentoyError(f"ISO file does not exist: {source}")
    if filesystem.strip().upper() == "FAT32" and source.stat().st_size > FAT32_MAX_FILE_BYTES:
        raise VentoyError("ISO exceeds the FAT32 maximum file size; use an exFAT Ventoy data partition.")

    root = Path(data_root)
    root.mkdir(parents=True, exist_ok=True)
    target_name = destination_name or source.name
    destination = root / target_name
    shutil.copy2(source, destination)
    _verify_file_readable(destination)
    source_sha = _sha256(source)
    destination_sha = _sha256(destination)
    if source_sha != destination_sha:
        destination.unlink(missing_ok=True)
        raise VentoyError("Copied ISO failed source/destination SHA256 verification.")
    return destination


def _normalize_plan_contract(payload: PlanContract | dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload, PlanContract):
        return payload.model_dump()
    return validate_plan_contract(payload).model_dump()


def stage_ventoy_handoff_bundle(
    data_root: str | Path,
    source_iso: str | Path,
    plan_contract: PlanContract | dict[str, Any],
    *,
    wifi_profile: dict[str, Any] | None = None,
    install_log_text: str | None = None,
    backup_info: dict[str, Any] | None = None,
    verify_readability: bool = True,
    filesystem: str = "EXFAT",
    integrity_key: bytes | None = None,
) -> VentoyPayloadResult:
    """Write the ISO and handoff files into the Ventoy data partition."""
    root = Path(data_root)
    root.mkdir(parents=True, exist_ok=True)

    if wifi_profile is not None:
        raise VentoyError("Plaintext Wi-Fi handoff is disabled; enter credentials interactively in the live TUI.")
    if not integrity_key or len(integrity_key) < 32:
        raise VentoyError("A one-time handoff integrity key of at least 32 bytes is required.")

    iso_destination = copy_iso_to_ventoy_root(source_iso, root, filesystem=filesystem)
    plan_path = root / "omarchy" / "plan.json"
    normalized_plan = _normalize_plan_contract(plan_contract)
    _write_json_file(plan_path, normalized_plan)

    wifi_path: Path | None = None

    install_log_path: Path | None = None
    if install_log_text is not None:
        install_log_path = root / "omarchy" / "install.log"
        install_log_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(install_log_path, install_log_text)
        _verify_file_readable(install_log_path)

    backup_info_path: Path | None = None
    if backup_info is not None:
        backup_info_path = root / "omarchy" / "windows-backup-info.json"
        _write_json_file(backup_info_path, backup_info)

    file_hashes = {
        "iso": _sha256(iso_destination),
        "plan": _sha256(plan_path),
    }
    if install_log_path is not None:
        file_hashes["install_log"] = _sha256(install_log_path)
    if backup_info_path is not None:
        file_hashes["backup_info"] = _sha256(backup_info_path)
    authenticated_payload = {
        "schema_version": "1.0.0",
        "release_tag": normalized_plan["provenance"]["release_tag"],
        "build_commit": normalized_plan["provenance"]["build_commit"],
        "workflow_run_id": normalized_plan["provenance"]["workflow_run_id"],
        "producer_version": normalized_plan["provenance"]["producer_version"],
        "plan_schema_version": normalized_plan["meta"]["schema_version"],
        "disk_guid": normalized_plan["disk_identity"]["gpt_disk_guid"],
        "partition_guids": {
            "efi": normalized_plan["efi_identity"]["partition_guid"],
            "windows": normalized_plan["windows_partition_identity"]["partition_guid"],
        },
        "file_sha256": file_hashes,
    }
    canonical = json.dumps(authenticated_payload, sort_keys=True, separators=(",", ":")).encode()
    authenticated_payload["hmac_sha256"] = hmac.new(integrity_key, canonical, hashlib.sha256).hexdigest()
    handoff_manifest_path = root / "omarchy" / "handoff-manifest.json"
    _write_json_file(handoff_manifest_path, authenticated_payload)

    written_files = [str(iso_destination), str(plan_path), str(handoff_manifest_path)]
    if wifi_path is not None:
        written_files.append(str(wifi_path))
    if install_log_path is not None:
        written_files.append(str(install_log_path))
    if backup_info_path is not None:
        written_files.append(str(backup_info_path))

    if verify_readability:
        for file_path in (
            iso_destination,
            plan_path,
            handoff_manifest_path,
            install_log_path,
            backup_info_path,
        ):
            if file_path is not None:
                _verify_file_readable(file_path)

    return VentoyPayloadResult(
        iso_path=str(iso_destination),
        plan_path=str(plan_path),
        wifi_path=str(wifi_path) if wifi_path else None,
        install_log_path=str(install_log_path) if install_log_path else None,
        backup_info_path=str(backup_info_path) if backup_info_path else None,
        written_files=tuple(written_files),
        handoff_manifest_path=str(handoff_manifest_path),
        handoff_manifest_sha256=_sha256(handoff_manifest_path),
    )


def validate_ventoy_usb(
    disk_number: int,
    *,
    payload_paths: Sequence[str | Path] | None = None,
    reserve_bytes: int = DEFAULT_VENTOY_MIN_FREE_BYTES,
    ensure_drive_letter: bool = True,
    runner: CommandRunner | None = None,
) -> VentoyUsbValidation:
    """Validate a Ventoy USB layout, its writable data volume, and capacity."""
    active_runner = runner or SubprocessCommandRunner()
    payload = _collect_usb_layout(disk_number, active_runner)

    bus_type = str(payload.get("bus_type", "")).strip().upper()
    partition_style = str(payload.get("partition_style", "")).strip().upper()
    partition_count = int(payload.get("partition_count", 0))
    partitions = payload.get("partitions", [])
    if not isinstance(partitions, list):
        raise VentoyError("Ventoy disk metadata returned invalid partition data.")

    if bus_type != "USB":
        raise VentoyError(f"Refusing to validate a non-USB disk: {bus_type or 'unknown'}")
    if partition_style != "GPT":
        raise VentoyError(f"Ventoy USB must be GPT-partitioned, got {partition_style or 'unknown'}.")
    if partition_count < 2:
        raise VentoyError("Ventoy USB must expose at least two partitions.")

    data_partition = _choose_data_partition(partitions)
    partition_number = int(data_partition.get("partition_number", 0))
    if partition_number <= 0:
        raise VentoyError("Could not determine the Ventoy data partition number.")

    data_drive_letter = str(data_partition.get("drive_letter", "")).strip().upper()
    if not data_drive_letter and ensure_drive_letter:
        data_drive_letter = _assign_drive_letter(disk_number, partition_number, active_runner)
    if not data_drive_letter:
        raise VentoyError("Could not determine a writable Ventoy data drive letter.")

    filesystem = str(data_partition.get("filesystem", "")).strip().upper()
    if filesystem and filesystem not in DEFAULT_VENTOY_DATA_FILESYSTEMS:
        raise VentoyError(f"Unexpected Ventoy data filesystem: {filesystem}")

    root = _probe_volume_root(data_drive_letter)
    _ensure_writable_root(root)

    free_bytes = shutil.disk_usage(root).free
    payload_bytes = _payload_size_bytes(payload_paths)
    if filesystem == "FAT32":
        oversized = [
            str(Path(item))
            for item in payload_paths or ()
            if Path(item).is_file() and Path(item).stat().st_size > FAT32_MAX_FILE_BYTES
        ]
        if oversized:
            raise VentoyError("FAT32 cannot store payload file(s): " + ", ".join(oversized))
    required_bytes = max(0, reserve_bytes) + payload_bytes
    structure_verified = partition_count >= 2 and filesystem in DEFAULT_VENTOY_DATA_FILESYSTEMS
    warnings: list[str] = []
    if free_bytes < required_bytes:
        raise VentoyError(
            f"Ventoy data volume does not have enough free space: need {required_bytes} bytes, have {free_bytes}."
        )
    if not filesystem:
        warnings.append("Ventoy data partition volume filesystem could not be read reliably.")

    return VentoyUsbValidation(
        disk_number=disk_number,
        bus_type=bus_type,
        partition_style=partition_style,
        partition_count=partition_count,
        data_drive_letter=data_drive_letter,
        data_root=str(root),
        filesystem=filesystem,
        free_bytes=free_bytes,
        required_bytes=required_bytes,
        payload_bytes=payload_bytes,
        writable=True,
        structure_verified=structure_verified,
        warnings=tuple(warnings),
        stable_identifier=_stable_device_identifier(payload),
    )


def install_ventoy_to_usb(
    disk_number: int,
    *,
    allow_install: bool = False,
    payload_paths: Sequence[str | Path] | None = None,
    reserve_bytes: int = DEFAULT_VENTOY_MIN_FREE_BYTES,
    runner: CommandRunner | None = None,
    confirmation: str = "",
) -> VentoyPrepResult:
    """Locate or install Ventoy, write it to the USB disk, and validate the layout."""
    active_runner = runner or SubprocessCommandRunner()
    initial_payload = _collect_usb_layout(disk_number, active_runner)
    stable_identifier = _validate_prewrite_target(initial_payload, disk_number)
    expected_confirmation = f"ERASE {stable_identifier}"
    if confirmation.strip().upper() != expected_confirmation:
        raise VentoyError(f"Typed confirmation must exactly match: {expected_confirmation}")
    cli = acquire_ventoy_cli(allow_install=allow_install, runner=active_runner)
    final_payload = _collect_usb_layout(disk_number, active_runner)
    if _validate_prewrite_target(final_payload, disk_number) != stable_identifier:
        raise VentoyError("Ventoy target identity changed immediately before write.")
    completed = _run_checked(
        active_runner,
        [str(cli.path), "VTOYCLI", "/I", f"/PhyDrive:{disk_number}", "/GPT"],
    )
    install_output = completed.stdout.strip() or completed.stderr.strip()
    validation = validate_ventoy_usb(
        disk_number,
        payload_paths=payload_paths,
        reserve_bytes=reserve_bytes,
        runner=active_runner,
    )
    return VentoyPrepResult(cli=cli, validation=validation, install_output=install_output)


def build_handoff_manifest() -> dict[str, str]:
    """Create the deterministic Ventoy handoff metadata contract."""
    return {
        "status": "ready",
        "transport_model": "Ventoy",
        "handoff_plan_path": "omarchy/plan.json",
        "handoff_manifest_path": "omarchy/handoff-manifest.json",
        "network_credentials": "interactive-only",
        "firstboot_log_path": "omarchy/install.log",
        "backup_metadata_path": "omarchy/windows-backup-info.json",
    }
