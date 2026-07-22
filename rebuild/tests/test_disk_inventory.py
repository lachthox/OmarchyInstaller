from __future__ import annotations

import pytest

from rebuild.installer.platforms.windows.disk_inventory import (
    DiskInventoryError,
    classify_disk_kind,
    enumerate_disks,
    install_target_candidates,
    usb_drive_candidates,
)


class FakeProbe:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def collect_disks(self) -> list[dict]:
        return self._rows


def disk_row(number: int, **overrides) -> dict:
    base = {
        "number": number,
        "model": f"Model{number}",
        "serial": f"SER{number}",
        "size_bytes": 512 * 1024**3,
        "bus_type": "NVMe",
        "media_type": "SSD",
        "partition_style": "GPT",
        "is_system": False,
        "is_boot": False,
        "is_read_only": False,
        "partition_count": 3,
        "largest_free_extent_bytes": 0,
    }
    base.update(overrides)
    return base


@pytest.mark.parametrize(
    ("bus", "media", "expected"),
    [
        ("USB", "", "USB drive"),
        ("USB", "SSD", "USB drive"),
        ("NVMe", "SSD", "NVMe SSD"),
        ("NVMe", "", "NVMe SSD"),
        ("SATA", "SSD", "SATA SSD"),
        ("SATA", "HDD", "SATA HDD"),
        ("ATA", "HDD", "SATA HDD"),
        ("SAS", "HDD", "SAS HDD"),
        ("RAID", "", "RAID disk"),
    ],
)
def test_classify_disk_kind(bus: str, media: str, expected: str) -> None:
    assert classify_disk_kind(bus, media) == expected


def test_enumerate_orders_by_number_and_exposes_flags() -> None:
    probe = FakeProbe(
        [
            disk_row(1, bus_type="USB", media_type="", partition_count=1),
            disk_row(0, bus_type="NVMe", media_type="SSD", is_system=True, is_boot=True),
        ]
    )
    disks = enumerate_disks(probe)
    assert [d.number for d in disks] == [0, 1]
    system, usb = disks
    assert system.is_system and not system.is_usb
    assert system.kind_label == "NVMe SSD"
    assert usb.is_usb
    assert usb.kind_label == "USB drive"


def test_empty_and_raw_disks_flagged_empty() -> None:
    probe = FakeProbe(
        [
            disk_row(0, partition_count=0, partition_style="RAW"),
            disk_row(1, partition_count=4, partition_style="GPT"),
        ]
    )
    empty, used = enumerate_disks(probe)
    assert empty.is_empty is True
    assert used.is_empty is False


def test_install_candidates_exclude_usb_and_readonly() -> None:
    probe = FakeProbe(
        [
            disk_row(0, bus_type="NVMe", is_system=True),
            disk_row(1, bus_type="SATA", media_type="HDD"),
            disk_row(2, bus_type="USB"),
            disk_row(3, bus_type="SATA", is_read_only=True),
        ]
    )
    candidates = install_target_candidates(enumerate_disks(probe))
    assert [d.number for d in candidates] == [0, 1]


def test_usb_candidates_exclude_protected_and_readonly_disks() -> None:
    probe = FakeProbe(
        [
            disk_row(0, bus_type="NVMe", is_system=True),
            disk_row(1, bus_type="USB"),
            disk_row(2, bus_type="USB", is_read_only=True),
            disk_row(3, bus_type="USB", is_boot=True),
            disk_row(4, bus_type="USB", size_bytes=0),
        ]
    )

    candidates = usb_drive_candidates(enumerate_disks(probe))

    assert [disk.number for disk in candidates] == [1]


def test_missing_number_and_empty_inventory_raise() -> None:
    with pytest.raises(DiskInventoryError):
        enumerate_disks(FakeProbe([{"model": "no number"}]))
    with pytest.raises(DiskInventoryError):
        enumerate_disks(FakeProbe([]))
