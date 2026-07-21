"""Installed-system post-Omarchy normalization and boot policy restoration."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import subprocess
from typing import Any, Protocol

from ..linux_live.boot_policy import (
    BootPolicySummary,
    discover_boot_entries,
    discover_boot_order,
    summarize_boot_policy,
)


DEFAULT_EFI_MOUNT_CANDIDATES = (
    Path("/boot/efi"),
    Path("/efi"),
    Path("/boot"),
)


class CommandRunner(Protocol):
    """Command runner interface for deterministic repair execution."""

    def run(self, command: list[str]) -> subprocess.CompletedProcess[str]: ...


class SubprocessCommandRunner:
    """Command runner backed by subprocess without shell interpolation."""

    def run(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )


class PostInstallNormalizationError(RuntimeError):
    """Raised when boot policy restoration cannot safely complete."""


@dataclass(frozen=True, slots=True)
class BootstrapContract:
    bootstrap_url: str
    bootstrap_repo: str
    bootstrap_root: str
    metadata_file: str
    required_files: tuple[str, ...]
    required_metadata_paths: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["required_files"] = list(self.required_files)
        payload["required_metadata_paths"] = list(self.required_metadata_paths)
        return payload


@dataclass(frozen=True, slots=True)
class BootstrapHealthResult:
    contract: BootstrapContract
    can_proceed: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    discovered_files: tuple[str, ...]
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["contract"] = self.contract.to_dict()
        payload["blockers"] = list(self.blockers)
        payload["warnings"] = list(self.warnings)
        payload["discovered_files"] = list(self.discovered_files)
        return payload


@dataclass(frozen=True, slots=True)
class PostInstallNormalizationResult:
    policy_name: str
    efi_mount: str
    can_proceed: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    repair_actions: tuple[str, ...]
    boot_policy_summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["blockers"] = list(self.blockers)
        payload["warnings"] = list(self.warnings)
        payload["repair_actions"] = list(self.repair_actions)
        return payload


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_bootstrap_contract(
    *,
    bootstrap_url: str = "https://omarchy.org/install",
    bootstrap_repo: str = "lachthox/OmarchyInstaller",
    bootstrap_root: str | Path = "/opt/omarchy-setup",
    metadata_file: str = "build-metadata.json",
) -> BootstrapContract:
    root = Path(bootstrap_root)
    return BootstrapContract(
        bootstrap_url=bootstrap_url.strip(),
        bootstrap_repo=bootstrap_repo.strip(),
        bootstrap_root=str(root),
        metadata_file=metadata_file.strip(),
        required_files=(
            "setup.sh",
            "main.py",
            "requirements.txt",
            "runtime-packages.txt",
            "hooks/live-autostart.sh",
            "hooks/firstboot-wrapper.sh",
        ),
        required_metadata_paths=(
            "runtime.entrypoint",
            "runtime.setup_wrapper",
            "runtime.entrypoint_compat_alias",
            "runtime.required_system_packages_file",
            "startup_hooks.live_tty_hook",
            "startup_hooks.payload_hook_reference",
        ),
    )


def evaluate_bootstrap_health(contract: BootstrapContract) -> BootstrapHealthResult:
    blockers: list[str] = []
    warnings: list[str] = []
    root = Path(contract.bootstrap_root)
    discovered_files: list[str] = []

    if not contract.bootstrap_url.startswith("https://"):
        blockers.append("bootstrap URL must use https://")
    if "/" not in contract.bootstrap_repo:
        warnings.append("bootstrap repo contract is not owner/repo formatted")
    if not root.exists() or not root.is_dir():
        blockers.append(f"bootstrap root is missing: {root}")

    metadata_path = root / contract.metadata_file
    metadata: dict[str, Any] = {}
    if metadata_path.is_file():
        try:
            metadata = _read_json(metadata_path)
        except Exception as exc:
            blockers.append(f"bootstrap metadata is unreadable: {exc}")
    else:
        blockers.append(f"bootstrap metadata file is missing: {metadata_path}")

    for rel_path in contract.required_files:
        candidate = root / rel_path
        if candidate.exists():
            discovered_files.append(str(candidate))
            continue
        blockers.append(f"required bootstrap file missing: {candidate}")

    for dotted_path in contract.required_metadata_paths:
        current: Any = metadata
        for segment in dotted_path.split("."):
            if not isinstance(current, dict) or segment not in current:
                current = None
                break
            current = current[segment]
        if current is None:
            blockers.append(f"bootstrap metadata missing contract path: {dotted_path}")

    if metadata:
        runtime = metadata.get("runtime", {})
        startup_hooks = metadata.get("startup_hooks", {})
        if runtime.get("entrypoint") != "python3 /opt/omarchy-installer/main.py":
            blockers.append("bootstrap runtime entrypoint drifted from the release contract")
        if runtime.get("setup_wrapper") != "/opt/omarchy-setup/setup.sh":
            blockers.append("bootstrap setup wrapper drifted from the release contract")
        if runtime.get("entrypoint_compat_alias") != "python3 /opt/omarchy-setup/main.py":
            warnings.append("bootstrap compatibility alias differs from the preferred contract")
        if startup_hooks.get("payload_hook_reference") != "/opt/omarchy-setup/hooks/live-autostart.sh":
            blockers.append("bootstrap live autostart hook is missing or relocated")

    return BootstrapHealthResult(
        contract=contract,
        can_proceed=not blockers,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
        discovered_files=tuple(sorted(set(discovered_files))),
        metadata=metadata,
    )


def _run_checked(runner: CommandRunner, command: list[str]) -> str:
    completed = runner.run(command)
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "command failed"
        raise PostInstallNormalizationError(f"{' '.join(command)}: {detail}")
    return completed.stdout.strip()


def _repair_boot_order(
    *,
    runner: CommandRunner,
    summary: BootPolicySummary,
) -> tuple[str, ...]:
    entries = discover_boot_entries(runner=runner)
    if not entries:
        raise PostInstallNormalizationError("Cannot repair boot order without EFI boot entries.")

    limine_ids = [entry.boot_id for entry in entries if "limine" in entry.label.lower() or "omarchy" in entry.label.lower()]
    windows_ids = [entry.boot_id for entry in entries if "windows boot manager" in entry.label.lower()]
    if not limine_ids:
        raise PostInstallNormalizationError("Cannot repair boot order because the Limine entry is missing.")
    if not windows_ids:
        raise PostInstallNormalizationError("Cannot repair boot order because the Windows fallback entry is missing.")

    current_order = list(summary.boot_order) or list(discover_boot_order(runner=runner))
    desired_order: list[str] = []
    for boot_id in [*limine_ids, *windows_ids, *current_order]:
        if boot_id and boot_id not in desired_order:
            desired_order.append(boot_id)

    if not desired_order:
        raise PostInstallNormalizationError("Cannot derive a deterministic EFI boot order.")
    if tuple(desired_order) == summary.boot_order:
        return tuple()

    _run_checked(runner, ["efibootmgr", "-o", ",".join(desired_order)])
    return (f"efibootmgr -o {','.join(desired_order)}",)


def normalize_boot_policy(
    *,
    efi_mount: str | Path | None = None,
    policy_name: str = "omarchy-post-install",
    runner: CommandRunner | None = None,
) -> PostInstallNormalizationResult:
    active_runner = runner or SubprocessCommandRunner()
    mount_path = Path(efi_mount) if efi_mount is not None else next(
        (candidate for candidate in DEFAULT_EFI_MOUNT_CANDIDATES if candidate.exists()),
        DEFAULT_EFI_MOUNT_CANDIDATES[0],
    )

    summary = summarize_boot_policy(policy_name, efi_mount=mount_path, runner=active_runner)
    blockers = list(summary.blockers)
    warnings = list(summary.warnings)
    repair_actions: list[str] = []

    if blockers:
        return PostInstallNormalizationResult(
            policy_name=summary.policy_name,
            efi_mount=str(mount_path),
            can_proceed=False,
            blockers=tuple(blockers),
            warnings=tuple(warnings),
            repair_actions=tuple(),
            boot_policy_summary=summary.to_dict(),
        )

    if warnings and summary.limine_boot_entry_present and summary.windows_boot_entry_present:
        try:
            repair_actions.extend(_repair_boot_order(runner=active_runner, summary=summary))
        except PostInstallNormalizationError as exc:
            blockers.append(str(exc))
        else:
            summary = summarize_boot_policy(policy_name, efi_mount=mount_path, runner=active_runner)
            if summary.blockers:
                blockers.extend(summary.blockers)
            warnings = list(summary.warnings)

    return PostInstallNormalizationResult(
        policy_name=summary.policy_name,
        efi_mount=str(mount_path),
        can_proceed=not blockers,
        blockers=tuple(blockers),
        warnings=tuple(warnings),
        repair_actions=tuple(repair_actions),
        boot_policy_summary=summary.to_dict(),
    )
