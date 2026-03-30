"""Machine identity matching between Linux live runtime and Windows plan contract."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import re
import subprocess
from typing import Any, Iterable, Protocol

from ...shared import PlanContract, validate_plan_contract


GUID_CLEAN_PATTERN = re.compile(r"[^0-9a-f]")
SERIAL_CLEAN_PATTERN = re.compile(r"[^0-9a-z]")


class MachineIdentityError(RuntimeError):
    """Raised when machine identity cannot be matched safely."""


class BlockDeviceProbe(Protocol):
    """Probe protocol for block-device introspection in the Linux live environment."""

    def collect_block_devices(self) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class LivePartitionSnapshot:
    path: str
    partuuid: str
    uuid: str
    filesystem: str
    start_sector: int
    end_sector: int
    size_bytes: int


@dataclass(frozen=True, slots=True)
class LiveDiskSnapshot:
    path: str
    serial: str
    model: str
    size_bytes: int
    logical_sector_size: int
    partitions: tuple[LivePartitionSnapshot, ...]


@dataclass(frozen=True, slots=True)
class IdentityMatchResult:
    disk: LiveDiskSnapshot
    efi_partition: LivePartitionSnapshot
    windows_partition: LivePartitionSnapshot
    validated_free_space_start_sector: int
    validated_free_space_end_sector: int
    validated_free_space_size_bytes: int

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["disk"]["partitions"] = [asdict(partition) for partition in self.disk.partitions]
        return payload


class LsblkProbe:
    """Default block-device probe backed by lsblk JSON output."""

    def collect_block_devices(self) -> dict[str, Any]:
        completed = subprocess.run(
            [
                "lsblk",
                "-b",
                "-J",
                "-o",
                "NAME,PATH,TYPE,SIZE,MODEL,SERIAL,PARTUUID,UUID,FSTYPE,START,LOG-SEC",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            message = completed.stderr.strip() or completed.stdout.strip() or "lsblk command failed"
            raise MachineIdentityError(message)
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise MachineIdentityError(f"Invalid lsblk JSON payload: {exc}") from exc
        if not isinstance(payload, dict):
            raise MachineIdentityError("lsblk payload must be an object.")
        return payload


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (ValueError, TypeError):
        return default


def _value(record: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in record and record[key] not in (None, ""):
            return record[key]
    return ""


def _normalize_guid(value: str) -> str:
    lowered = value.strip().strip("{}").lower()
    return GUID_CLEAN_PATTERN.sub("", lowered)


def _normalize_serial(value: str) -> str:
    lowered = value.strip().lower()
    return SERIAL_CLEAN_PATTERN.sub("", lowered)


def _normalize_model(value: str) -> str:
    return " ".join(value.strip().lower().split())


def _iter_partitions(node: dict[str, Any]) -> Iterable[dict[str, Any]]:
    for child in node.get("children", []) or []:
        child_type = str(_value(child, "type")).strip().lower()
        if child_type == "part":
            yield child
        yield from _iter_partitions(child)


def _partition_snapshot(record: dict[str, Any], *, logical_sector_size: int) -> LivePartitionSnapshot:
    path = str(_value(record, "path", "name")).strip()
    size_bytes = _as_int(_value(record, "size"), default=0)
    if size_bytes <= 0:
        raise MachineIdentityError(f"Partition reported invalid size for {path or record!r}")
    start_sector = _as_int(_value(record, "start"), default=0)
    sectors = max(1, (size_bytes + logical_sector_size - 1) // logical_sector_size)
    end_sector = start_sector + sectors - 1
    return LivePartitionSnapshot(
        path=path,
        partuuid=str(_value(record, "partuuid")).strip(),
        uuid=str(_value(record, "uuid")).strip(),
        filesystem=str(_value(record, "fstype")).strip(),
        start_sector=start_sector,
        end_sector=end_sector,
        size_bytes=size_bytes,
    )


def _disk_snapshot(record: dict[str, Any]) -> LiveDiskSnapshot:
    logical_sector_size = _as_int(_value(record, "log-sec", "log_sec"), default=512)
    if logical_sector_size <= 0:
        logical_sector_size = 512
    partitions = tuple(_partition_snapshot(child, logical_sector_size=logical_sector_size) for child in _iter_partitions(record))
    if not partitions:
        raise MachineIdentityError("Candidate disk has no readable partition records.")
    return LiveDiskSnapshot(
        path=str(_value(record, "path", "name")).strip(),
        serial=str(_value(record, "serial")).strip(),
        model=str(_value(record, "model")).strip(),
        size_bytes=_as_int(_value(record, "size"), default=0),
        logical_sector_size=logical_sector_size,
        partitions=partitions,
    )


def _match_disk_identity(plan: PlanContract, disk: LiveDiskSnapshot) -> bool:
    expected_serial = _normalize_serial(plan.disk_identity.disk_serial)
    expected_model = _normalize_model(plan.disk_identity.disk_model)
    actual_serial = _normalize_serial(disk.serial)
    actual_model = _normalize_model(disk.model)

    if plan.disk_identity.disk_size_bytes != disk.size_bytes:
        return False
    if expected_serial and expected_serial != actual_serial:
        return False
    if expected_model and expected_model not in actual_model and actual_model not in expected_model:
        return False
    return True


def _partition_match_tokens(partition_guid: str, partuuid: str) -> set[str]:
    tokens = {
        _normalize_guid(partition_guid),
        _normalize_guid(partuuid),
    }
    return {token for token in tokens if token}


def _find_partition_match(
    partitions: tuple[LivePartitionSnapshot, ...],
    *,
    expected_partition_guid: str,
    expected_partuuid: str,
    label: str,
) -> LivePartitionSnapshot:
    expected_tokens = _partition_match_tokens(expected_partition_guid, expected_partuuid)
    if not expected_tokens:
        raise MachineIdentityError(f"{label} identity in plan has no GUID/PARTUUID match tokens.")

    matches = []
    for partition in partitions:
        live_tokens = _partition_match_tokens(partition.partuuid, partition.uuid)
        if expected_tokens.intersection(live_tokens):
            matches.append(partition)

    if not matches:
        raise MachineIdentityError(f"{label} partition from plan was not found on live disk.")
    if len(matches) > 1:
        raise MachineIdentityError(f"{label} partition match is ambiguous; multiple candidates were found.")
    return matches[0]


def _compute_free_space_gaps(disk: LiveDiskSnapshot) -> tuple[tuple[int, int, int], ...]:
    total_sectors = max(1, disk.size_bytes // disk.logical_sector_size)
    max_sector = total_sectors - 1
    occupied = sorted(
        (
            max(0, partition.start_sector),
            min(max_sector, partition.end_sector),
        )
        for partition in disk.partitions
    )
    gaps: list[tuple[int, int, int]] = []
    cursor = 0
    for start, end in occupied:
        if start > cursor:
            size = (start - cursor) * disk.logical_sector_size
            gaps.append((cursor, start - 1, size))
        cursor = max(cursor, end + 1)
    if cursor <= max_sector:
        size = (max_sector - cursor + 1) * disk.logical_sector_size
        gaps.append((cursor, max_sector, size))
    return tuple(gaps)


def _validate_prepared_free_space(plan: PlanContract, disk: LiveDiskSnapshot) -> tuple[int, int, int]:
    expected_start = plan.prepared_free_space_range.start_sector
    expected_end = plan.prepared_free_space_range.end_sector
    expected_size = plan.prepared_free_space_range.size_bytes
    expected = (expected_start, expected_end, expected_size)

    for gap in _compute_free_space_gaps(disk):
        if gap == expected:
            return gap
    raise MachineIdentityError(
        "Prepared free-space range from plan does not match current disk gaps "
        f"(expected start={expected_start}, end={expected_end}, size={expected_size})."
    )


def match_machine_identity(
    plan_payload: PlanContract | dict[str, Any],
    *,
    probe: BlockDeviceProbe | None = None,
) -> IdentityMatchResult:
    """Validate live machine identity against the Windows-produced plan contract."""
    plan = plan_payload if isinstance(plan_payload, PlanContract) else validate_plan_contract(plan_payload)
    active_probe = probe or LsblkProbe()
    payload = active_probe.collect_block_devices()

    devices = payload.get("blockdevices", [])
    if not isinstance(devices, list) or not devices:
        raise MachineIdentityError("No block devices were returned by the probe.")

    disk_candidates: list[LiveDiskSnapshot] = []
    for record in devices:
        device_type = str(_value(record, "type")).strip().lower()
        if device_type != "disk":
            continue
        snapshot = _disk_snapshot(record)
        if _match_disk_identity(plan, snapshot):
            disk_candidates.append(snapshot)

    if not disk_candidates:
        raise MachineIdentityError("No live disk matches the planned serial/model/size identity.")
    if len(disk_candidates) > 1:
        raise MachineIdentityError("Disk identity match is ambiguous; multiple live disks match the plan identity.")

    disk = disk_candidates[0]
    efi_partition = _find_partition_match(
        disk.partitions,
        expected_partition_guid=plan.efi_identity.partition_guid,
        expected_partuuid=plan.efi_identity.partuuid,
        label="EFI",
    )
    windows_partition = _find_partition_match(
        disk.partitions,
        expected_partition_guid=plan.windows_partition_identity.partition_guid,
        expected_partuuid=plan.windows_partition_identity.partuuid,
        label="Windows",
    )
    free_space_start, free_space_end, free_space_size = _validate_prepared_free_space(plan, disk)

    return IdentityMatchResult(
        disk=disk,
        efi_partition=efi_partition,
        windows_partition=windows_partition,
        validated_free_space_start_sector=free_space_start,
        validated_free_space_end_sector=free_space_end,
        validated_free_space_size_bytes=free_space_size,
    )
