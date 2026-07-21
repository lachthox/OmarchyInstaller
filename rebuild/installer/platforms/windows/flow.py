"""Python migration flow for Windows prep steps."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import secrets
from typing import Any

from .backup import BackupError, BackupResult, run_windows_backup_subsystem
from .partition_prep import (
    PartitionPrepError,
    PartitionPrepPolicy,
    PartitionPrepResult,
    prepare_unallocated_space,
    apply_partition_metadata_to_plan,
)
from .handoff import VentoyError, install_ventoy_to_usb, stage_ventoy_handoff_bundle
from .disk_probe import DiskProbeSnapshot
from ...shared import validate_plan_contract

GIB = 1024**3


def _gib(value_bytes: int) -> float:
    return round(value_bytes / GIB, 1)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class FlowStepResult:
    name: str
    ok: bool
    apply_mode: bool
    summary: str
    payload: dict[str, Any] | None = None
    error: str | None = None


@dataclass(slots=True)
class WindowsMigrationFlow:
    """Runs migrated Python steps for Windows prep with safe defaults."""

    apply_changes: bool = False
    target_free_gib: int = 120
    backup_destination: str | None = None
    backup_fallback_destination: str | None = None
    _verified_backup_manifest: str | None = None
    _backup_root: str | None = None
    _prepared_snapshot: DiskProbeSnapshot | None = None

    @property
    def prepared_snapshot(self) -> DiskProbeSnapshot | None:
        return self._prepared_snapshot

    def _resolve_backup_destination(self) -> str:
        system_drive = os.environ.get("SystemDrive", "C:").rstrip("\\/").casefold()

        def resolve_and_validate(value: str) -> str:
            destination = Path(value).expanduser().resolve()
            destination_drive = PureWindowsPath(value).drive or destination.drive
            if self.apply_changes and destination_drive.rstrip("\\/").casefold() == system_drive:
                raise BackupError("Apply-mode backups must be stored off the Windows system disk.")
            return str(destination)

        if self.backup_fallback_destination:
            self.backup_fallback_destination = resolve_and_validate(
                self.backup_fallback_destination
            )
        if self.backup_destination and self.backup_destination.strip():
            return resolve_and_validate(self.backup_destination)
        if self.apply_changes:
            raise BackupError("Apply mode requires an explicit off-system-disk backup destination.")
        return str((Path.cwd() / "media").resolve())

    def run_backup(self) -> FlowStepResult:
        try:
            destination = self._resolve_backup_destination()
            result: BackupResult = run_windows_backup_subsystem(
                primary_destination=destination,
                fallback_destination=self.backup_fallback_destination,
                dry_run=not self.apply_changes,
            )
        except (BackupError, OSError, ValueError) as exc:
            return FlowStepResult(
                name="backup",
                ok=False,
                apply_mode=self.apply_changes,
                summary=f"Backup step failed: {exc}",
                error=str(exc),
            )

        artifact_count = len(result.artifacts)
        self._backup_root = result.backup_root
        self._verified_backup_manifest = result.manifest_path if result.verified else None
        mode = "APPLY" if self.apply_changes else "DRY-RUN"
        return FlowStepResult(
            name="backup",
            ok=True,
            apply_mode=self.apply_changes,
            summary=(
                f"[{mode}] Backup completed with {artifact_count} artifacts at {result.backup_root}"
            ),
            payload=result.to_dict(),
        )

    def run_ventoy_handoff(
        self,
        *,
        plan_path: str,
        iso_path: str,
        release_manifest_path: str,
        usb_disk_number: int,
        usb_confirmation: str,
        allow_ventoy_install: bool = False,
    ) -> FlowStepResult:
        """Validate the paired artifacts, prepare Ventoy, and write authenticated handoff."""
        try:
            if self._prepared_snapshot is None:
                raise ValueError("A freshly validated partition stage is required.")
            plan_file = Path(plan_path)
            iso_file = Path(iso_path)
            release_file = Path(release_manifest_path)
            if not plan_file.is_file() or not iso_file.is_file() or not release_file.is_file():
                raise ValueError("Plan, ISO, and release manifest files are all required.")
            plan = validate_plan_contract(json.loads(plan_file.read_text(encoding="utf-8")))
            plan = apply_partition_metadata_to_plan(plan, self._prepared_snapshot)
            iso_sha = _sha256(iso_file)
            release_sha = _sha256(release_file)
            if plan.provenance.iso_name != iso_file.name or plan.provenance.iso_sha256 != iso_sha:
                raise ValueError("ISO does not match the plan provenance.")
            if plan.provenance.release_manifest_sha256 != release_sha:
                raise ValueError("Release manifest does not match the plan provenance.")
            integrity_key = secrets.token_bytes(32)
            if not self.apply_changes:
                return FlowStepResult(
                    name="ventoy_handoff",
                    ok=True,
                    apply_mode=False,
                    summary="[DRY-RUN] Paired ISO, plan, target identity, and Ventoy inputs validated.",
                    payload={"integrity_key_hex": integrity_key.hex(), "plan": plan.model_dump(mode="json")},
                )
            prep = install_ventoy_to_usb(
                usb_disk_number,
                allow_install=allow_ventoy_install,
                payload_paths=(iso_file,),
                confirmation=usb_confirmation,
            )
            bundle = stage_ventoy_handoff_bundle(
                prep.validation.data_root,
                iso_file,
                plan,
                backup_info={"backup_manifest": self._verified_backup_manifest},
                filesystem=prep.validation.filesystem,
                integrity_key=integrity_key,
            )
            return FlowStepResult(
                name="ventoy_handoff",
                ok=True,
                apply_mode=True,
                summary="[APPLY] Ventoy and authenticated handoff verified; record the one-time key.",
                payload={
                    "integrity_key_hex": integrity_key.hex(),
                    "ventoy": prep.to_dict(),
                    "handoff": bundle.to_dict(),
                },
            )
        except (OSError, ValueError, VentoyError) as exc:
            return FlowStepResult(
                name="ventoy_handoff",
                ok=False,
                apply_mode=self.apply_changes,
                summary=f"Ventoy/handoff step failed: {exc}",
                error=str(exc),
            )

    def run_partition_prep(self) -> FlowStepResult:
        target_free_space_bytes = max(1, int(self.target_free_gib)) * GIB
        policy = PartitionPrepPolicy(
            target_free_space_bytes=target_free_space_bytes,
            dry_run=not self.apply_changes,
        )
        try:
            if self.apply_changes and not self._verified_backup_manifest:
                raise PartitionPrepError("Apply mode requires a verified backup from this session.")
            journal_path = (
                str(Path(self._backup_root) / "resize-journal.json") if self._backup_root else None
            )
            result: PartitionPrepResult = prepare_unallocated_space(
                policy=policy,
                verified_backup_manifest=self._verified_backup_manifest,
                journal_path=journal_path,
            )
        except (PartitionPrepError, OSError, ValueError) as exc:
            return FlowStepResult(
                name="partition_prep",
                ok=False,
                apply_mode=self.apply_changes,
                summary=f"Partition prep failed: {exc}",
                error=str(exc),
            )

        mode = "APPLY" if self.apply_changes else "DRY-RUN"
        current_gib = _gib(result.current_free_space_bytes)
        final_gib = _gib(result.final_free_space_bytes)
        resize_state = "resized" if result.resized else "no-resize"
        self._prepared_snapshot = result.after_snapshot
        return FlowStepResult(
            name="partition_prep",
            ok=True,
            apply_mode=self.apply_changes,
            summary=(
                f"[{mode}] Partition prep {resize_state}; free space {current_gib} GiB -> {final_gib} GiB"
            ),
            payload=result.to_dict(),
        )
