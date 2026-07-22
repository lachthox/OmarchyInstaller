"""Windows disk and partition probe with stable identifiers."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
import subprocess
from typing import Any, Literal, Protocol, cast

from ...shared.models import DiskIdentity, FreeSpaceRange, PartitionIdentity


EFI_SYSTEM_PARTITION_GPT_TYPE = "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"


class DiskProbeError(RuntimeError):
    """Raised when disk identity data cannot be collected safely."""


class DiskLayoutProbe(Protocol):
    """Probe protocol to support deterministic tests and PowerShell runtime collection."""

    def collect_layout(self, system_drive: str) -> dict[str, Any]: ...


class TargetDiskLayoutProbe(Protocol):
    """Probe for an arbitrary disk by number (may have no Windows partition)."""

    def collect_disk_layout(self, disk_number: int) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class TargetDiskSnapshot:
    """A disk considered as a Linux install target.

    Unlike DiskProbeSnapshot this does not require a Windows partition or an
    ESP: the target may be an empty disk (whole-disk install) or a disk that
    already holds data where Linux uses the unallocated free space.
    """

    disk_number: int
    model: str
    serial: str
    disk_size_bytes: int
    logical_sector_size: int
    partition_style: str
    gpt_disk_guid: str
    partitions: tuple[PartitionIdentity, ...]
    install_free_space_range: FreeSpaceRange
    mode: str  # "whole_disk" | "free_space"
    existing_esp: PartitionIdentity | None
    is_empty: bool

    def to_fragment(self) -> dict[str, Any]:
        return {
            "disk_number": self.disk_number,
            "model": self.model,
            "serial": self.serial,
            "disk_size_bytes": self.disk_size_bytes,
            "logical_sector_size": self.logical_sector_size,
            "partition_style": self.partition_style,
            "gpt_disk_guid": self.gpt_disk_guid,
            "mode": self.mode,
            "is_empty": self.is_empty,
            "install_free_space_range": self.install_free_space_range.model_dump(),
            "existing_esp": self.existing_esp.model_dump() if self.existing_esp else None,
            "partitions": [partition.model_dump() for partition in self.partitions],
        }


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
    filesystem_uuid = if ($volume -and $volume.UniqueId) {{ [string]$volume.UniqueId }} else {{ '' }}
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

    def collect_disk_layout(self, disk_number: int) -> dict[str, Any]:
        """Collect layout for an arbitrary disk by number (may be empty/RAW)."""
        script = rf"""
$disk = Get-Disk -Number {int(disk_number)} -ErrorAction Stop
$partitions = @(Get-Partition -DiskNumber $disk.Number -ErrorAction SilentlyContinue | Sort-Object Offset)
$partitionPayload = foreach ($partition in $partitions) {{
  $volume = $null
  try {{ $volume = $partition | Get-Volume -ErrorAction Stop }} catch {{ }}
  [PSCustomObject]@{{
    partition_number = [int]$partition.PartitionNumber
    guid = [string]$partition.Guid
    gpt_type = [string]$partition.GptType
    drive_letter = if ($partition.DriveLetter) {{ [string]$partition.DriveLetter }} else {{ '' }}
    offset_bytes = [int64]$partition.Offset
    size_bytes = [int64]$partition.Size
    filesystem = if ($volume -and $volume.FileSystem) {{ [string]$volume.FileSystem }} else {{ '' }}
    filesystem_uuid = if ($volume -and $volume.UniqueId) {{ [string]$volume.UniqueId }} else {{ '' }}
  }}
}}
$payload = [PSCustomObject]@{{
  disk_number = [int]$disk.Number
  model = [string]$disk.FriendlyName
  serial = [string]$disk.SerialNumber
  size_bytes = [int64]$disk.Size
  partition_style = [string]$disk.PartitionStyle
  gpt_disk_guid = [string]$disk.Guid
  logical_sector_size = [int64]$disk.LogicalSectorSize
  largest_free_extent_bytes = [int64]$disk.LargestFreeExtent
  partitions = @($partitionPayload)
}}
ConvertTo-Json -InputObject $payload -Depth 8 -Compress
"""
        output = self._run_ps(script)
        try:
            payload = json.loads(output)
        except json.JSONDecodeError as exc:
            raise DiskProbeError(f"Failed to parse target disk probe JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise DiskProbeError("Target disk probe did not return an object payload.")
        return payload


def normalize_drive_letter(system_drive: str) -> str:
    value = system_drive.strip().rstrip(":").upper()
    if not re.fullmatch(r"[A-Z]", value):
        raise ValueError(f"Invalid system drive letter: {system_drive!r}")
    return value


def _normalize_guid(value: str) -> str:
    normalized = value.strip().strip("{}").lower()
    return normalized


def _partition_guid(record: dict[str, Any]) -> str:
    guid = _normalize_guid(str(record.get("guid", "")))
    if not guid:
        raise DiskProbeError("GPT partition did not report a partition GUID.")
    return guid


def _build_partition_identity(record: dict[str, Any], *, disk_number: int, sector_size: int) -> PartitionIdentity:
    offset_bytes = int(record.get("offset_bytes", 0))
    size_bytes = int(record.get("size_bytes", 0))
    if size_bytes <= 0:
        raise DiskProbeError(f"Partition has invalid size: {size_bytes}")
    start_sector = offset_bytes // sector_size
    end_sector = ((offset_bytes + size_bytes) // sector_size) - 1
    if end_sector < start_sector:
        end_sector = start_sector

    partition_guid = _partition_guid(record)
    filesystem = str(record.get("filesystem", "")).strip()
    return PartitionIdentity(
        partition_guid=partition_guid,
        partuuid=partition_guid,
        filesystem_uuid=str(record.get("filesystem_uuid", "")).strip(),
        filesystem_type=filesystem,
        partition_number=int(record.get("partition_number", 0)),
        start_sector=start_sector,
        end_sector=end_sector,
        logical_sector_size=sector_size,
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

    raise DiskProbeError("Could not locate EFI system partition.")


def _align_up(value: int, alignment: int) -> int:
    return ((value + alignment - 1) // alignment) * alignment


def _compute_adjacent_free_range(
    *,
    windows_partition: PartitionIdentity,
    partitions: tuple[PartitionIdentity, ...],
    disk_size_bytes: int,
    sector_size: int,
) -> FreeSpaceRange:
    if disk_size_bytes <= 0:
        raise DiskProbeError("Disk size must be positive.")

    alignment_sectors = max(1, (1024**2) // sector_size)
    start_sector = _align_up(windows_partition.end_sector + 1, alignment_sectors)
    following = sorted(
        partition.start_sector
        for partition in partitions
        if partition.start_sector > windows_partition.end_sector
    )
    if following:
        end_sector = following[0] - 1
    else:
        total_sectors = disk_size_bytes // sector_size
        conservative_gpt_tail = alignment_sectors
        end_sector = total_sectors - conservative_gpt_tail - 1
    if end_sector < start_sector:
        return FreeSpaceRange(
            start_sector=start_sector,
            end_sector=start_sector - 1,
            logical_sector_size=sector_size,
            size_bytes=0,
        )
    size_bytes = (end_sector - start_sector + 1) * sector_size
    return FreeSpaceRange(
        start_sector=start_sector,
        end_sector=end_sector,
        logical_sector_size=sector_size,
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
    if partition_style != "GPT":
        raise DiskProbeError(f"GPT is required; reported partition style: {partition_style!r}")

    disk_number = int(payload.get("disk_number", 0))
    disk_size_bytes = int(payload.get("size_bytes", 0))
    if disk_size_bytes <= 0:
        raise DiskProbeError("Disk size bytes must be greater than zero.")

    sector_size = int(payload.get("logical_sector_size", 0)) or 512
    if sector_size <= 0:
        sector_size = 512

    model = str(payload.get("model", "")).strip() or f"Disk {disk_number}"
    serial = str(payload.get("serial", "")).strip()
    gpt_disk_guid = _normalize_guid(str(payload.get("gpt_disk_guid", "")))
    if not gpt_disk_guid:
        raise DiskProbeError("GPT disk did not report a disk GUID.")

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
    prepared_free_space_range = _compute_adjacent_free_range(
        windows_partition=windows_partition_identity,
        partitions=partition_identities,
        disk_size_bytes=disk_size_bytes,
        sector_size=sector_size,
    )

    disk_identity = DiskIdentity(
        disk_serial=serial,
        runtime_disk_number=disk_number,
        disk_model=model,
        disk_size_bytes=disk_size_bytes,
        logical_sector_size=sector_size,
        gpt_disk_guid=gpt_disk_guid,
        partition_style=cast(Literal["GPT"], partition_style),
    )

    return DiskProbeSnapshot(
        disk_identity=disk_identity,
        efi_identity=efi_identity,
        windows_partition_identity=windows_partition_identity,
        prepared_free_space_range=prepared_free_space_range,
        partitions=partition_identities,
    )


def _partition_extents(raw_partitions: list[dict[str, Any]], sector_size: int) -> list[tuple[int, int]]:
    """Return sorted (start_sector, end_sector) extents from raw partition records."""
    extents: list[tuple[int, int]] = []
    for record in raw_partitions:
        size_bytes = int(record.get("size_bytes", 0) or 0)
        if size_bytes <= 0:
            continue
        offset_bytes = int(record.get("offset_bytes", 0) or 0)
        start = offset_bytes // sector_size
        end = ((offset_bytes + size_bytes) // sector_size) - 1
        if end < start:
            end = start
        extents.append((start, end))
    return sorted(extents)


def _free_range_between(start_sector: int, end_sector: int, sector_size: int) -> FreeSpaceRange:
    if end_sector < start_sector:
        return FreeSpaceRange(
            start_sector=start_sector,
            end_sector=start_sector - 1,
            logical_sector_size=sector_size,
            size_bytes=0,
        )
    return FreeSpaceRange(
        start_sector=start_sector,
        end_sector=end_sector,
        logical_sector_size=sector_size,
        size_bytes=(end_sector - start_sector + 1) * sector_size,
    )


def _usable_disk_bounds(disk_size_bytes: int, sector_size: int) -> tuple[int, int, int]:
    """First aligned usable sector, last usable sector (GPT tail reserved), alignment."""
    alignment = max(1, (1024**2) // sector_size)
    total_sectors = disk_size_bytes // sector_size
    first_usable = alignment  # leave the primary GPT + a 1 MiB alignment gap
    last_usable = total_sectors - alignment - 1  # reserve a tail for the backup GPT
    return first_usable, last_usable, alignment


def _whole_disk_free_range(disk_size_bytes: int, sector_size: int) -> FreeSpaceRange:
    first_usable, last_usable, _ = _usable_disk_bounds(disk_size_bytes, sector_size)
    return _free_range_between(first_usable, last_usable, sector_size)


def _largest_free_gap(
    extents: list[tuple[int, int]], disk_size_bytes: int, sector_size: int
) -> FreeSpaceRange:
    first_usable, last_usable, alignment = _usable_disk_bounds(disk_size_bytes, sector_size)
    best = _free_range_between(first_usable, first_usable - 1, sector_size)  # empty
    cursor = first_usable
    for start, end in extents:
        gap_start = _align_up(cursor, alignment)
        gap_end = min(start - 1, last_usable)
        candidate = _free_range_between(gap_start, gap_end, sector_size)
        if candidate.size_bytes > best.size_bytes:
            best = candidate
        cursor = max(cursor, end + 1)
    trailing = _free_range_between(_align_up(cursor, alignment), last_usable, sector_size)
    if trailing.size_bytes > best.size_bytes:
        best = trailing
    return best


def collect_target_disk_snapshot(
    disk_number: int,
    *,
    mode: str = "auto",
    probe: TargetDiskLayoutProbe | None = None,
) -> TargetDiskSnapshot:
    """Describe an arbitrary disk as a Linux install target.

    mode: "auto" picks whole_disk for an empty disk and free_space otherwise;
    "whole_disk" or "free_space" force a specific model.
    """
    active_probe = probe or PowerShellDiskLayoutProbe()
    payload = active_probe.collect_disk_layout(disk_number)

    disk_size_bytes = int(payload.get("size_bytes", 0) or 0)
    if disk_size_bytes <= 0:
        raise DiskProbeError("Target disk size must be greater than zero.")
    sector_size = int(payload.get("logical_sector_size", 0) or 0) or 512
    partition_style = str(payload.get("partition_style", "") or "").strip().upper()
    gpt_disk_guid = _normalize_guid(str(payload.get("gpt_disk_guid", "") or ""))
    model = str(payload.get("model", "") or "").strip() or f"Disk {disk_number}"
    serial = str(payload.get("serial", "") or "").strip()

    raw_partitions = payload.get("partitions", []) or []
    if not isinstance(raw_partitions, list):
        raise DiskProbeError("Target disk probe returned a non-list partitions field.")
    is_empty = len(raw_partitions) == 0

    resolved_mode = mode
    if resolved_mode == "auto":
        resolved_mode = "whole_disk" if is_empty else "free_space"
    if resolved_mode not in ("whole_disk", "free_space"):
        raise DiskProbeError(f"Unknown target disk mode: {mode!r}")

    if resolved_mode == "whole_disk":
        install_free = _whole_disk_free_range(disk_size_bytes, sector_size)
    else:
        extents = _partition_extents(raw_partitions, sector_size)
        install_free = _largest_free_gap(extents, disk_size_bytes, sector_size)

    # Build identities only for GPT partitions that report a GUID (skip others).
    identities: list[PartitionIdentity] = []
    existing_esp: PartitionIdentity | None = None
    for record in raw_partitions:
        if not _normalize_guid(str(record.get("guid", "") or "")):
            continue
        identity = _build_partition_identity(record, disk_number=disk_number, sector_size=sector_size)
        identities.append(identity)
        if _normalize_guid(str(record.get("gpt_type", "") or "")) == EFI_SYSTEM_PARTITION_GPT_TYPE:
            existing_esp = identity

    return TargetDiskSnapshot(
        disk_number=disk_number,
        model=model,
        serial=serial,
        disk_size_bytes=disk_size_bytes,
        logical_sector_size=sector_size,
        partition_style=partition_style or ("RAW" if is_empty else "UNKNOWN"),
        gpt_disk_guid=gpt_disk_guid,
        partitions=tuple(identities),
        install_free_space_range=install_free,
        mode=resolved_mode,
        existing_esp=existing_esp,
        is_empty=is_empty,
    )
