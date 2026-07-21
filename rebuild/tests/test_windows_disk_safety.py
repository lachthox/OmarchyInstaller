from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from rebuild.installer.platforms.windows.disk_probe import (
    DiskProbeError,
    collect_disk_probe_snapshot,
)
from rebuild.installer.platforms.windows.partition_prep import (
    PartitionPrepError,
    PartitionPrepPolicy,
    prepare_unallocated_space,
)


MIB = 1024**2
GIB = 1024**3
ESP_TYPE = "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"


class SequenceProbe:
    def __init__(self, *payloads: dict[str, object]) -> None:
        self.payloads = list(payloads)

    def collect_layout(self, _system_drive: str) -> dict[str, object]:
        if len(self.payloads) > 1:
            return self.payloads.pop(0)
        return deepcopy(self.payloads[0])


class RecordingResizer:
    def __init__(self, minimum: int, maximum: int) -> None:
        self.minimum = minimum
        self.maximum = maximum
        self.calls: list[tuple[str, int]] = []

    def get_supported_size_range(self, _drive: str) -> tuple[int, int]:
        return self.minimum, self.maximum

    def resize_partition(self, drive: str, new_size_bytes: int) -> None:
        self.calls.append((drive, new_size_bytes))


def partition(number: int, offset: int, size: int, *, guid: str, gpt_type: str = "") -> dict[str, object]:
    return {
        "partition_number": number,
        "guid": guid,
        "gpt_type": gpt_type,
        "drive_letter": "C" if number == 2 else "",
        "offset_bytes": offset,
        "size_bytes": size,
        "filesystem": "NTFS" if number == 2 else "FAT32",
        "filesystem_uuid": f"fs-{number}",
    }


def layout(
    *,
    sector_size: int = 512,
    gap_after_windows: int = 0,
    serial: str = "serial",
    disk_guid: str = "disk-guid",
    extra_nonadjacent_gap: int = 0,
) -> dict[str, object]:
    esp_offset = MIB
    esp_size = 512 * MIB
    windows_offset = esp_offset + esp_size + extra_nonadjacent_gap
    windows_size = 100 * GIB
    recovery_offset = windows_offset + windows_size + gap_after_windows
    recovery_size = GIB
    disk_size = recovery_offset + recovery_size + MIB
    return {
        "disk_number": 0,
        "model": "Fixture disk",
        "serial": serial,
        "size_bytes": disk_size,
        "partition_style": "GPT",
        "gpt_disk_guid": disk_guid,
        "logical_sector_size": sector_size,
        "partitions": [
            partition(1, esp_offset, esp_size, guid="esp-guid", gpt_type=ESP_TYPE),
            partition(2, windows_offset, windows_size, guid="windows-guid"),
            partition(3, recovery_offset, recovery_size, guid="recovery-guid"),
        ],
    }


def verified_manifest(tmp_path: Path, *, disk_guid: str = "disk-guid") -> Path:
    path = tmp_path / "backup-manifest.json"
    path.write_text(
        json.dumps(
            {
                "verification": {"status": "verified"},
                "source": {
                    "disk_identity": {"gpt_disk_guid": disk_guid},
                    "efi_identity": {"partition_guid": "esp-guid"},
                    "windows_partition_identity": {"partition_guid": "windows-guid"},
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def test_no_existing_adjacent_gap_is_zero_length() -> None:
    snapshot = collect_disk_probe_snapshot(SequenceProbe(layout()))

    assert snapshot.prepared_free_space_range.size_bytes == 0
    assert snapshot.prepared_free_space_range.end_sector + 1 == snapshot.prepared_free_space_range.start_sector


def test_only_gap_directly_after_windows_is_counted() -> None:
    snapshot = collect_disk_probe_snapshot(
        SequenceProbe(layout(gap_after_windows=8 * GIB, extra_nonadjacent_gap=30 * GIB))
    )

    assert snapshot.prepared_free_space_range.size_bytes == 8 * GIB


@pytest.mark.parametrize("sector_size", [512, 4096])
def test_sector_sizes_preserve_exact_geometry(sector_size: int) -> None:
    snapshot = collect_disk_probe_snapshot(
        SequenceProbe(layout(sector_size=sector_size, gap_after_windows=GIB))
    )

    assert snapshot.disk_identity.logical_sector_size == sector_size
    assert snapshot.prepared_free_space_range.size_bytes == GIB


def test_missing_serial_does_not_fall_back_to_disk_number() -> None:
    snapshot = collect_disk_probe_snapshot(SequenceProbe(layout(serial="")))

    assert snapshot.disk_identity.disk_serial == ""
    assert snapshot.disk_identity.gpt_disk_guid == "disk-guid"


def test_fat32_partition_without_esp_type_is_never_selected() -> None:
    payload = layout()
    partitions = payload["partitions"]
    assert isinstance(partitions, list)
    partitions.insert(0, partition(4, 0, MIB, guid="fat-data", gpt_type="data-type"))

    snapshot = collect_disk_probe_snapshot(SequenceProbe(payload))

    assert snapshot.efi_identity.partition_guid == "esp-guid"


def test_missing_real_esp_blocks_even_when_fat32_exists() -> None:
    payload = layout()
    partitions = payload["partitions"]
    assert isinstance(partitions, list)
    partitions[0]["gpt_type"] = "data-type"  # type: ignore[index]

    with pytest.raises(DiskProbeError, match="EFI system partition"):
        collect_disk_probe_snapshot(SequenceProbe(payload))


def test_resize_uses_exact_adjacent_missing_space_plus_small_margin(tmp_path: Path) -> None:
    before = layout(gap_after_windows=10 * GIB)
    after = deepcopy(before)
    after_partitions = after["partitions"]
    assert isinstance(after_partitions, list)
    after_partitions[1]["size_bytes"] = 70 * GIB - 16 * MIB  # type: ignore[index]
    windows_size = 100 * GIB
    resizer = RecordingResizer(minimum=40 * GIB, maximum=windows_size)
    policy = PartitionPrepPolicy(target_free_space_bytes=40 * GIB)

    result = prepare_unallocated_space(
        policy,
        disk_probe=SequenceProbe(before, after),  # type: ignore[arg-type]
        resizer=resizer,
        verified_backup_manifest=verified_manifest(tmp_path),
        journal_path=tmp_path / "resize.json",
    )

    assert result.requested_shrink_bytes == 30 * GIB + 16 * MIB
    assert resizer.calls == [("C", windows_size - result.requested_shrink_bytes)]
    assert json.loads((tmp_path / "resize.json").read_text(encoding="utf-8"))["status"] == "validated"


def test_insufficient_supported_shrink_blocks_before_resize(tmp_path: Path) -> None:
    before = layout()
    resizer = RecordingResizer(minimum=90 * GIB, maximum=100 * GIB)

    with pytest.raises(PartitionPrepError, match="exceeds supported capacity"):
        prepare_unallocated_space(
            PartitionPrepPolicy(target_free_space_bytes=40 * GIB),
            disk_probe=SequenceProbe(before),  # type: ignore[arg-type]
            resizer=resizer,
            verified_backup_manifest=verified_manifest(tmp_path),
            journal_path=tmp_path / "resize.json",
        )
    assert not resizer.calls


def test_backup_for_different_disk_blocks_before_resize(tmp_path: Path) -> None:
    resizer = RecordingResizer(minimum=40 * GIB, maximum=100 * GIB)

    with pytest.raises(PartitionPrepError, match="does not match"):
        prepare_unallocated_space(
            PartitionPrepPolicy(target_free_space_bytes=40 * GIB),
            disk_probe=SequenceProbe(layout()),  # type: ignore[arg-type]
            resizer=resizer,
            verified_backup_manifest=verified_manifest(tmp_path, disk_guid="other-disk"),
            journal_path=tmp_path / "resize.json",
        )
    assert not resizer.calls


def test_changed_disk_identity_after_resize_is_distinct_applied_failure(tmp_path: Path) -> None:
    before = layout()
    after = deepcopy(before)
    after["gpt_disk_guid"] = "different-disk"
    after_partitions = after["partitions"]
    assert isinstance(after_partitions, list)
    after_partitions[1]["size_bytes"] = 60 * GIB - 16 * MIB  # type: ignore[index]
    resizer = RecordingResizer(minimum=40 * GIB, maximum=100 * GIB)

    with pytest.raises(PartitionPrepError, match="Resize was applied") as error:
        prepare_unallocated_space(
            PartitionPrepPolicy(target_free_space_bytes=40 * GIB),
            disk_probe=SequenceProbe(before, after),  # type: ignore[arg-type]
            resizer=resizer,
            verified_backup_manifest=verified_manifest(tmp_path),
            journal_path=tmp_path / "resize.json",
        )
    assert error.value.resize_applied is True
    assert json.loads((tmp_path / "resize.json").read_text(encoding="utf-8"))["status"] == (
        "resize-applied-validation-failed"
    )
