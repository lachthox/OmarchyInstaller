"""Limine boot policy and Windows preservation checks."""

from __future__ import annotations

from dataclasses import asdict, dataclass
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


def _run_checked(runner: CommandRunner, command: list[str]) -> str:
    completed = runner.run(command)
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "command failed"
        raise BootPolicyError(f"{' '.join(command)}: {detail}")
    return completed.stdout


def _validate_efi_mount(efi_mount: str | Path) -> tuple[Path, tuple[str, ...], tuple[str, ...]]:
    root = Path(efi_mount).expanduser()
    blockers: list[str] = []
    warnings: list[str] = []

    if not root.is_absolute():
        blockers.append(f"EFI mount path must be absolute (got: {root}).")
    if not root.exists():
        blockers.append(f"EFI mount path does not exist: {root}.")
    elif not root.is_dir():
        blockers.append(f"EFI mount path is not a directory: {root}.")
    else:
        try:
            resolved = root.resolve()
            if resolved == Path("/"):
                blockers.append("EFI mount path resolves to '/'; refusing unsafe root path.")
            if resolved == Path("/boot"):
                blockers.append("EFI mount path resolves to '/boot'; expected mounted ESP (for example /boot/efi).")
            if root.is_symlink():
                warnings.append(f"EFI mount path is a symlink: {root}.")
            if not resolved.is_mount():
                warnings.append(
                    f"EFI path is not a mount point: {resolved}. "
                    "Ensure the EFI System Partition is mounted before finalize."
                )
        except OSError as exc:
            blockers.append(f"Could not resolve EFI mount path safely: {exc}")

    return root, tuple(blockers), tuple(warnings)


def _is_safe_relative_target(root: Path, relative_path: Path) -> bool:
    try:
        candidate = (root / relative_path).resolve()
        candidate.relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def verify_windows_efi_assets(efi_mount: str | Path) -> bool:
    root = Path(efi_mount)
    if not _is_safe_relative_target(root, WINDOWS_EFI_PATH):
        return False
    return (root / WINDOWS_EFI_PATH).is_file()


def verify_limine_efi_assets(efi_mount: str | Path) -> bool:
    root = Path(efi_mount)
    if not _is_safe_relative_target(root, LIMINE_PRIMARY_PATH):
        return False
    if not _is_safe_relative_target(root, LIMINE_FALLBACK_PATH):
        return False
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

    root, mount_blockers, mount_warnings = _validate_efi_mount(efi_mount)
    if mount_blockers:
        return BootPolicySummary(
            policy_name=normalized_policy,
            efi_mount=str(root),
            windows_efi_exists=False,
            limine_efi_exists=False,
            windows_boot_entry_present=False,
            limine_boot_entry_present=False,
            boot_order=tuple(),
            can_finalize=False,
            blockers=tuple(mount_blockers),
            warnings=tuple(mount_warnings),
            emergency_windows_fallback_path=str(root / WINDOWS_EFI_PATH),
        )

    entries = discover_boot_entries(runner=runner)
    entry_labels = [entry.label.lower() for entry in entries]
    windows_entry_present = any("windows boot manager" in label for label in entry_labels)
    limine_entry_present = any("limine" in label or "omarchy" in label for label in entry_labels)

    boot_order = discover_boot_order(runner=runner)
    windows_efi_exists = verify_windows_efi_assets(efi_mount)
    limine_efi_exists = verify_limine_efi_assets(efi_mount)

    blockers: list[str] = list(mount_blockers)
    warnings: list[str] = list(mount_warnings)

    windows_target = root / WINDOWS_EFI_PATH
    limine_primary_target = root / LIMINE_PRIMARY_PATH
    limine_fallback_target = root / LIMINE_FALLBACK_PATH

    if not _is_safe_relative_target(root, WINDOWS_EFI_PATH):
        blockers.append(f"Unsafe Windows EFI target path resolved outside EFI mount: {windows_target}")
    if not _is_safe_relative_target(root, LIMINE_PRIMARY_PATH):
        blockers.append(f"Unsafe Limine EFI primary path resolved outside EFI mount: {limine_primary_target}")
    if not _is_safe_relative_target(root, LIMINE_FALLBACK_PATH):
        blockers.append(f"Unsafe Limine EFI fallback path resolved outside EFI mount: {limine_fallback_target}")

    if not windows_efi_exists:
        blockers.append(f"Windows EFI asset is missing: {windows_target}")
    if not limine_efi_exists:
        blockers.append(
            "Limine EFI loader is missing: "
            f"{limine_primary_target} or {limine_fallback_target}"
        )
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
        efi_mount=str(root),
        windows_efi_exists=windows_efi_exists,
        limine_efi_exists=limine_efi_exists,
        windows_boot_entry_present=windows_entry_present,
        limine_boot_entry_present=limine_entry_present,
        boot_order=boot_order,
        can_finalize=not blockers,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
        emergency_windows_fallback_path=str(root / WINDOWS_EFI_PATH),
    )


def assert_boot_policy_ready(summary: BootPolicySummary) -> None:
    """Fail closed if Limine + Windows fallback policy is not safe to finalize."""
    if summary.can_finalize:
        return
    raise BootPolicyError("; ".join(summary.blockers))


def validate_boot_policy(policy_name: str) -> bool:
    """Backward-compatible lightweight validator for policy naming."""
    return bool(policy_name.strip())
