"""Windows disk and partition probe with stable identifiers."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
import subprocess
from typing import Any, Protocol

from ...shared.models import DiskIdentity, FreeSpaceRange, PartitionIdentity


EFI_SYSTEM_PARTITION_GPT_TYPE = "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"


class DiskProbeError(RuntimeError):
    """Raised when disk identity data cannot be collected safely."""


class DiskLayoutProbe(Protocol):
    """Probe protocol to support deterministic tests and PowerShell runtime collection."""

    def collect_layout(self, system_drive: str) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class DiskProbeSnapshot:
    disk_identity: DiskIdentity
    efi_identity: PartitionIdentity
    windows_partition_identity: PartitionIdentity
    prepared_free_space_range: FreeSpaceRange
    partitions: tuple[PartitionIdentity, ...]

    def to_plan_fragment(self) -> dict[str, Any]:
        """Return the plan fragment fields this probe owns."""
        return {
            "disk_identity": self.disk_identity.model_dump(),
            "efi_identity": self.efi_identity.model_dump(),
            "windows_partition_identity": self.windows_partition_identity.model_dump(),
            "prepared_free_space_range": self.prepared_free_space_range.model_dump(),
            "partitions": [partition.model_dump() for partition in self.partitions],
        }


class PowerShellDiskLayoutProbe:
    """Collect disk and partition layout information through PowerShell commands."""

    def _run_ps(self, script: str) -> str:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            message = completed.stderr.strip() or completed.stdout.strip() or "PowerShell command failed."
            raise DiskProbeError(message)
        return completed.stdout.strip()

    def collect_layout(self, system_drive: str) -> dict[str, Any]:
        normalized_drive = normalize_drive_letter(system_drive)
        script = rf"""
$drive = '{normalized_drive}'
$systemPartition = Get-Partition -DriveLetter $drive -ErrorAction Stop
$disk = Get-Disk -Number $systemPartition.DiskNumber -ErrorAction Stop
$partitions = Get-Partition -DiskNumber $disk.Number -ErrorAction Stop | Sort-Object Offset

$partitionPayload = foreach ($partition in $partitions) {{
  $volume = $null
  try {{
    $volume = $partition | Get-Volume -ErrorAction Stop
  }} catch {{
  }}

  [PSCustomObject]@{{
    partition_number = [int]$partition.PartitionNumber
    guid = [string]$partition.Guid
    gpt_type = [string]$partition.GptType
    drive_letter = if ($partition.DriveLetter) {{ [string]$partition.DriveLetter }} else {{ '' }}
    offset_bytes = [int64]$partition.Offset
    size_bytes = [int64]$partition.Size
    filesystem = if ($volume -and $volume.FileSystem) {{ [string]$volume.FileSystem }} else {{ '' }}
  }}
}}

$serial = [string]$disk.SerialNumber
if ([string]::IsNullOrWhiteSpace($serial)) {{
  try {{
    $physical = Get-PhysicalDisk | Where-Object DeviceId -eq $disk.Number | Select-Object -First 1
    if ($physical -and -not [string]::IsNullOrWhiteSpace([string]$physical.SerialNumber)) {{
      $serial = [string]$physical.SerialNumber
    }}
  }} catch {{
  }}
}}

$payload = [PSCustomObject]@{{
  disk_number = [int]$disk.Number
  model = [string]$disk.FriendlyName
  serial = [string]$serial
  size_bytes = [int64]$disk.Size
  partition_style = [string]$disk.PartitionStyle
  gpt_disk_guid = [string]$disk.Guid
  logical_sector_size = [int64]$disk.LogicalSectorSize
  largest_free_extent_bytes = [int64]$disk.LargestFreeExtent
  partitions = $partitionPayload
}}

$payload | ConvertTo-Json -Depth 8 -Compress
"""
        output = self._run_ps(script)
        try:
            payload = json.loads(output)
        except json.JSONDecodeError as exc:
            raise DiskProbeError(f"Failed to parse disk probe JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise DiskProbeError("Disk probe did not return an object payload.")
        return payload


def normalize_drive_letter(system_drive: str) -> str:
    value = system_drive.strip().rstrip(":").upper()
    if not re.fullmatch(r"[A-Z]", value):
        raise ValueError(f"Invalid system drive letter: {system_drive!r}")
    return value


def _normalize_guid(value: str) -> str:
    normalized = value.strip().strip("{}").lower()
    return normalized


def _partition_guid_or_fallback(record: dict[str, Any], disk_number: int) -> str:
    guid = _normalize_guid(str(record.get("guid", "")))
    if guid:
        return guid
    part_number = int(record.get("partition_number", 0))
    return f"disk{disk_number}-part{part_number}"


def _build_partition_identity(record: dict[str, Any], *, disk_number: int, sector_size: int) -> PartitionIdentity:
    offset_bytes = int(record.get("offset_bytes", 0))
    size_bytes = int(record.get("size_bytes", 0))
    if size_bytes <= 0:
        raise DiskProbeError(f"Partition has invalid size: {size_bytes}")
    start_sector = offset_bytes // sector_size
    end_sector = ((offset_bytes + size_bytes) // sector_size) - 1
    if end_sector < start_sector:
        end_sector = start_sector

    partition_guid = _partition_guid_or_fallback(record, disk_number)
    filesystem = str(record.get("filesystem", "")).strip()
    return PartitionIdentity(
        partition_guid=partition_guid,
        partuuid=partition_guid,
        filesystem=filesystem,
        start_sector=start_sector,
        end_sector=end_sector,
        size_bytes=size_bytes,
    )


def _find_windows_partition(records: list[dict[str, Any]], system_drive: str) -> dict[str, Any]:
    for record in records:
        if str(record.get("drive_letter", "")).strip().upper() == system_drive:
            return record
    raise DiskProbeError(f"Could not locate system partition for drive {system_drive}.")


def _find_efi_partition(records: list[dict[str, Any]]) -> dict[str, Any]:
    for record in records:
        gpt_type = _normalize_guid(str(record.get("gpt_type", "")))
        if gpt_type == EFI_SYSTEM_PARTITION_GPT_TYPE:
            return record

    for record in records:
        filesystem = str(record.get("filesystem", "")).strip().upper()
        if filesystem == "FAT32":
            return record

    raise DiskProbeError("Could not locate EFI system partition.")


def _compute_largest_free_range(
    *,
    partitions: tuple[PartitionIdentity, ...],
    disk_size_bytes: int,
    sector_size: int,
) -> FreeSpaceRange:
    if disk_size_bytes <= 0:
        raise DiskProbeError("Disk size must be positive.")

    total_sectors = max(1, disk_size_bytes // sector_size)
    max_sector = total_sectors - 1
    occupied = sorted(
        (
            max(0, partition.start_sector),
            min(max_sector, partition.end_sector),
        )
        for partition in partitions
    )

    gaps: list[tuple[int, int]] = []
    cursor = 0
    for start_sector, end_sector in occupied:
        if start_sector > cursor:
            gaps.append((cursor, start_sector - 1))
        cursor = max(cursor, end_sector + 1)

    if cursor <= max_sector:
        gaps.append((cursor, max_sector))

    if not gaps:
        raise DiskProbeError("No unallocated free-space region found on target disk.")

    start_sector, end_sector = max(gaps, key=lambda item: item[1] - item[0] + 1)
    size_bytes = (end_sector - start_sector + 1) * sector_size
    return FreeSpaceRange(
        start_sector=start_sector,
        end_sector=end_sector,
        size_bytes=size_bytes,
    )


def collect_disk_probe_snapshot(
    probe: DiskLayoutProbe | None = None,
    *,
    system_drive: str = "C",
) -> DiskProbeSnapshot:
    """Collect and normalize disk identity data for the Windows handoff contract."""
    active_probe = probe or PowerShellDiskLayoutProbe()
    normalized_drive = normalize_drive_letter(system_drive)
    payload = active_probe.collect_layout(normalized_drive)

    partition_style = str(payload.get("partition_style", "")).strip().upper()
    if partition_style not in {"GPT", "MBR"}:
        raise DiskProbeError(f"Unsupported partition style reported: {partition_style!r}")

    disk_number = int(payload.get("disk_number", 0))
    disk_size_bytes = int(payload.get("size_bytes", 0))
    if disk_size_bytes <= 0:
        raise DiskProbeError("Disk size bytes must be greater than zero.")

    sector_size = int(payload.get("logical_sector_size", 0)) or 512
    if sector_size <= 0:
        sector_size = 512

    model = str(payload.get("model", "")).strip() or f"Disk {disk_number}"
    serial = str(payload.get("serial", "")).strip() or f"disk-{disk_number}"
    gpt_disk_guid = _normalize_guid(str(payload.get("gpt_disk_guid", "")))
    if partition_style == "GPT" and not gpt_disk_guid:
        raise DiskProbeError("GPT disk did not report a disk GUID.")
    if not gpt_disk_guid:
        gpt_disk_guid = f"disk-{disk_number}"

    raw_partitions = payload.get("partitions", [])
    if not isinstance(raw_partitions, list) or not raw_partitions:
        raise DiskProbeError("Disk probe returned no partition records.")

    windows_record = _find_windows_partition(raw_partitions, normalized_drive)
    efi_record = _find_efi_partition(raw_partitions)

    partition_identities = tuple(
        _build_partition_identity(record, disk_number=disk_number, sector_size=sector_size)
        for record in raw_partitions
    )
    windows_partition_identity = _build_partition_identity(
        windows_record,
        disk_number=disk_number,
        sector_size=sector_size,
    )
    efi_identity = _build_partition_identity(
        efi_record,
        disk_number=disk_number,
        sector_size=sector_size,
    )
    prepared_free_space_range = _compute_largest_free_range(
        partitions=partition_identities,
        disk_size_bytes=disk_size_bytes,
        sector_size=sector_size,
    )

    disk_identity = DiskIdentity(
        disk_serial=serial,
        disk_model=model,
        disk_size_bytes=disk_size_bytes,
        gpt_disk_guid=gpt_disk_guid,
        partition_style=partition_style,
    )

    return DiskProbeSnapshot(
        disk_identity=disk_identity,
        efi_identity=efi_identity,
        windows_partition_identity=windows_partition_identity,
        prepared_free_space_range=prepared_free_space_range,
        partitions=partition_identities,
    )
