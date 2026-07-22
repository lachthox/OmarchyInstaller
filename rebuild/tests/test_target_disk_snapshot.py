from __future__ import annotations

import pytest

from rebuild.installer.platforms.windows.disk_probe import (
    DiskProbeError,
    collect_target_disk_snapshot,
)


GIB = 1024**3
EFI_TYPE = "{c12a7328-f81f-11d2-ba4b-00a0c93ec93b}"


class FakeDiskProbe:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def collect_disk_layout(self, disk_number: int) -> dict:
        return dict(self._payload, disk_number=disk_number)


def part(number: int, offset_gib: float, size_gib: float, *, guid: str, gpt_type: str = "") -> dict:
    return {
        "partition_number": number,
        "guid": guid,
        "gpt_type": gpt_type,
        "offset_bytes": int(offset_gib * GIB),
        "size_bytes": int(size_gib * GIB),
        "filesystem": "NTFS",
        "filesystem_uuid": "",
    }


def disk_payload(size_gib: int, partitions: list[dict], *, style: str = "GPT", guid: str = "abc") -> dict:
    return {
        "model": "Test Disk",
        "serial": "SER",
        "size_bytes": size_gib * GIB,
        "partition_style": style,
        "gpt_disk_guid": guid,
        "logical_sector_size": 512,
        "partitions": partitions,
    }


def test_empty_disk_uses_whole_disk() -> None:
    probe = FakeDiskProbe(disk_payload(1000, [], style="RAW", guid=""))
    snap = collect_target_disk_snapshot(3, probe=probe)
    assert snap.mode == "whole_disk"
    assert snap.is_empty is True
    assert snap.disk_number == 3
    # Whole-disk free space is essentially the full disk minus alignment/GPT tail.
    assert snap.install_free_space_range.size_bytes > 990 * GIB
    assert snap.existing_esp is None


def test_data_disk_uses_largest_free_gap() -> None:
    # 1000 GB disk: 200 GB partition at the front, ~800 GB free after it.
    partitions = [part(1, 0.001, 200, guid="p1")]
    probe = FakeDiskProbe(disk_payload(1000, partitions))
    snap = collect_target_disk_snapshot(1, probe=probe)
    assert snap.mode == "free_space"
    assert snap.is_empty is False
    assert 790 * GIB < snap.install_free_space_range.size_bytes < 800 * GIB
    # The free gap must start after the existing partition.
    assert snap.install_free_space_range.start_sector > int(200 * GIB / 512)


def test_largest_gap_between_partitions_is_selected() -> None:
    # 100 GB at front, then a 300 GB hole, then 50 GB near the end.
    partitions = [
        part(1, 0.001, 100, guid="p1"),
        part(2, 420, 50, guid="p2"),
    ]
    probe = FakeDiskProbe(disk_payload(500, partitions))
    snap = collect_target_disk_snapshot(1, probe=probe)
    # The 300+ GB middle hole is the largest and must be chosen.
    assert snap.install_free_space_range.size_bytes > 300 * GIB
    start_gib = snap.install_free_space_range.start_sector * 512 / GIB
    assert 99 < start_gib < 121


def test_existing_esp_detected_and_mode_override() -> None:
    partitions = [
        part(1, 0.001, 1, guid="esp", gpt_type=EFI_TYPE),
        part(2, 1, 400, guid="data"),
    ]
    probe = FakeDiskProbe(disk_payload(1000, partitions))
    snap = collect_target_disk_snapshot(2, mode="free_space", probe=probe)
    assert snap.existing_esp is not None
    assert snap.existing_esp.partition_guid == "esp"
    assert len(snap.partitions) == 2


def test_bad_mode_and_zero_size_raise() -> None:
    probe = FakeDiskProbe(disk_payload(100, []))
    with pytest.raises(DiskProbeError):
        collect_target_disk_snapshot(0, mode="nonsense", probe=probe)
    zero = FakeDiskProbe(disk_payload(0, []))
    with pytest.raises(DiskProbeError):
        collect_target_disk_snapshot(0, probe=zero)
