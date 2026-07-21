"""Worker-friendly Linux installation state machine and confirmation boundary."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
import threading
from typing import Protocol

from ..shared import PlanContract, atomic_write_json, validate_plan_contract


REQUIRED_INSTALL_STAGES: tuple[str, ...] = (
    "handoff_discovery",
    "handoff_validation",
    "machine_identity",
    "network",
    "windows_esp_preservation",
    "destructive_summary",
    "typed_confirmation",
    "gpt_backup",
    "partition_creation",
    "actual_geometry_verification",
    "luks_creation",
    "btrfs_creation",
    "subvolume_creation",
    "mount_tree_creation",
    "esp_mount",
    "archinstall_config_generation",
    "archinstall_credentials_generation",
    "archinstall_semantic_validation",
    "base_installation",
    "target_finalization",
    "target_validation",
    "success_marker",
    "cleanup",
    "reboot_readiness",
)


class InstallRunState(StrEnum):
    SIMULATED = "simulated"
    APPLIED = "applied"
    FAILED = "failed"
    CANCELLED = "cancelled"


class LiveStateError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class StageRecord:
    stage: str
    status: str
    detail: str


@dataclass(frozen=True, slots=True)
class LiveStateResult:
    state: InstallRunState
    stages: tuple[StageRecord, ...]
    cancellation_safe: bool
    diagnostic_path: str


class StageBackend(Protocol):
    def run_stage(self, stage: str, plan: PlanContract, *, dry_run: bool) -> tuple[bool, str]: ...


def confirmation_token(plan: PlanContract) -> str:
    suffix = "".join(character for character in plan.disk_identity.gpt_disk_guid if character.isalnum())[-8:]
    return f"INSTALL {suffix.upper()}"


def destructive_summary(plan: PlanContract) -> str:
    extent = plan.prepared_free_space_range
    return (
        f"Create encrypted Linux storage on GPT disk {plan.disk_identity.gpt_disk_guid}; "
        f"sectors {extent.start_sector}-{extent.end_sector} ({extent.size_bytes} bytes). "
        f"Preserve Windows partition {plan.windows_partition_identity.partuuid} and "
        f"ESP {plan.efi_identity.partuuid}."
    )


class LiveInstallStateMachine:
    def __init__(self, backend: StageBackend) -> None:
        self.backend = backend

    def run(
        self,
        plan_payload: PlanContract | dict | None,
        *,
        dry_run: bool,
        typed_confirmation: str = "",
        cancellation: threading.Event | None = None,
        diagnostic_path: str | Path | None = None,
        secrets: tuple[str, ...] = (),
    ) -> LiveStateResult:
        if plan_payload is None:
            raise LiveStateError("A validated plan is required; plan_payload=None cannot succeed.")
        plan = plan_payload if isinstance(plan_payload, PlanContract) else validate_plan_contract(plan_payload)
        if not dry_run and typed_confirmation != confirmation_token(plan):
            raise LiveStateError(f"Typed confirmation must exactly match {confirmation_token(plan)}.")

        records: list[StageRecord] = []
        cancellation_safe = True
        try:
            for stage in REQUIRED_INSTALL_STAGES:
                if cancellation and cancellation.is_set():
                    if cancellation_safe:
                        records.append(StageRecord(stage, "cancelled", "Cancelled at a safe boundary."))
                        return LiveStateResult(
                            InstallRunState.CANCELLED, tuple(records), True, str(diagnostic_path or "")
                        )
                    records.append(
                        StageRecord(stage, "continued", "Cancellation disabled after partition changes began.")
                    )
                if stage == "partition_creation" and not dry_run:
                    cancellation_safe = False
                if stage == "destructive_summary":
                    records.append(StageRecord(stage, "simulated" if dry_run else "passed", destructive_summary(plan)))
                    continue
                if stage == "typed_confirmation":
                    records.append(
                        StageRecord(
                            stage,
                            "simulated" if dry_run else "passed",
                            "Confirmation bypassed only for simulation."
                            if dry_run
                            else "Exact disk-bound confirmation accepted.",
                        )
                    )
                    continue
                ok, detail = self.backend.run_stage(stage, plan, dry_run=dry_run)
                if not ok:
                    raise LiveStateError(f"Stage {stage} failed: {detail}")
                records.append(StageRecord(stage, "simulated" if dry_run else "passed", detail))
        except Exception as exc:
            message = str(exc)
            for secret in secrets:
                if secret:
                    message = message.replace(secret, "<redacted>")
            records.append(StageRecord(records[-1].stage if records else "startup", "failed", message))
            if diagnostic_path:
                atomic_write_json(
                    Path(diagnostic_path),
                    {
                        "state": InstallRunState.FAILED,
                        "stages": [asdict(record) for record in records],
                        "cancellation_safe": cancellation_safe,
                    },
                )
            raise LiveStateError(message) from exc

        state = InstallRunState.SIMULATED if dry_run else InstallRunState.APPLIED
        return LiveStateResult(state, tuple(records), cancellation_safe, str(diagnostic_path or ""))
