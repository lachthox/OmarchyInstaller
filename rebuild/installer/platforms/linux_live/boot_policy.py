"""Limine boot policy and Windows preservation checks."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Protocol


WINDOWS_EFI_PATH = Path("EFI/Microsoft/Boot/bootmgfw.efi")
LIMINE_PRIMARY_PATH = Path("EFI/Limine/BOOTX64.EFI")
LIMINE_FALLBACK_PATH = Path("EFI/BOOT/BOOTX64.EFI")


class BootPolicyError(RuntimeError):
    """Raised when boot policy validation fails closed."""


class CommandRunner(Protocol):
    """Minimal command-runner protocol for deterministic stubs."""

    def run(self, command: list[str]) -> subprocess.CompletedProcess[str]: ...


class SubprocessCommandRunner:
    """Default command runner backed by subprocess."""

    def run(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )


@dataclass(frozen=True, slots=True)
class BootEntry:
    boot_id: str
    label: str
    details: str


@dataclass(frozen=True, slots=True)
class BootPolicySummary:
    policy_name: str
    efi_mount: str
    windows_efi_exists: bool
    limine_efi_exists: bool
    windows_boot_entry_present: bool
    limine_boot_entry_present: bool
    boot_order: tuple[str, ...]
    can_finalize: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    emergency_windows_fallback_path: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["boot_order"] = list(self.boot_order)
        payload["blockers"] = list(self.blockers)
        payload["warnings"] = list(self.warnings)
        return payload


@dataclass(frozen=True, slots=True)
class PreinstallPreservationSummary:
    efi_mount: str
    efi_mount_verified: bool
    windows_efi_exists: bool
    can_proceed: bool
    blockers: tuple[str, ...]


def summarize_preinstall_preservation(
    *, efi_mount: str | Path, runner: CommandRunner | None = None
) -> PreinstallPreservationSummary:
    """Verify the mounted ESP and Windows loader without requiring Limine yet."""
    mount = Path(efi_mount)
    active_runner = runner or SubprocessCommandRunner()
    completed = active_runner.run(["findmnt", "--json", "--target", str(mount), "--output", "TARGET,FSTYPE"])
    verified = False
    if completed.returncode == 0:
        try:
            measured = json.loads(completed.stdout).get("filesystems", [])[0]
            verified = (
                Path(str(measured.get("target", ""))).resolve() == mount.resolve()
                and str(measured.get("fstype", "")).casefold() in {"vfat", "fat", "fat32"}
            )
        except (json.JSONDecodeError, IndexError, KeyError, TypeError):
            verified = False
    windows_exists = verified and verify_windows_efi_assets(mount)
    blockers: list[str] = []
    if not verified:
        blockers.append("EFI path is not a verified FAT mount.")
    if not windows_exists:
        blockers.append("Windows EFI asset is missing from EFI partition.")
    return PreinstallPreservationSummary(str(mount), verified, windows_exists, not blockers, tuple(blockers))


def _run_checked(runner: CommandRunner, command: list[str]) -> str:
    completed = runner.run(command)
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "command failed"
        raise BootPolicyError(f"{' '.join(command)}: {detail}")
    return completed.stdout


def verify_windows_efi_assets(efi_mount: str | Path) -> bool:
    root = Path(efi_mount)
    return (root / WINDOWS_EFI_PATH).is_file()


def verify_limine_efi_assets(efi_mount: str | Path) -> bool:
    root = Path(efi_mount)
    return (root / LIMINE_PRIMARY_PATH).is_file() or (root / LIMINE_FALLBACK_PATH).is_file()


def discover_boot_entries(runner: CommandRunner | None = None) -> tuple[BootEntry, ...]:
    active_runner = runner or SubprocessCommandRunner()
    output = _run_checked(active_runner, ["efibootmgr", "-v"])
    entries: list[BootEntry] = []
    line_pattern = re.compile(r"^Boot([0-9A-Fa-f]{4})\*?\s+(.+)$")
    for raw_line in output.splitlines():
        match = line_pattern.match(raw_line.strip())
        if not match:
            continue
        boot_id, details = match.groups()
        label = details.split("\t", 1)[0].strip()
        entries.append(BootEntry(boot_id=boot_id.upper(), label=label, details=details.strip()))
    return tuple(entries)


def discover_boot_order(runner: CommandRunner | None = None) -> tuple[str, ...]:
    active_runner = runner or SubprocessCommandRunner()
    output = _run_checked(active_runner, ["efibootmgr"])
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line.startswith("BootOrder:"):
            continue
        order_raw = line.split(":", 1)[1].strip()
        if not order_raw:
            return tuple()
        return tuple(item.strip().upper() for item in order_raw.split(",") if item.strip())
    return tuple()


def summarize_boot_policy(
    policy_name: str,
    *,
    efi_mount: str | Path,
    runner: CommandRunner | None = None,
) -> BootPolicySummary:
    """Validate Limine + Windows preservation contract before finalization."""
    normalized_policy = policy_name.strip().lower()
    if not normalized_policy:
        raise BootPolicyError("Boot policy name must be provided.")

    entries = discover_boot_entries(runner=runner)
    entry_labels = [entry.label.lower() for entry in entries]
    windows_entry_present = any("windows boot manager" in label for label in entry_labels)
    limine_entry_present = any("limine" in label or "omarchy" in label for label in entry_labels)

    boot_order = discover_boot_order(runner=runner)
    windows_efi_exists = verify_windows_efi_assets(efi_mount)
    limine_efi_exists = verify_limine_efi_assets(efi_mount)

    blockers: list[str] = []
    warnings: list[str] = []

    if not windows_efi_exists:
        blockers.append("Windows EFI asset is missing from EFI partition.")
    if not limine_efi_exists:
        blockers.append("Limine EFI loader is missing from EFI partition.")
    if not windows_entry_present:
        blockers.append("Windows Boot Manager EFI entry is missing.")
    if not limine_entry_present:
        blockers.append("Limine EFI entry is missing.")

    if boot_order:
        first = boot_order[0]
        limine_ids = {entry.boot_id for entry in entries if "limine" in entry.label.lower() or "omarchy" in entry.label.lower()}
        windows_ids = {entry.boot_id for entry in entries if "windows boot manager" in entry.label.lower()}
        if limine_ids and first not in limine_ids:
            warnings.append("BootOrder does not currently prioritize Limine as first entry.")
        if windows_ids and not any(item in windows_ids for item in boot_order):
            blockers.append("BootOrder does not include Windows Boot Manager fallback entry.")
    else:
        warnings.append("BootOrder could not be determined from efibootmgr output.")

    return BootPolicySummary(
        policy_name=normalized_policy,
        efi_mount=str(Path(efi_mount)),
        windows_efi_exists=windows_efi_exists,
        limine_efi_exists=limine_efi_exists,
        windows_boot_entry_present=windows_entry_present,
        limine_boot_entry_present=limine_entry_present,
        boot_order=boot_order,
        can_finalize=not blockers,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
        emergency_windows_fallback_path=str(Path(efi_mount) / WINDOWS_EFI_PATH),
    )


def assert_boot_policy_ready(summary: BootPolicySummary) -> None:
    """Fail closed if Limine + Windows fallback policy is not safe to finalize."""
    if summary.can_finalize:
        return
    raise BootPolicyError("; ".join(summary.blockers))


def validate_boot_policy(policy_name: str) -> bool:
    """Backward-compatible lightweight validator for policy naming."""
    return bool(policy_name.strip())
