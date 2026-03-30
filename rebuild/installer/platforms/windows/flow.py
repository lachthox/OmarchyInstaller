"""Python migration flow for Windows prep steps."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .backup import BackupError, BackupResult, run_windows_backup_subsystem
from .partition_prep import (
    PartitionPrepError,
    PartitionPrepPolicy,
    PartitionPrepResult,
    prepare_unallocated_space,
)

GIB = 1024**3


def _gib(value_bytes: int) -> float:
    return round(value_bytes / GIB, 1)


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

    def _resolve_backup_destination(self) -> str:
        if self.backup_destination and self.backup_destination.strip():
            return self.backup_destination
        return str((Path.cwd() / "media").resolve())

    def run_backup(self) -> FlowStepResult:
        destination = self._resolve_backup_destination()
        try:
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

    def run_partition_prep(self) -> FlowStepResult:
        target_free_space_bytes = max(1, int(self.target_free_gib)) * GIB
        policy = PartitionPrepPolicy(
            target_free_space_bytes=target_free_space_bytes,
            dry_run=not self.apply_changes,
        )
        try:
            result: PartitionPrepResult = prepare_unallocated_space(policy=policy)
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
        return FlowStepResult(
            name="partition_prep",
            ok=True,
            apply_mode=self.apply_changes,
            summary=(
                f"[{mode}] Partition prep {resize_state}; free space {current_gib} GiB -> {final_gib} GiB"
            ),
            payload=result.to_dict(),
        )
