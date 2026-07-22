from __future__ import annotations

import pytest

from rebuild.installer.platforms.windows.disk_probe import collect_target_disk_snapshot
from rebuild.installer.platforms.windows.target_disk_prep import (
    TargetDiskPrepError,
    prepare_target_disk,
)


GIB = 1024**3
EFI_TYPE = "{c12a7328-f81f-11d2-ba4b-00a0c93ec93b}"


class FakeDiskProbe:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def collect_disk_layout(self, disk_number: int) -> dict:
        return dict(self._payload, disk_number=disk_number)


def part(number, offset_gib, size_gib, *, guid, gpt_type=""):
    return {
        "partition_number": number,
        "guid": guid,
        "gpt_type": gpt_type,
        "offset_bytes": int(offset_gib * GIB),
        "size_bytes": int(size_gib * GIB),
        "filesystem": "NTFS",
        "filesystem_uuid": "",
    }


def payload(size_gib, partitions, *, style="GPT", guid="abc"):
    return {
        "model": "T",
        "serial": "S",
        "size_bytes": size_gib * GIB,
        "partition_style": style,
        "gpt_disk_guid": guid,
        "logical_sector_size": 512,
        "partitions": partitions,
    }


def snap(size_gib, partitions, mode="auto", **kw):
    probe = FakeDiskProbe(payload(size_gib, partitions, **kw))
    return collect_target_disk_snapshot(1, mode=mode, probe=probe)


def test_whole_empty_disk_uses_everything_no_erase() -> None:
    result = prepare_target_disk(
        snap(1000, [], style="RAW", guid=""),
        requested_linux_bytes=120 * GIB,
        minimum_linux_bytes=40 * GIB,
    )
    assert result.mode == "whole_disk"
    assert result.would_erase_existing_data is False
    assert result.fits is True
    # Uses the whole usable region, not just the requested 120 GB.
    assert result.linux_bytes > 990 * GIB


def test_whole_disk_with_data_flags_erase() -> None:
    result = prepare_target_disk(
        snap(1000, [part(1, 0.001, 400, guid="p1")], mode="whole_disk"),
        requested_linux_bytes=120 * GIB,
        minimum_linux_bytes=40 * GIB,
    )
    assert result.mode == "whole_disk"
    assert result.would_erase_existing_data is True


def test_free_space_carves_requested_size() -> None:
    # 1 TB disk, 200 GB used at front, ~800 GB free.
    result = prepare_target_disk(
        snap(1000, [part(1, 0.001, 200, guid="p1")]),
        requested_linux_bytes=150 * GIB,
        minimum_linux_bytes=40 * GIB,
    )
    assert result.mode == "free_space"
    assert result.would_erase_existing_data is False
    # Linux takes ~150 GB out of the free gap, leaving the rest.
    assert 149 * GIB <= result.linux_bytes <= 151 * GIB
    assert result.linux_bytes < result.available_free_bytes


def test_free_space_request_capped_to_available() -> None:
    result = prepare_target_disk(
        snap(500, [part(1, 0.001, 400, guid="p1")]),  # ~100 GB free
        requested_linux_bytes=300 * GIB,  # more than available
        minimum_linux_bytes=40 * GIB,
    )
    assert result.linux_bytes <= result.available_free_bytes
    assert result.fits is True


def test_does_not_fit_when_free_below_minimum() -> None:
    result = prepare_target_disk(
        snap(100, [part(1, 0.001, 80, guid="p1")]),  # ~20 GB free
        requested_linux_bytes=40 * GIB,
        minimum_linux_bytes=40 * GIB,
    )
    assert result.fits is False


def test_invalid_minimum_raises() -> None:
    with pytest.raises(TargetDiskPrepError):
        prepare_target_disk(snap(100, []), requested_linux_bytes=40 * GIB, minimum_linux_bytes=0)
