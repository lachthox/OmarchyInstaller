"""Windows partition shrink policy and plan metadata helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
import subprocess
from typing import Any, Protocol

from .disk_probe import (
    DiskProbeSnapshot,
    PowerShellDiskLayoutProbe,
    collect_disk_probe_snapshot,
    normalize_drive_letter,
)
from ...shared import PlanContract, validate_plan_contract
from ...shared.atomic_io import atomic_write_json


DEFAULT_TARGET_FREE_SPACE_BYTES = 120 * 1024 * 1024 * 1024
DEFAULT_SAFETY_MARGIN_BYTES = 16 * 1024 * 1024


class PartitionPrepError(RuntimeError):
    """Raised when partition preparation cannot safely satisfy policy."""

    def __init__(self, message: str, *, resize_applied: bool = False) -> None:
        super().__init__(message)
        self.resize_applied = resize_applied


class PartitionResizer(Protocol):
    """Protocol for real or stub partition resize backends."""

    def get_supported_size_range(self, system_drive: str) -> tuple[int, int]: ...
    def resize_partition(self, system_drive: str, new_size_bytes: int) -> None: ...


class PowerShellPartitionResizer:
    """Resize backend backed by PowerShell storage cmdlets."""

    def _run_ps(self, script: str) -> str:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", script],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            message = completed.stderr.strip() or completed.stdout.strip() or "PowerShell command failed."
            raise PartitionPrepError(message)
        return completed.stdout.strip()

    def get_supported_size_range(self, system_drive: str) -> tuple[int, int]:
        drive = normalize_drive_letter(system_drive)
        script = rf"""
$size = Get-PartitionSupportedSize -DriveLetter '{drive}' -ErrorAction Stop
[PSCustomObject]@{{
  size_min = [int64]$size.SizeMin
  size_max = [int64]$size.SizeMax
}} | ConvertTo-Json -Compress
"""
        output = self._run_ps(script)
        try:
            payload = json.loads(output)
        except json.JSONDecodeError as exc:
            raise PartitionPrepError(f"Failed to parse supported partition size payload: {exc}") from exc
        minimum = int(payload.get("size_min", 0))
        maximum = int(payload.get("size_max", 0))
        if minimum <= 0 or maximum <= 0 or minimum > maximum:
            raise PartitionPrepError(f"Invalid supported partition size range: min={minimum} max={maximum}")
        return minimum, maximum

    def resize_partition(self, system_drive: str, new_size_bytes: int) -> None:
        drive = normalize_drive_letter(system_drive)
        if new_size_bytes <= 0:
            raise ValueError("new_size_bytes must be positive.")
        script = rf"Resize-Partition -DriveLetter '{drive}' -Size {int(new_size_bytes)} -ErrorAction Stop | Out-Null"
        self._run_ps(script)


@dataclass(frozen=True, slots=True)
class PartitionPrepPolicy:
    target_free_space_bytes: int = DEFAULT_TARGET_FREE_SPACE_BYTES
    safety_margin_bytes: int = DEFAULT_SAFETY_MARGIN_BYTES
    dry_run: bool = False

    def __post_init__(self) -> None:
        if self.target_free_space_bytes <= 0:
            raise ValueError("target_free_space_bytes must be greater than zero.")
        if self.safety_margin_bytes < 0 or self.safety_margin_bytes > 1024**3:
            raise ValueError("safety_margin_bytes must be between zero and 1 GiB.")


@dataclass(frozen=True, slots=True)
class PartitionPrepResult:
    before_snapshot: DiskProbeSnapshot
    after_snapshot: DiskProbeSnapshot
    target_free_space_bytes: int
    current_free_space_bytes: int
    final_free_space_bytes: int
    requested_shrink_bytes: int
    applied_shrink_bytes: int
    new_windows_partition_size_bytes: int
    would_resize: bool
    resized: bool
    policy_unallocated_only: bool

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["before_snapshot"] = self.before_snapshot.to_plan_fragment()
        payload["after_snapshot"] = self.after_snapshot.to_plan_fragment()
        return payload


def _calculate_shrink_bytes(current_free_space_bytes: int, policy: PartitionPrepPolicy) -> int:
    if current_free_space_bytes >= policy.target_free_space_bytes:
        return 0
    missing = policy.target_free_space_bytes - current_free_space_bytes
    if missing <= 0:
        return 0
    return missing + policy.safety_margin_bytes


def _require_verified_backup(path: str | Path | None, snapshot: DiskProbeSnapshot) -> Path:
    if path is None:
        raise PartitionPrepError("Apply mode requires a verified backup manifest.")
    manifest_path = Path(path)
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PartitionPrepError(f"Verified backup manifest is unreadable: {exc}") from exc
    verification = payload.get("verification", {})
    if not isinstance(verification, dict) or verification.get("status") != "verified":
        raise PartitionPrepError("Backup manifest does not contain verified postconditions.")
    source = payload.get("source", {})
    if not isinstance(source, dict):
        raise PartitionPrepError("Backup manifest is missing source identities.")
    expected = {
        "disk_identity": snapshot.disk_identity.gpt_disk_guid,
        "efi_identity": snapshot.efi_identity.partition_guid,
        "windows_partition_identity": snapshot.windows_partition_identity.partition_guid,
    }
    for block_name, expected_identity in expected.items():
        block = source.get(block_name, {})
        if not isinstance(block, dict):
            raise PartitionPrepError(f"Backup manifest is missing {block_name}.")
        key = "gpt_disk_guid" if block_name == "disk_identity" else "partition_guid"
        if str(block.get(key, "")).casefold() != expected_identity.casefold():
            raise PartitionPrepError(f"Backup manifest {block_name} does not match the current target.")
    return manifest_path


def _verify_post_resize_identity(before: DiskProbeSnapshot, after: DiskProbeSnapshot) -> None:
    if before.disk_identity != after.disk_identity:
        raise PartitionPrepError("Disk identity changed unexpectedly during shrink operation.")
    if before.efi_identity.partition_guid != after.efi_identity.partition_guid:
        raise PartitionPrepError("EFI partition identity changed unexpectedly during shrink operation.")
    if before.windows_partition_identity.partition_guid != after.windows_partition_identity.partition_guid:
        raise PartitionPrepError("Windows partition identity changed unexpectedly during shrink operation.")


def prepare_unallocated_space(
    policy: PartitionPrepPolicy | None = None,
    *,
    system_drive: str = "C",
    disk_probe: PowerShellDiskLayoutProbe | None = None,
    resizer: PartitionResizer | None = None,
    verified_backup_manifest: str | Path | None = None,
    journal_path: str | Path | None = None,
) -> PartitionPrepResult:
    """Prepare unallocated space by shrinking Windows partition only."""
    active_policy = policy or PartitionPrepPolicy()
    drive = normalize_drive_letter(system_drive)
    active_probe = disk_probe or PowerShellDiskLayoutProbe()
    active_resizer = resizer or PowerShellPartitionResizer()

    before = collect_disk_probe_snapshot(active_probe, system_drive=drive)
    current_free_space_bytes = before.prepared_free_space_range.size_bytes
    requested_shrink_bytes = _calculate_shrink_bytes(current_free_space_bytes, active_policy)
    windows_size_bytes = before.windows_partition_identity.size_bytes

    if requested_shrink_bytes == 0:
        return PartitionPrepResult(
            before_snapshot=before,
            after_snapshot=before,
            target_free_space_bytes=active_policy.target_free_space_bytes,
            current_free_space_bytes=current_free_space_bytes,
            final_free_space_bytes=current_free_space_bytes,
            requested_shrink_bytes=0,
            applied_shrink_bytes=0,
            new_windows_partition_size_bytes=windows_size_bytes,
            would_resize=False,
            resized=False,
            policy_unallocated_only=True,
        )

    minimum_size, maximum_size = active_resizer.get_supported_size_range(drive)
    max_allowed_shrink = windows_size_bytes - minimum_size
    if max_allowed_shrink <= 0:
        raise PartitionPrepError("Windows reports no available shrink capacity.")
    if requested_shrink_bytes > max_allowed_shrink:
        raise PartitionPrepError(
            "Required shrink exceeds supported capacity "
            f"(required {requested_shrink_bytes} bytes, max {max_allowed_shrink} bytes)."
        )

    new_partition_size_bytes = windows_size_bytes - requested_shrink_bytes
    if new_partition_size_bytes < minimum_size or new_partition_size_bytes > maximum_size:
        raise PartitionPrepError(
            "Computed partition size is outside supported range "
            f"(size {new_partition_size_bytes}, supported {minimum_size}-{maximum_size})."
        )

    if active_policy.dry_run:
        return PartitionPrepResult(
            before_snapshot=before,
            after_snapshot=before,
            target_free_space_bytes=active_policy.target_free_space_bytes,
            current_free_space_bytes=current_free_space_bytes,
            final_free_space_bytes=current_free_space_bytes,
            requested_shrink_bytes=requested_shrink_bytes,
            applied_shrink_bytes=0,
            new_windows_partition_size_bytes=new_partition_size_bytes,
            would_resize=True,
            resized=False,
            policy_unallocated_only=True,
        )

    backup_manifest = _require_verified_backup(verified_backup_manifest, before)
    if journal_path is None:
        raise PartitionPrepError("Apply mode requires a durable resize journal path.")
    journal = Path(journal_path)
    before_payload = {
        "schema_version": "1.0.0",
        "status": "planned",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "backup_manifest": str(backup_manifest),
        "system_drive": drive,
        "disk_identity": before.disk_identity.model_dump(mode="json"),
        "windows_partition_before": before.windows_partition_identity.model_dump(mode="json"),
        "adjacent_free_before": before.prepared_free_space_range.model_dump(mode="json"),
        "requested_shrink_bytes": requested_shrink_bytes,
        "intended_windows_size_bytes": new_partition_size_bytes,
        "rollback_supported": False,
    }
    atomic_write_json(journal, before_payload)

    active_resizer.resize_partition(drive, new_partition_size_bytes)
    try:
        after = collect_disk_probe_snapshot(active_probe, system_drive=drive)
        _verify_post_resize_identity(before, after)

        final_free_space_bytes = after.prepared_free_space_range.size_bytes
        if final_free_space_bytes < active_policy.target_free_space_bytes:
            raise PartitionPrepError(
                "Post-resize free space does not meet target "
                f"(target {active_policy.target_free_space_bytes}, got {final_free_space_bytes})."
            )
    except Exception as exc:
        failure_payload = dict(before_payload)
        failure_payload.update(
            {
                "status": "resize-applied-validation-failed",
                "failed_at_utc": datetime.now(UTC).isoformat(),
                "error": str(exc),
            }
        )
        atomic_write_json(journal, failure_payload)
        raise PartitionPrepError(
            f"Resize was applied but post-resize validation failed: {exc}",
            resize_applied=True,
        ) from exc

    completed_payload = dict(before_payload)
    completed_payload.update(
        {
            "status": "validated",
            "validated_at_utc": datetime.now(UTC).isoformat(),
            "disk_identity_after": after.disk_identity.model_dump(mode="json"),
            "windows_partition_after": after.windows_partition_identity.model_dump(mode="json"),
            "adjacent_free_after": after.prepared_free_space_range.model_dump(mode="json"),
        }
    )
    atomic_write_json(journal, completed_payload)

    return PartitionPrepResult(
        before_snapshot=before,
        after_snapshot=after,
        target_free_space_bytes=active_policy.target_free_space_bytes,
        current_free_space_bytes=current_free_space_bytes,
        final_free_space_bytes=final_free_space_bytes,
        requested_shrink_bytes=requested_shrink_bytes,
        applied_shrink_bytes=windows_size_bytes - after.windows_partition_identity.size_bytes,
        new_windows_partition_size_bytes=after.windows_partition_identity.size_bytes,
        would_resize=True,
        resized=True,
        policy_unallocated_only=True,
    )


def apply_partition_metadata_to_plan(
    plan_payload: PlanContract | dict[str, Any],
    snapshot: DiskProbeSnapshot,
) -> PlanContract:
    """Write exact disk/partition/free-space metadata into a validated plan contract."""
    payload = plan_payload.model_dump() if isinstance(plan_payload, PlanContract) else dict(plan_payload)
    payload["disk_identity"] = snapshot.disk_identity.model_dump()
    payload["efi_identity"] = snapshot.efi_identity.model_dump()
    payload["windows_partition_identity"] = snapshot.windows_partition_identity.model_dump()
    payload["prepared_free_space_range"] = snapshot.prepared_free_space_range.model_dump()
    return validate_plan_contract(payload)
