"""Preflight summary gate before destructive Linux install actions."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from .discovery import HandoffDiscoveryResult
from .identity import IdentityMatchResult


class PreflightGateError(RuntimeError):
    """Raised when preflight summary indicates destructive actions are unsafe."""


@dataclass(frozen=True, slots=True)
class PreflightSummary:
    schema_version: str
    generated_at_utc: str
    target_disk: dict[str, Any]
    target_partitions: dict[str, Any]
    prepared_free_space: dict[str, Any]
    network_state: dict[str, Any]
    intended_linux_layout: dict[str, Any]
    boot_policy: dict[str, Any]
    omarchy_handoff: dict[str, Any]
    can_proceed: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["blockers"] = list(self.blockers)
        payload["warnings"] = list(self.warnings)
        return payload

    def render_text(self) -> str:
        lines = [
            "Omarchy Linux Live Preflight Summary",
            f"- Generated: {self.generated_at_utc}",
            f"- Target Disk: {self.target_disk.get('path', '')} ({self.target_disk.get('model', '')}, {self.target_disk.get('size_bytes', 0)} bytes)",
            f"- EFI Partition: {self.target_partitions.get('efi_path', '')}",
            f"- Windows Partition: {self.target_partitions.get('windows_path', '')}",
            (
                "- Prepared Free Space: "
                f"{self.prepared_free_space.get('start_sector', 0)}-{self.prepared_free_space.get('end_sector', 0)} "
                f"({self.prepared_free_space.get('size_bytes', 0)} bytes)"
            ),
            f"- Network State: {self.network_state.get('mode', 'unknown')}",
            f"- Boot Policy: {self.boot_policy.get('policy_name', '')}",
            f"- Handoff Mode: {self.omarchy_handoff.get('mode', '')}",
            f"- Can Proceed: {self.can_proceed}",
        ]
        if self.blockers:
            lines.append("- Blockers: " + "; ".join(self.blockers))
        if self.warnings:
            lines.append("- Warnings: " + "; ".join(self.warnings))
        return "\n".join(lines)


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _validate_required_layout(layout: dict[str, Any]) -> tuple[bool, tuple[str, ...]]:
    required_keys = ("filesystem", "mount_root", "encryption")
    missing = tuple(key for key in required_keys if key not in layout or str(layout.get(key, "")).strip() == "")
    return (len(missing) == 0, missing)


def build_preflight_summary(
    identity: IdentityMatchResult,
    handoff: HandoffDiscoveryResult,
    *,
    network_state: dict[str, Any],
    intended_linux_layout: dict[str, Any],
    boot_policy_name: str,
    omarchy_handoff_mode: str = "ventoy-plan",
) -> PreflightSummary:
    """Build mandatory preflight summary for operator confirmation."""
    blockers: list[str] = []
    warnings: list[str] = []

    network_mode = str(network_state.get("mode", "")).strip().lower()
    if network_mode not in {"ethernet", "wifi", "offline"}:
        blockers.append("Network mode is missing or invalid.")
    if network_mode == "offline":
        warnings.append("Network is offline; install flow may require fallback behavior.")

    layout_ok, layout_missing = _validate_required_layout(intended_linux_layout)
    if not layout_ok:
        blockers.append("Linux layout is incomplete: missing " + ", ".join(layout_missing))

    if not boot_policy_name.strip():
        blockers.append("Boot policy is not specified.")
    if not omarchy_handoff_mode.strip():
        blockers.append("Omarchy handoff mode is not specified.")

    target_disk = {
        "path": identity.disk.path,
        "model": identity.disk.model,
        "serial": identity.disk.serial,
        "size_bytes": identity.disk.size_bytes,
        "logical_sector_size": identity.disk.logical_sector_size,
    }
    target_partitions = {
        "efi_path": identity.efi_partition.path,
        "efi_partuuid": identity.efi_partition.partuuid,
        "windows_path": identity.windows_partition.path,
        "windows_partuuid": identity.windows_partition.partuuid,
    }
    prepared_free_space = {
        "start_sector": identity.validated_free_space_start_sector,
        "end_sector": identity.validated_free_space_end_sector,
        "size_bytes": identity.validated_free_space_size_bytes,
    }
    boot_policy = {
        "policy_name": boot_policy_name.strip(),
    }
    omarchy_handoff = {
        "mode": omarchy_handoff_mode.strip(),
        "source_root": handoff.source_root,
        "plan_path": handoff.plan_path,
        "plan_relative_path": handoff.discovered_relative_path,
        "plan_schema_version": handoff.plan.meta.schema_version,
        "plan_release_tag": handoff.plan.meta.release_tag,
        "plan_build_commit": handoff.plan.meta.build_commit,
    }

    return PreflightSummary(
        schema_version="1.0.0",
        generated_at_utc=_utc_now(),
        target_disk=target_disk,
        target_partitions=target_partitions,
        prepared_free_space=prepared_free_space,
        network_state=dict(network_state),
        intended_linux_layout=dict(intended_linux_layout),
        boot_policy=boot_policy,
        omarchy_handoff=omarchy_handoff,
        can_proceed=not blockers,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
    )


def assert_preflight_ready(summary: PreflightSummary) -> None:
    """Fail closed if mandatory preflight summary still contains blockers."""
    if summary.can_proceed:
        return
    raise PreflightGateError("; ".join(summary.blockers))
