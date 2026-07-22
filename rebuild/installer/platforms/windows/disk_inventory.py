"""Enumerate and classify all physical disks on a Windows host.

This is read-only: it lists every physical disk with enough information to tell
USB removable media apart from fixed internal drives (HDD / SATA SSD / NVMe
SSD), so the installer can offer a genuine choice of install target and never
mistake the Ventoy boot stick for a disk to install onto.

The PowerShell probe is isolated behind `DiskInventoryProbe` so `enumerate_disks`
can be unit-tested with deterministic payloads and no real hardware.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import subprocess
from typing import Any, Protocol


class DiskInventoryError(RuntimeError):
    """Raised when the physical-disk inventory cannot be collected."""


class DiskInventoryProbe(Protocol):
    def collect_disks(self) -> list[dict[str, Any]]: ...


@dataclass(frozen=True, slots=True)
class DiskInfo:
    number: int
    model: str
    serial: str
    size_bytes: int
    bus_type: str
    media_type: str
    partition_style: str
    is_system: bool
    is_boot: bool
    is_read_only: bool
    partition_count: int
    largest_free_extent_bytes: int

    @property
    def is_usb(self) -> bool:
        return self.bus_type.strip().upper() == "USB"

    @property
    def is_empty(self) -> bool:
        """No partitions, or an uninitialised (RAW) disk."""
        return self.partition_count <= 0 or self.partition_style.strip().upper() == "RAW"

    @property
    def kind_label(self) -> str:
        """Human label such as 'NVMe SSD', 'SATA HDD', or 'USB drive'."""
        return classify_disk_kind(self.bus_type, self.media_type)

    @property
    def size_gib(self) -> int:
        return int(self.size_bytes // (1024**3))

    @property
    def free_gib(self) -> int:
        return int(self.largest_free_extent_bytes // (1024**3))


def classify_disk_kind(bus_type: str, media_type: str) -> str:
    bus = bus_type.strip().upper()
    media = media_type.strip().upper()
    if bus == "USB":
        return "USB drive"
    media_word = "SSD" if media == "SSD" else ("HDD" if media == "HDD" else "")
    if bus == "NVME":
        return f"NVMe {media_word or 'SSD'}"
    bus_word = {
        "SATA": "SATA",
        "ATA": "SATA",
        "SAS": "SAS",
        "RAID": "RAID",
        "SCSI": "SCSI",
        "SD": "SD card",
        "MMC": "eMMC",
    }.get(bus, bus.title() if bus else "Disk")
    if media_word:
        return f"{bus_word} {media_word}"
    return f"{bus_word} disk"


def _build_disk_info(record: dict[str, Any]) -> DiskInfo:
    try:
        number = int(record["number"])
    except (KeyError, TypeError, ValueError) as exc:
        raise DiskInventoryError(f"Disk record is missing a valid number: {record!r}") from exc
    size_bytes = int(record.get("size_bytes", 0) or 0)
    return DiskInfo(
        number=number,
        model=str(record.get("model", "") or "").strip() or f"Disk {number}",
        serial=str(record.get("serial", "") or "").strip(),
        size_bytes=size_bytes,
        bus_type=str(record.get("bus_type", "") or "").strip(),
        media_type=str(record.get("media_type", "") or "").strip(),
        partition_style=str(record.get("partition_style", "") or "").strip(),
        is_system=bool(record.get("is_system", False)),
        is_boot=bool(record.get("is_boot", False)),
        is_read_only=bool(record.get("is_read_only", False)),
        partition_count=int(record.get("partition_count", 0) or 0),
        largest_free_extent_bytes=int(record.get("largest_free_extent_bytes", 0) or 0),
    )


def enumerate_disks(probe: DiskInventoryProbe) -> tuple[DiskInfo, ...]:
    """Return every physical disk, ordered by disk number."""
    records = probe.collect_disks()
    if not isinstance(records, list):
        raise DiskInventoryError("Disk inventory probe did not return a list.")
    disks = [_build_disk_info(record) for record in records if isinstance(record, dict)]
    if not disks:
        raise DiskInventoryError("No physical disks were reported.")
    return tuple(sorted(disks, key=lambda disk: disk.number))


def install_target_candidates(disks: tuple[DiskInfo, ...]) -> tuple[DiskInfo, ...]:
    """Fixed internal disks eligible as install targets (USB media excluded)."""
    return tuple(disk for disk in disks if not disk.is_usb and not disk.is_read_only)


class PowerShellDiskInventoryProbe:
    """Enumerate physical disks via Get-Disk joined with Get-PhysicalDisk."""

    def _run_ps(self, script: str) -> str:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            message = completed.stderr.strip() or completed.stdout.strip() or "PowerShell command failed."
            raise DiskInventoryError(message)
        return completed.stdout.strip()

    def collect_disks(self) -> list[dict[str, Any]]:
        script = r"""
$physical = @{}
foreach ($p in (Get-PhysicalDisk -ErrorAction SilentlyContinue)) {
  $physical[[string]$p.DeviceId] = [string]$p.MediaType
}
$rows = foreach ($d in (Get-Disk -ErrorAction Stop | Sort-Object Number)) {
  $media = ''
  if ($physical.ContainsKey([string]$d.Number)) { $media = $physical[[string]$d.Number] }
  [PSCustomObject]@{
    number = [int]$d.Number
    model = [string]$d.FriendlyName
    serial = [string]$d.SerialNumber
    size_bytes = [int64]$d.Size
    bus_type = [string]$d.BusType
    media_type = $media
    partition_style = [string]$d.PartitionStyle
    is_system = [bool]$d.IsSystem
    is_boot = [bool]$d.IsBoot
    is_read_only = [bool]$d.IsReadOnly
    partition_count = [int]$d.NumberOfPartitions
    largest_free_extent_bytes = [int64]$d.LargestFreeExtent
  }
}
# Force an array so a single disk still serialises as a JSON list.
ConvertTo-Json -InputObject @($rows) -Depth 5 -Compress
"""
        output = self._run_ps(script)
        try:
            payload = json.loads(output)
        except json.JSONDecodeError as exc:
            raise DiskInventoryError(f"Failed to parse disk inventory JSON: {exc}") from exc
        if isinstance(payload, dict):
            payload = [payload]
        if not isinstance(payload, list):
            raise DiskInventoryError("Disk inventory did not return a JSON array.")
        return payload


def collect_disk_inventory(probe: DiskInventoryProbe | None = None) -> tuple[DiskInfo, ...]:
    return enumerate_disks(probe or PowerShellDiskInventoryProbe())
