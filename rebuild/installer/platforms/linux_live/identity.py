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
    gpt_disk_guid: str
    serial: str
    model: str
    size_bytes: int
    logical_sector_size: int
    first_usable_sector: int
    last_usable_sector: int
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

    @staticmethod
    def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                command,
                capture_output=True,
                text=True,
                check=False,
                timeout=6,
            )
        except subprocess.TimeoutExpired as exc:
            raise MachineIdentityError(
                f"{command[0]} timed out after 6 seconds while checking the target disk."
            ) from exc

    def collect_block_devices(self) -> dict[str, Any]:
        completed = self._run(
            [
                "lsblk",
                "-b",
                "-J",
                "-o",
                "NAME,PATH,TYPE,SIZE,MODEL,SERIAL,PTUUID,PARTUUID,UUID,FSTYPE,START,LOG-SEC",
            ]
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
        for record in payload.get("blockdevices", []) or []:
            if not isinstance(record, dict) or str(record.get("type", "")).lower() != "disk":
                continue
            path = str(record.get("path") or record.get("name") or "")
            completed = self._run(["sgdisk", "--print", path])
            if completed.returncode != 0:
                raise MachineIdentityError(
                    completed.stderr.strip() or f"sgdisk failed for {path}"
                )
            usable = re.search(
                r"First usable sector is\s+(\d+), last usable sector is\s+(\d+)",
                completed.stdout,
                flags=re.IGNORECASE,
            )
            guid = re.search(
                r"Disk identifier \(GUID\):\s*([0-9A-Fa-f-]+)", completed.stdout
            )
            if not usable or not guid:
                raise MachineIdentityError(f"sgdisk omitted authoritative GPT geometry for {path}")
            record["first_usable_sector"] = int(usable.group(1))
            record["last_usable_sector"] = int(usable.group(2))
            record["ptuuid"] = guid.group(1)
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
        gpt_disk_guid=str(_value(record, "ptuuid")).strip(),
        serial=str(_value(record, "serial")).strip(),
        model=str(_value(record, "model")).strip(),
        size_bytes=_as_int(_value(record, "size"), default=0),
        logical_sector_size=logical_sector_size,
        first_usable_sector=_as_int(_value(record, "first_usable_sector"), default=-1),
        last_usable_sector=_as_int(_value(record, "last_usable_sector"), default=-1),
        partitions=partitions,
    )


def _match_disk_identity(plan: PlanContract, disk: LiveDiskSnapshot) -> bool:
    expected_serial = _normalize_serial(plan.disk_identity.disk_serial)
    expected_model = _normalize_model(plan.disk_identity.disk_model)
    actual_serial = _normalize_serial(disk.serial)
    actual_model = _normalize_model(disk.model)

    if _normalize_guid(plan.disk_identity.gpt_disk_guid) != _normalize_guid(disk.gpt_disk_guid):
        return False
    if plan.disk_identity.disk_size_bytes != disk.size_bytes:
        return False
    if plan.disk_identity.logical_sector_size != disk.logical_sector_size:
        return False
    if expected_serial and expected_serial != actual_serial:
        return False
    if expected_model and expected_model not in actual_model and actual_model not in expected_model:
        return False
    return True


def _find_partition_match(
    partitions: tuple[LivePartitionSnapshot, ...],
    *,
    expected_partition_guid: str,
    expected_partuuid: str,
    expected_filesystem_uuid: str,
    expected_filesystem: str,
    expected_start_sector: int,
    expected_end_sector: int,
    expected_size_bytes: int,
    label: str,
) -> LivePartitionSnapshot:
    expected_guid = _normalize_guid(expected_partition_guid)
    expected_linux_partuuid = _normalize_guid(expected_partuuid)
    if not expected_guid or not expected_linux_partuuid:
        raise MachineIdentityError(f"{label} identity in plan has no GUID/PARTUUID match tokens.")
    if expected_guid != expected_linux_partuuid:
        raise MachineIdentityError(f"{label} GPT GUID and PARTUUID contract disagree.")

    matches = []
    for partition in partitions:
        if expected_linux_partuuid == _normalize_guid(partition.partuuid):
            matches.append(partition)

    if not matches:
        raise MachineIdentityError(f"{label} partition from plan was not found on live disk.")
    if len(matches) > 1:
        raise MachineIdentityError(f"{label} partition match is ambiguous; multiple candidates were found.")
    match = matches[0]
    if expected_filesystem_uuid and expected_filesystem_uuid.casefold() != match.uuid.casefold():
        raise MachineIdentityError(f"{label} filesystem UUID does not match independently.")
    if expected_filesystem and expected_filesystem.casefold() != match.filesystem.casefold():
        raise MachineIdentityError(f"{label} filesystem type does not match independently.")
    if (
        match.start_sector != expected_start_sector
        or match.end_sector != expected_end_sector
        or match.size_bytes != expected_size_bytes
    ):
        raise MachineIdentityError(f"{label} partition geometry/size does not match independently.")
    return match


def _compute_free_space_gaps(disk: LiveDiskSnapshot) -> tuple[tuple[int, int, int], ...]:
    if disk.first_usable_sector < 0 or disk.last_usable_sector < disk.first_usable_sector:
        raise MachineIdentityError("Authoritative GPT usable-sector bounds are unavailable.")
    min_sector = disk.first_usable_sector
    max_sector = disk.last_usable_sector
    occupied = sorted(
        (
            max(min_sector, partition.start_sector),
            min(max_sector, partition.end_sector),
        )
        for partition in disk.partitions
    )
    gaps: list[tuple[int, int, int]] = []
    cursor = min_sector
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
    for gap_start, gap_end, _gap_size in _compute_free_space_gaps(disk):
        if gap_start <= expected_start and gap_end >= expected_end:
            return expected_start, expected_end, expected_size
    raise MachineIdentityError(
        "Prepared free-space range from plan does not match current disk gaps "
        f"(expected start={expected_start}, end={expected_end}, size={expected_size})."
    )


def resolve_target_disk_path(
    plan_payload: PlanContract | dict[str, Any],
    *,
    probe: BlockDeviceProbe | None = None,
) -> str:
    """Resolve the live device path of the separate Linux install target disk.

    Unlike the Windows disk, the target disk may be empty (no partitions), so
    it is matched directly on the raw block-device record by GPT disk GUID
    and/or serial+size, without requiring partitions or an ESP.
    """
    plan = plan_payload if isinstance(plan_payload, PlanContract) else validate_plan_contract(plan_payload)
    target = plan.linux_install_target
    if target is None:
        raise MachineIdentityError("Plan has no separate Linux install target.")
    active_probe = probe or LsblkProbe()
    payload = active_probe.collect_block_devices()
    devices = payload.get("blockdevices", [])
    if not isinstance(devices, list) or not devices:
        raise MachineIdentityError("No block devices were returned by the probe.")

    expected_guid = _normalize_guid(target.disk_identity.gpt_disk_guid)
    expected_serial = _normalize_serial(target.disk_identity.disk_serial)
    expected_size = target.disk_identity.disk_size_bytes
    windows_path = ""
    if isinstance(plan.disk_identity.gpt_disk_guid, str):
        windows_guid = _normalize_guid(plan.disk_identity.gpt_disk_guid)
    else:
        windows_guid = ""

    matches: set[str] = set()
    for record in devices:
        if str(_value(record, "type")).strip().lower() != "disk":
            continue
        path = str(_value(record, "path", "name")).strip()
        rec_guid = _normalize_guid(str(_value(record, "ptuuid")).strip())
        rec_serial = _normalize_serial(str(_value(record, "serial")).strip())
        rec_size = _as_int(_value(record, "size"), default=0)
        if windows_guid and rec_guid and rec_guid == windows_guid:
            windows_path = path  # never select the Windows disk as the target
            continue
        guid_hit = bool(expected_guid) and bool(rec_guid) and expected_guid == rec_guid
        serial_hit = (
            bool(expected_serial)
            and bool(rec_serial)
            and expected_serial == rec_serial
            and rec_size == expected_size
        )
        if guid_hit or serial_hit:
            matches.add(path)

    matches.discard(windows_path)
    if not matches:
        raise MachineIdentityError("No live disk matches the planned Linux target disk identity.")
    if len(matches) > 1:
        raise MachineIdentityError("Linux target disk match is ambiguous; multiple live disks match.")
    return next(iter(matches))


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
        if not any(True for _ in _iter_partitions(record)):
            # An empty disk (e.g. a blank separate-disk install target) is
            # never the Windows disk we are identifying here; skip it instead
            # of failing the whole match on its missing partition records.
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
        expected_filesystem_uuid=plan.efi_identity.filesystem_uuid,
        expected_filesystem=plan.efi_identity.filesystem_type,
        expected_start_sector=plan.efi_identity.start_sector,
        expected_end_sector=plan.efi_identity.end_sector,
        expected_size_bytes=plan.efi_identity.size_bytes,
        label="EFI",
    )
    windows_partition = _find_partition_match(
        disk.partitions,
        expected_partition_guid=plan.windows_partition_identity.partition_guid,
        expected_partuuid=plan.windows_partition_identity.partuuid,
        expected_filesystem_uuid=plan.windows_partition_identity.filesystem_uuid,
        expected_filesystem=plan.windows_partition_identity.filesystem_type,
        expected_start_sector=plan.windows_partition_identity.start_sector,
        expected_end_sector=plan.windows_partition_identity.end_sector,
        expected_size_bytes=plan.windows_partition_identity.size_bytes,
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
