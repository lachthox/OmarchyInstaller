"""Install orchestration scaffolding for live environment."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import subprocess
import shutil
from tempfile import gettempdir
from typing import Any, Protocol
from uuid import uuid4

from ...shared import PlanContract, validate_plan_contract
from .identity import MachineIdentityError, match_machine_identity


DEFAULT_LIVE_STAGE_ROOT = Path(gettempdir()) / "omarchy-live-install"
DEFAULT_CRYPT_MAPPER_NAME = "omarchy-cryptroot"
DEFAULT_MOUNT_ROOT = "/mnt"
DEFAULT_STANDALONE_EFI_SIZE_MIB = 1024
DEFAULT_BOOTLOADER = "limine"


class LiveInstallError(RuntimeError):
    """Raised when live install staging cannot be managed safely."""


class CommandRunner(Protocol):
    """Minimal command runner protocol for deterministic stubs."""

    def run(self, command: list[str], input_text: str | None = None) -> subprocess.CompletedProcess[str]: ...


class SubprocessCommandRunner:
    """Default command runner backed by subprocess."""

    def run(self, command: list[str], input_text: str | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            input=input_text,
            check=False,
        )


@dataclass(frozen=True, slots=True)
class LiveInstallExecutionResult:
    status: str
    stage_root: str
    staged_files: tuple[str, ...]
    removed_paths: tuple[str, ...]
    commands: tuple[str, ...]
    target_partition_path: str
    efi_partition_path: str
    target_disk_path: str
    mount_root: str
    encryption_mapper: str
    dry_run: bool

    def to_dict(self) -> dict[str, str]:
        payload = asdict(self)
        payload["staged_files"] = list(self.staged_files)
        payload["removed_paths"] = list(self.removed_paths)
        payload["commands"] = list(self.commands)
        return payload


def resolve_live_stage_root(base_dir: str | Path | None = None, *, run_id: str | None = None) -> Path:
    root = Path(base_dir).expanduser() if base_dir is not None else DEFAULT_LIVE_STAGE_ROOT
    stage_id = run_id or uuid4().hex
    return root / stage_id


def _assert_within_stage_root(stage_root: Path, candidate: Path) -> None:
    try:
        candidate.resolve().relative_to(stage_root.resolve())
    except ValueError as exc:
        raise LiveInstallError(f"Path escapes live staging root: {candidate}") from exc


def stage_live_runtime_artifact(stage_root: str | Path, relative_path: str | Path, content: str | dict) -> Path:
    root = Path(stage_root)
    target = root / Path(relative_path)
    _assert_within_stage_root(root, target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, dict):
        target.write_text(json.dumps(content, indent=2) + "\n", encoding="utf-8")
    else:
        target.write_text(str(content), encoding="utf-8")
    return target


def cleanup_live_stage(stage_root: str | Path, *, residual_paths: tuple[str, ...] = ()) -> tuple[str, ...]:
    root = Path(stage_root)
    removed: list[str] = []

    for residual in residual_paths:
        candidate = root / Path(residual)
        if not candidate.exists():
            continue
        _assert_within_stage_root(root, candidate)
        if candidate.is_dir():
            shutil.rmtree(candidate)
        else:
            candidate.unlink()
        removed.append(str(candidate))

    if root.exists():
        shutil.rmtree(root)
        removed.append(str(root))

    return tuple(removed)


def _run_checked(
    runner: CommandRunner,
    command: list[str],
    *,
    input_text: str | None = None,
) -> str:
    completed = runner.run(command, input_text=input_text)
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "command failed"
        raise LiveInstallError(f"{' '.join(command)}: {detail}")
    return completed.stdout.strip()


def _run_cleanup_best_effort(
    runner: CommandRunner,
    command: list[str],
    install_log_lines: list[str],
) -> None:
    completed = runner.run(command)
    if completed.returncode == 0:
        install_log_lines.append(f"CLEANUP: {' '.join(command)}")
        return
    detail = completed.stderr.strip() or completed.stdout.strip() or "command failed"
    install_log_lines.append(f"CLEANUP-FAILED: {' '.join(command)} -> {detail}")


def _parse_lsblk_partitions(payload: dict[str, Any]) -> list[dict[str, Any]]:
    partitions: list[dict[str, Any]] = []

    def walk(node: dict[str, Any]) -> None:
        node_type = str(node.get("type", "")).strip().lower()
        if node_type == "part":
            partitions.append(node)
        for child in node.get("children", []) or []:
            if isinstance(child, dict):
                walk(child)

    for device in payload.get("blockdevices", []) or []:
        if isinstance(device, dict):
            walk(device)
    return partitions


def _discover_partition_path(
    runner: CommandRunner,
    *,
    disk_path: str,
    start_sector: int,
    expected_size_bytes: int,
) -> str:
    output = _run_checked(
        runner,
        [
            "lsblk",
            "-b",
            "-J",
            "-o",
            "PATH,TYPE,START,SIZE,PKNAME",
        ],
    )
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as exc:
        raise LiveInstallError(f"Invalid lsblk JSON while discovering partition: {exc}") from exc

    disk_name = Path(disk_path).name
    candidates: list[str] = []
    for partition in _parse_lsblk_partitions(payload):
        pkname = str(partition.get("pkname", "")).strip()
        if pkname != disk_name:
            continue
        try:
            part_start = int(str(partition.get("start", "0")).strip())
            part_size = int(str(partition.get("size", "0")).strip())
        except ValueError:
            continue
        if part_start == start_sector and part_size == expected_size_bytes:
            path = str(partition.get("path", "")).strip()
            if path:
                candidates.append(path)

    if not candidates:
        raise LiveInstallError("Could not resolve newly created Linux partition path after sgdisk.")
    if len(candidates) > 1:
        raise LiveInstallError("Linux partition discovery is ambiguous after sgdisk.")
    return candidates[0]


def _cpu_ucode_package() -> str:
    cpuinfo = Path("/proc/cpuinfo")
    if not cpuinfo.exists():
        return ""
    try:
        text = cpuinfo.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    for raw_line in text.splitlines():
        if raw_line.lower().startswith("vendor_id"):
            _, _, value = raw_line.partition(":")
            vendor = value.strip()
            if vendor == "GenuineIntel":
                return "intel-ucode"
            if vendor == "AuthenticAMD":
                return "amd-ucode"
            break
    return ""


def _default_archinstall_packages() -> list[str]:
    packages = [
        "base",
        "base-devel",
        "linux-firmware",
        "git",
        "vim",
        "btrfs-progs",
        "sudo",
        "networkmanager",
        "wpa_supplicant",
    ]
    ucode = _cpu_ucode_package()
    if ucode:
        packages.append(ucode)
    return packages


def _build_archinstall_config(
    *,
    target_disk_path: str,
    efi_partition_path: str,
    target_partition_path: str,
    hostname: str,
    username: str,
    user_password: str,
    encryption_passphrase: str,
    timezone: str,
    locale: str,
    keyboard_layout: str,
    bootloader: str,
    wipe_efi: bool,
) -> dict[str, Any]:
    return {
        "archinstall-language": "English",
        "audio_config": {
            "audio": "pipewire",
        },
        "bootloader_config": {
            "bootloader": bootloader,
        },
        "disk_config": {
            "config_type": "manual_partitioning",
            "device_modifications": [
                {
                    "device": target_disk_path,
                    "partitions": [
                        {
                            "dev_name": efi_partition_path,
                            "mountpoint": "/boot",
                            "fs_type": "vfat",
                            "wipe": wipe_efi,
                        },
                        {
                            "dev_name": target_partition_path,
                            "mountpoint": "/",
                            "fs_type": "btrfs",
                            "btrfs": {
                                "subvolumes": [
                                    {"name": "@", "mountpoint": "/"},
                                    {"name": "@home", "mountpoint": "/home"},
                                    {"name": "@log", "mountpoint": "/var/log"},
                                    {"name": "@pkg", "mountpoint": "/var/cache/pacman/pkg"},
                                    {"name": "@snapshots", "mountpoint": "/.snapshots"},
                                ]
                            },
                            "encrypted": True,
                            "encryption_password": encryption_passphrase,
                            "encryption_type": "luks2",
                            "wipe": True,
                        },
                    ],
                }
            ],
        },
        "hostname": hostname,
        "kernels": ["linux"],
        "locale_config": {
            "kb_layout": keyboard_layout,
            "sys_enc": "UTF-8",
            "sys_lang": locale,
        },
        "network_config": {
            "type": "nm",
        },
        "ntp": True,
        "packages": _default_archinstall_packages(),
        "profile_config": {
            "profile": {
                "main": "Minimal",
            }
        },
        "timezone": timezone,
        "users": [
            {
                "username": username,
                "password": user_password,
                "is_superuser": True,
            }
        ],
    }


def _build_plan_partition_command_plan(
    *,
    target_disk_path: str,
    start_sector: int,
    end_sector: int,
) -> list[list[str]]:
    return [
        [
            "sgdisk",
            f"--new=0:{start_sector}:{end_sector}",
            "--typecode=0:8300",
            "--change-name=0:omarchy-linux",
            target_disk_path,
        ],
        ["partprobe", target_disk_path],
        ["udevadm", "settle"],
    ]


def _parse_lsblk_disks(payload: dict[str, Any]) -> list[dict[str, Any]]:
    disks: list[dict[str, Any]] = []
    for device in payload.get("blockdevices", []) or []:
        if not isinstance(device, dict):
            continue
        if str(device.get("type", "")).strip().lower() == "disk":
            disks.append(device)
    return disks


def _discover_default_disk(runner: CommandRunner) -> str:
    output = _run_checked(
        runner,
        ["lsblk", "-b", "-J", "-o", "PATH,TYPE,SIZE,RM,HOTPLUG,MODEL"],
    )
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as exc:
        raise LiveInstallError(f"Invalid lsblk JSON while selecting target disk: {exc}") from exc

    candidates: list[tuple[int, str]] = []
    for disk in _parse_lsblk_disks(payload):
        path = str(disk.get("path", "")).strip()
        if not path:
            continue
        if str(disk.get("rm", "0")).strip() == "1":
            continue
        if str(disk.get("hotplug", "0")).strip() == "1":
            continue
        try:
            size = int(str(disk.get("size", "0")).strip())
        except ValueError:
            size = 0
        if size <= 0:
            continue
        candidates.append((size, path))

    if not candidates:
        raise LiveInstallError("Could not select a non-removable target disk for standalone install.")

    candidates.sort(reverse=True)
    return candidates[0][1]


def _blockdev_size(runner: CommandRunner, disk_path: str) -> tuple[int, int]:
    sector_size_raw = _run_checked(runner, ["blockdev", "--getss", disk_path])
    total_sectors_raw = _run_checked(runner, ["blockdev", "--getsz", disk_path])
    try:
        sector_size = int(sector_size_raw.strip())
        total_sectors = int(total_sectors_raw.strip())
    except ValueError as exc:
        raise LiveInstallError(f"Invalid blockdev output for {disk_path}.") from exc
    if sector_size <= 0 or total_sectors <= 0:
        raise LiveInstallError(f"Invalid geometry reported for {disk_path}.")
    return sector_size, total_sectors


def _standalone_partition_bounds(runner: CommandRunner, disk_path: str) -> tuple[int, int]:
    sector_size, total_sectors = _blockdev_size(runner, disk_path)
    first_usable_sector = 2048
    efi_sectors = (DEFAULT_STANDALONE_EFI_SIZE_MIB * 1024 * 1024) // sector_size
    efi_end = first_usable_sector + efi_sectors - 1
    root_start = efi_end + 1
    root_end = total_sectors - 34
    if root_end <= root_start:
        raise LiveInstallError(f"Disk {disk_path} is too small for standalone whole-disk layout.")
    return efi_end, root_start


def _build_standalone_command_plan(*, target_disk_path: str, efi_end_sector: int, root_start_sector: int) -> list[list[str]]:
    return [
        ["sgdisk", "--zap-all", target_disk_path],
        ["sgdisk", "-o", target_disk_path],
        [
            "sgdisk",
            f"--new=1:2048:{efi_end_sector}",
            "--typecode=1:ef00",
            "--change-name=1:OmarchyEFI",
            target_disk_path,
        ],
        [
            "sgdisk",
            f"--new=2:{root_start_sector}:0",
            "--typecode=2:8300",
            "--change-name=2:OmarchyRoot",
            target_disk_path,
        ],
        ["partprobe", target_disk_path],
        ["udevadm", "settle"],
    ]


def _find_partition_by_label(runner: CommandRunner, *, disk_path: str, label: str) -> str:
    output = _run_checked(
        runner,
        ["lsblk", "-J", "-o", "PATH,TYPE,PARTLABEL,PKNAME"],
    )
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as exc:
        raise LiveInstallError(f"Invalid lsblk JSON while resolving {label} partition: {exc}") from exc

    disk_name = Path(disk_path).name

    def walk(node: dict[str, Any]) -> str:
        if str(node.get("type", "")).strip().lower() == "part":
            pkname = str(node.get("pkname", "")).strip()
            partlabel = str(node.get("partlabel", "")).strip()
            if pkname == disk_name and partlabel == label:
                return str(node.get("path", "")).strip()
        for child in node.get("children", []) or []:
            if isinstance(child, dict):
                match = walk(child)
                if match:
                    return match
        return ""

    for device in payload.get("blockdevices", []) or []:
        if isinstance(device, dict):
            match = walk(device)
            if match:
                return match
    raise LiveInstallError(f"Could not resolve partition labeled {label} on {disk_path}.")


def execute_install_plan(
    plan_payload: PlanContract | dict | None = None,
    *,
    target_disk_path: str = "",
    stage_root: str | Path | None = None,
    dry_run: bool = True,
    encryption_passphrase: str = "",
    user_password: str = "",
    hostname: str = "",
    username: str = "",
    timezone: str = "",
    locale: str = "en_US",
    keyboard_layout: str = "us",
    bootloader: str = DEFAULT_BOOTLOADER,
    crypt_mapper_name: str = DEFAULT_CRYPT_MAPPER_NAME,
    mount_root: str = DEFAULT_MOUNT_ROOT,
    cleanup_after_success: bool = True,
    runner: CommandRunner | None = None,
) -> LiveInstallExecutionResult:
    """Orchestrate Linux partition + encrypted layout + archinstall execution."""
    active_runner = runner or SubprocessCommandRunner()
    root = resolve_live_stage_root(stage_root)
    root.mkdir(parents=True, exist_ok=True)

    staged_files: list[str] = []
    commands: list[str] = []
    plan_contract: PlanContract | None = None

    if plan_payload is not None:
        plan_contract = plan_payload if isinstance(plan_payload, PlanContract) else validate_plan_contract(plan_payload)
        plan_file = stage_live_runtime_artifact(root, "runtime/plan.json", plan_contract.model_dump())
        staged_files.append(str(plan_file))

    install_log_lines: list[str] = ["live install orchestration initialized"]
    target_partition_path = ""
    efi_partition_path = ""
    removed_paths: tuple[str, ...] = tuple()
    status = "staged"
    failed = False

    try:
        if plan_contract is not None:
            try:
                identity = match_machine_identity(plan_contract)
            except MachineIdentityError as exc:
                raise LiveInstallError(str(exc)) from exc

            resolved_disk_path = target_disk_path.strip() or identity.disk.path
            efi_partition_path = identity.efi_partition.path
            start_sector = plan_contract.prepared_free_space_range.start_sector
            end_sector = plan_contract.prepared_free_space_range.end_sector
            partition_size_bytes = plan_contract.prepared_free_space_range.size_bytes

            resolved_hostname = str(plan_contract.user_choices.get("hostname", "")).strip() or hostname.strip()
            resolved_username = str(plan_contract.user_choices.get("username", "")).strip() or username.strip()
            resolved_timezone = str(plan_contract.user_choices.get("timezone", "")).strip() or timezone.strip() or "UTC"
            resolved_locale = str(plan_contract.user_choices.get("locale", "")).strip() or locale.strip() or "en_US"
            resolved_keyboard = str(plan_contract.user_choices.get("kb_layout", "")).strip() or keyboard_layout.strip() or "us"
            resolved_bootloader = str(plan_contract.user_choices.get("bootloader", "")).strip() or bootloader.strip() or DEFAULT_BOOTLOADER

            if not resolved_hostname:
                raise LiveInstallError("hostname is required for config-mode install.")
            if not resolved_username:
                raise LiveInstallError("username is required for config-mode install.")
            if not dry_run and not user_password:
                raise LiveInstallError("user_password is required for config-mode install.")
            if not dry_run and not encryption_passphrase:
                raise LiveInstallError("encryption_passphrase is required for config-mode install.")

            target_partition_path = f"{resolved_disk_path}-planned-partition"
            archinstall_config = _build_archinstall_config(
                target_disk_path=resolved_disk_path,
                efi_partition_path=efi_partition_path,
                target_partition_path=target_partition_path,
                hostname=resolved_hostname,
                username=resolved_username,
                user_password=user_password or "placeholder-password",
                encryption_passphrase=encryption_passphrase or "placeholder-passphrase",
                timezone=resolved_timezone,
                locale=resolved_locale,
                keyboard_layout=resolved_keyboard,
                bootloader=resolved_bootloader,
                wipe_efi=False,
            )
            archinstall_config_path = stage_live_runtime_artifact(
                root,
                "runtime/archinstall-config.json",
                archinstall_config,
            )
            staged_files.append(str(archinstall_config_path))

            command_plan = _build_plan_partition_command_plan(
                target_disk_path=resolved_disk_path,
                start_sector=start_sector,
                end_sector=end_sector,
            )
            commands = [" ".join(command) for command in command_plan]
            commands.append(f"archinstall --config {archinstall_config_path}")
            target_disk_path = resolved_disk_path

            if dry_run:
                install_log_lines.append("dry-run enabled; no destructive commands executed")
                for command in commands:
                    install_log_lines.append(f"DRY-RUN: {command}")
            else:
                try:
                    for command in command_plan:
                        _run_checked(active_runner, command)
                        install_log_lines.append(f"EXECUTED: {' '.join(command)}")

                    target_partition_path = _discover_partition_path(
                        active_runner,
                        disk_path=resolved_disk_path,
                        start_sector=start_sector,
                        expected_size_bytes=partition_size_bytes,
                    )
                    install_log_lines.append(f"resolved target partition: {target_partition_path}")

                    archinstall_config = _build_archinstall_config(
                        target_disk_path=resolved_disk_path,
                        efi_partition_path=efi_partition_path,
                        target_partition_path=target_partition_path,
                        hostname=resolved_hostname,
                        username=resolved_username,
                        user_password=user_password,
                        encryption_passphrase=encryption_passphrase,
                        timezone=resolved_timezone,
                        locale=resolved_locale,
                        keyboard_layout=resolved_keyboard,
                        bootloader=resolved_bootloader,
                        wipe_efi=False,
                    )
                    stage_live_runtime_artifact(root, "runtime/archinstall-config.json", archinstall_config)
                    _run_checked(active_runner, ["archinstall", "--config", str(archinstall_config_path)])
                    install_log_lines.append(f"EXECUTED: archinstall --config {archinstall_config_path}")
                except Exception as exc:
                    install_log_lines.append(f"ERROR: {exc}")
                    raise
        else:
            resolved_disk_path = target_disk_path.strip() or _discover_default_disk(active_runner)
            efi_end_sector, root_start_sector = _standalone_partition_bounds(active_runner, resolved_disk_path)
            command_plan = _build_standalone_command_plan(
                target_disk_path=resolved_disk_path,
                efi_end_sector=efi_end_sector,
                root_start_sector=root_start_sector,
            )
            commands = [" ".join(command) for command in command_plan]
            target_disk_path = resolved_disk_path

            if dry_run:
                install_log_lines.append("dry-run enabled; standalone whole-disk commands staged only")
                for command in commands:
                    install_log_lines.append(f"DRY-RUN: {command}")
                status = "whole-disk-staged"
            else:
                if not hostname.strip():
                    raise LiveInstallError("hostname is required for standalone install.")
                if not username.strip():
                    raise LiveInstallError("username is required for standalone install.")
                if not user_password:
                    raise LiveInstallError("user_password is required for standalone install.")
                if not encryption_passphrase:
                    raise LiveInstallError("encryption_passphrase is required for standalone install.")
                try:
                    for command in command_plan:
                        _run_checked(active_runner, command)
                        install_log_lines.append(f"EXECUTED: {' '.join(command)}")
                    target_partition_path = _find_partition_by_label(
                        active_runner,
                        disk_path=resolved_disk_path,
                        label="OmarchyRoot",
                    )
                    efi_partition_path = _find_partition_by_label(
                        active_runner,
                        disk_path=resolved_disk_path,
                        label="OmarchyEFI",
                    )
                    _run_checked(active_runner, ["mkfs.fat", "-F", "32", efi_partition_path])
                    install_log_lines.append(f"EXECUTED: mkfs.fat -F 32 {efi_partition_path}")
                    archinstall_config = _build_archinstall_config(
                        target_disk_path=resolved_disk_path,
                        efi_partition_path=efi_partition_path,
                        target_partition_path=target_partition_path,
                        hostname=hostname.strip(),
                        username=username.strip(),
                        user_password=user_password,
                        encryption_passphrase=encryption_passphrase,
                        timezone=timezone.strip() or "UTC",
                        locale=locale.strip() or "en_US",
                        keyboard_layout=keyboard_layout.strip() or "us",
                        bootloader=bootloader.strip() or DEFAULT_BOOTLOADER,
                        wipe_efi=False,
                    )
                    archinstall_config_path = stage_live_runtime_artifact(
                        root,
                        "runtime/archinstall-config.json",
                        archinstall_config,
                    )
                    staged_files.append(str(archinstall_config_path))
                    _run_checked(active_runner, ["archinstall", "--config", str(archinstall_config_path)])
                    install_log_lines.append(f"EXECUTED: archinstall --config {archinstall_config_path}")
                    commands.append(f"mkfs.fat -F 32 {efi_partition_path}")
                    commands.append(f"archinstall --config {archinstall_config_path}")
                    status = "whole-disk-installed"
                except Exception as exc:
                    install_log_lines.append(f"ERROR: {exc}")
                    raise

    except Exception:
        failed = True
        status = "failed"
        raise
    finally:
        install_log = stage_live_runtime_artifact(root, "runtime/install.log", "\n".join(install_log_lines) + "\n")
        install_log_path = str(install_log)
        if install_log_path not in staged_files:
            staged_files.append(install_log_path)
        if not failed and cleanup_after_success:
            removed_paths = cleanup_live_stage(root, residual_paths=("runtime/install.log",))
            status = "completed"
        elif not failed:
            removed_paths = tuple()
            status = "staged"

    return LiveInstallExecutionResult(
        status=status,
        stage_root=str(root),
        staged_files=tuple(staged_files),
        removed_paths=removed_paths,
        commands=tuple(commands),
        target_partition_path=target_partition_path,
        efi_partition_path=efi_partition_path,
        target_disk_path=target_disk_path,
        mount_root=mount_root,
        encryption_mapper=f"/dev/mapper/{crypt_mapper_name}",
        dry_run=dry_run,
    )
