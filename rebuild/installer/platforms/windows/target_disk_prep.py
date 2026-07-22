"""Plan a Linux install region on a separate (non-Windows) target disk.

Unlike the Windows system-disk path, installing onto a separate disk needs no
destructive shrink: an empty disk is used whole, and a disk with data uses its
existing unallocated gap. This module therefore only validates the target and
carves the exact partition region; the real partition/format work is performed
Linux-side by archinstall against the region computed here.
"""

from __future__ import annotations

from dataclasses import dataclass

from .disk_probe import TargetDiskSnapshot
from ...shared.models import FreeSpaceRange


class TargetDiskPrepError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class TargetDiskPrepResult:
    disk_number: int
    mode: str
    total_disk_bytes: int
    available_free_bytes: int
    requested_linux_bytes: int
    install_partition_range: FreeSpaceRange
    fits: bool
    would_erase_existing_data: bool
    existing_esp_present: bool

    @property
    def linux_bytes(self) -> int:
        return self.install_partition_range.size_bytes


def _align_down(sectors: int, alignment: int) -> int:
    return (sectors // alignment) * alignment


def prepare_target_disk(
    snapshot: TargetDiskSnapshot,
    *,
    requested_linux_bytes: int,
    minimum_linux_bytes: int,
) -> TargetDiskPrepResult:
    """Validate and carve the Linux install region on a target disk.

    whole_disk: Linux occupies the entire usable region (the disk is dedicated
    to Linux; if it holds data, that data is erased on install).
    free_space: Linux occupies up to `requested_linux_bytes` from the start of
    the largest unallocated gap, leaving the rest of the disk untouched.
    """
    if minimum_linux_bytes <= 0:
        raise TargetDiskPrepError("minimum_linux_bytes must be positive.")
    free = snapshot.install_free_space_range
    sector = snapshot.logical_sector_size
    alignment = max(1, (1024**2) // sector)

    if snapshot.mode == "whole_disk":
        region = free
        would_erase = not snapshot.is_empty
    elif snapshot.mode == "free_space":
        want = requested_linux_bytes if requested_linux_bytes > 0 else free.size_bytes
        want = max(minimum_linux_bytes, min(want, free.size_bytes))
        want_sectors = _align_down(want // sector, alignment)
        end_sector = free.start_sector + want_sectors - 1
        if end_sector > free.end_sector:
            end_sector = free.end_sector
        region = FreeSpaceRange(
            start_sector=free.start_sector,
            end_sector=end_sector,
            logical_sector_size=sector,
            size_bytes=max(0, (end_sector - free.start_sector + 1)) * sector,
        )
        would_erase = False
    else:
        raise TargetDiskPrepError(f"Unsupported target disk mode: {snapshot.mode!r}")

    fits = region.size_bytes >= minimum_linux_bytes
    return TargetDiskPrepResult(
        disk_number=snapshot.disk_number,
        mode=snapshot.mode,
        total_disk_bytes=snapshot.disk_size_bytes,
        available_free_bytes=free.size_bytes,
        requested_linux_bytes=requested_linux_bytes,
        install_partition_range=region,
        fits=fits,
        would_erase_existing_data=would_erase,
        existing_esp_present=snapshot.existing_esp is not None,
    )
