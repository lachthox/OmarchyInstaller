"""Expected-state and result models for the installed-system boot guardian."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal
import json

from ..linux_live.boot_policy import BootEntry


BOOT_GUARDIAN_STATE_SCHEMA_VERSION = "1.0.0"
DEFAULT_BOOT_GUARDIAN_STATE_PATH = Path("/var/lib/omarchy/boot/expected-state.json")


class BootGuardianStateError(RuntimeError):
    """Raised when a boot guardian state payload cannot be loaded safely."""


def _default_expected_boot_labels() -> dict[str, tuple[str, ...]]:
    return {
        "limine": ("Limine", "Omarchy"),
        "windows": ("Windows Boot Manager",),
    }


@dataclass(frozen=True, slots=True)
class BootGuardianExpectedState:
    schema_version: str = BOOT_GUARDIAN_STATE_SCHEMA_VERSION
    policy_name: str = "omarchy-boot-guardian"
    efi_mount: str = "/boot/efi"
    efi_filesystem_uuid: str = ""
    efi_partuuid: str = ""
    windows_efi_relative_path: str = "EFI/Microsoft/Boot/bootmgfw.efi"
    limine_efi_relative_paths: tuple[str, ...] = ("EFI/Limine/BOOTX64.EFI", "EFI/BOOT/BOOTX64.EFI")
    expected_boot_labels: dict[str, tuple[str, ...]] = field(default_factory=_default_expected_boot_labels)
    preferred_boot_order: tuple[str, ...] = ("limine", "windows")
    repair_policy: str = "boot-order-only"
    warning_notify: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["limine_efi_relative_paths"] = list(self.limine_efi_relative_paths)
        payload["preferred_boot_order"] = list(self.preferred_boot_order)
        payload["expected_boot_labels"] = {
            role: list(labels) for role, labels in self.expected_boot_labels.items()
        }
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "BootGuardianExpectedState":
        if not isinstance(payload, dict):
            raise BootGuardianStateError("Boot guardian expected-state payload must be a dictionary.")

        schema_version = str(payload.get("schema_version", "")).strip() or BOOT_GUARDIAN_STATE_SCHEMA_VERSION
        if schema_version != BOOT_GUARDIAN_STATE_SCHEMA_VERSION:
            raise BootGuardianStateError(
                f"Unsupported boot guardian state schema version: {schema_version}"
            )
        policy_name = str(payload.get("policy_name", "")).strip() or "omarchy-boot-guardian"
        efi_mount = str(payload.get("efi_mount", "")).strip() or "/boot/efi"
        efi_filesystem_uuid = str(payload.get("efi_filesystem_uuid", "")).strip().casefold()
        efi_partuuid = str(payload.get("efi_partuuid", "")).strip().casefold()
        if not efi_filesystem_uuid or not efi_partuuid:
            raise BootGuardianStateError("Expected-state must contain machine-specific EFI UUID and PARTUUID.")
        windows_efi_relative_path = str(payload.get("windows_efi_relative_path", "")).strip() or "EFI/Microsoft/Boot/bootmgfw.efi"

        limine_raw = payload.get("limine_efi_relative_paths", ())
        if isinstance(limine_raw, (list, tuple)):
            limine_efi_relative_paths = tuple(str(item).strip() for item in limine_raw if str(item).strip())
        else:
            raise BootGuardianStateError("limine_efi_relative_paths must be a list of strings.")
        if not limine_efi_relative_paths:
            limine_efi_relative_paths = ("EFI/Limine/BOOTX64.EFI", "EFI/BOOT/BOOTX64.EFI")

        labels_raw = payload.get("expected_boot_labels", {})
        if not isinstance(labels_raw, dict):
            raise BootGuardianStateError("expected_boot_labels must be an object mapping roles to labels.")
        expected_boot_labels: dict[str, tuple[str, ...]] = {}
        for role, labels in labels_raw.items():
            if isinstance(labels, (list, tuple)):
                cleaned = tuple(str(item).strip() for item in labels if str(item).strip())
            else:
                raise BootGuardianStateError(f"expected_boot_labels[{role!r}] must be a list of strings.")
            if cleaned:
                expected_boot_labels[str(role).strip().lower()] = cleaned
        if not expected_boot_labels:
            expected_boot_labels = _default_expected_boot_labels()

        preferred_raw = payload.get("preferred_boot_order", ())
        if isinstance(preferred_raw, (list, tuple)):
            preferred_boot_order = tuple(str(item).strip().lower() for item in preferred_raw if str(item).strip())
        else:
            raise BootGuardianStateError("preferred_boot_order must be a list of role names.")
        if not preferred_boot_order:
            preferred_boot_order = ("limine", "windows")

        repair_policy = str(payload.get("repair_policy", "")).strip() or "boot-order-only"
        if repair_policy != "boot-order-only":
            raise BootGuardianStateError(f"Unsupported boot guardian repair policy: {repair_policy}")
        warning_notify = bool(payload.get("warning_notify", False))

        return cls(
            schema_version=schema_version,
            policy_name=policy_name,
            efi_mount=efi_mount,
            efi_filesystem_uuid=efi_filesystem_uuid,
            efi_partuuid=efi_partuuid,
            windows_efi_relative_path=windows_efi_relative_path,
            limine_efi_relative_paths=limine_efi_relative_paths,
            expected_boot_labels=expected_boot_labels,
            preferred_boot_order=preferred_boot_order,
            repair_policy=repair_policy,
            warning_notify=warning_notify,
        )


@dataclass(frozen=True, slots=True)
class BootGuardianObservedState:
    efi_mount: str
    efi_mount_exists: bool
    efi_mount_verified: bool
    efi_filesystem_uuid: str
    efi_partuuid: str
    windows_efi_exists: bool
    limine_efi_exists: bool
    boot_entries: tuple[BootEntry, ...]
    boot_order: tuple[str, ...]
    resolved_boot_ids: dict[str, str]
    resolved_boot_labels: dict[str, str]
    measurement_error: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["boot_entries"] = [
            {
                "boot_id": entry.boot_id,
                "label": entry.label,
                "details": entry.details,
            }
            for entry in self.boot_entries
        ]
        payload["boot_order"] = list(self.boot_order)
        return payload


@dataclass(frozen=True, slots=True)
class BootGuardianFinding:
    code: str
    severity: Literal["healthy", "warning", "critical"]
    message: str
    repairable: bool = False
    repair_command: str = ""
    repair_path: str = "omarchy-boot-repair"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class BootGuardianResult:
    schema_version: str
    mode: Literal["check", "repair"]
    status: Literal["healthy", "warning", "critical", "repaired"]
    severity: Literal["healthy", "warning", "critical"]
    notify: bool
    can_repair: bool
    repair_attempted: bool
    repaired: bool
    exit_code: int
    state_source: str
    expected_state: BootGuardianExpectedState
    observed_state: BootGuardianObservedState
    findings: tuple[BootGuardianFinding, ...]
    repair_actions: tuple[str, ...]
    repair_command: str = ""
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["expected_state"] = self.expected_state.to_dict()
        payload["observed_state"] = self.observed_state.to_dict()
        payload["findings"] = [finding.to_dict() for finding in self.findings]
        payload["repair_actions"] = list(self.repair_actions)
        return payload

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)
