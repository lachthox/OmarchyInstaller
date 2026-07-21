"""Production install orchestration for the Arch live environment."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
import subprocess
import shutil
import time
from tempfile import gettempdir
from typing import Any, Protocol
from uuid import uuid4

from ...shared import PlanContract, validate_plan_contract
from .archinstall_contract import (
    ARCHINSTALL_MOUNTPOINT,
    build_archinstall_config,
    build_archinstall_credentials,
    validate_archinstall_files,
)


DEFAULT_LIVE_STAGE_ROOT = Path(gettempdir()) / "omarchy-live-install"
DEFAULT_CRYPT_MAPPER_NAME = "omarchy-cryptroot"
DEFAULT_MOUNT_ROOT = ARCHINSTALL_MOUNTPOINT


class LiveInstallError(RuntimeError):
    """Raised when live install staging cannot be managed safely."""


class CommandRunner(Protocol):
    """Minimal command runner protocol for deterministic stubs."""

    def run(self, command: list[str], input_text: str | None = None) -> subprocess.CompletedProcess[str]: ...


class SubprocessCommandRunner:
    """Default command runner backed by subprocess.

    `archinstall` itself allocates a pseudo-terminal internally (its
    `SysCommandWorker` uses `pty.fork()`, and its `--silent` execution path
    runs steps under `systemd-run --pty`); invoked with plain captured pipes
    and no controlling terminal at all, that inner pty/systemd-run setup
    fails immediately. Every other command in the install plan works fine
    without one, so only the `archinstall` invocation is given a real pty.
    """

    def run(self, command: list[str], input_text: str | None = None) -> subprocess.CompletedProcess[str]:
        if command and command[0] == "archinstall":
            return _run_with_pty(command)
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            input=input_text,
            check=False,
        )


def _run_with_pty(command: list[str]) -> subprocess.CompletedProcess[str]:
    import os
    import pty

    master_fd, slave_fd = pty.openpty()
    try:
        process = subprocess.Popen(  # noqa: S603 - command list is built internally, not from user input
            command,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            close_fds=True,
        )
        os.close(slave_fd)
        slave_fd = -1
        output = bytearray()
        while True:
            try:
                chunk = os.read(master_fd, 65536)
            except OSError:
                break
            if not chunk:
                break
            output.extend(chunk)
        returncode = process.wait()
    finally:
        if slave_fd != -1:
            os.close(slave_fd)
        os.close(master_fd)
    text = output.decode("utf-8", errors="replace")
    return subprocess.CompletedProcess(command, returncode, stdout=text, stderr="")


@dataclass(frozen=True, slots=True)
class LiveInstallExecutionResult:
    status: str
    stage_root: str
    staged_files: tuple[str, ...]
    removed_paths: tuple[str, ...]
    commands: tuple[str, ...]
    target_partition_path: str
    target_partition_start_sector: int
    target_partition_end_sector: int
    target_partition_size_bytes: int
    target_partition_guid: str
    mount_root: str
    encryption_mapper: str
    target_finalization_status: str
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


@dataclass(frozen=True, slots=True)
class CreatedPartition:
    path: str
    start_sector: int
    end_sector: int
    size_bytes: int
    partuuid: str


def _discover_partition(
    runner: CommandRunner,
    *,
    disk_path: str,
    logical_sector_size: int,
) -> CreatedPartition:
    output = _run_checked(
        runner,
        [
            "lsblk",
            "-b",
            "-J",
            "-o",
            "PATH,TYPE,START,SIZE,PKNAME,PARTLABEL,PARTUUID",
        ],
    )
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as exc:
        raise LiveInstallError(f"Invalid lsblk JSON while discovering partition: {exc}") from exc

    disk_name = Path(disk_path).name
    candidates: list[CreatedPartition] = []
    for partition in _parse_lsblk_partitions(payload):
        pkname = str(partition.get("pkname", "")).strip()
        if pkname != disk_name:
            continue
        try:
            part_start = int(str(partition.get("start", "0")).strip())
            part_size = int(str(partition.get("size", "0")).strip())
        except ValueError:
            continue
        if str(partition.get("partlabel", "")).strip() == "omarchy-linux":
            path = str(partition.get("path", "")).strip()
            if path:
                sectors = (part_size + logical_sector_size - 1) // logical_sector_size
                candidates.append(
                    CreatedPartition(
                        path=path,
                        start_sector=part_start,
                        end_sector=part_start + sectors - 1,
                        size_bytes=part_size,
                        partuuid=str(partition.get("partuuid", "")).strip(),
                    )
                )

    if not candidates:
        raise LiveInstallError("Could not resolve newly created Linux partition path after sgdisk.")
    if len(candidates) > 1:
        raise LiveInstallError("Linux partition discovery is ambiguous after sgdisk.")
    created = candidates[0]
    if not created.partuuid:
        raise LiveInstallError("New Linux partition is missing its actual PARTUUID.")
    return created


def _assert_planned_extent_is_still_free(
    runner: CommandRunner,
    *,
    disk_path: str,
    start_sector: int,
    end_sector: int,
    logical_sector_size: int,
) -> dict[str, Any]:
    gpt = _run_checked(runner, ["sgdisk", "--print", disk_path])
    match = re.search(
        r"First usable sector is\s+(\d+), last usable sector is\s+(\d+)", gpt, re.IGNORECASE
    )
    if not match:
        raise LiveInstallError("sgdisk omitted authoritative GPT usable-sector bounds.")
    first_usable, last_usable = int(match.group(1)), int(match.group(2))
    if start_sector < first_usable or end_sector > last_usable:
        raise LiveInstallError("Planned extent overlaps reserved GPT metadata sectors.")

    output = _run_checked(runner, ["lsblk", "-b", "-J", "-o", "PATH,TYPE,START,SIZE,PKNAME"])
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as exc:
        raise LiveInstallError(f"Invalid lsblk JSON while revalidating free space: {exc}") from exc
    disk_name = Path(disk_path).name
    for partition in _parse_lsblk_partitions(payload):
        if str(partition.get("pkname", "")).strip() != disk_name:
            continue
        part_start = int(str(partition.get("start", "0")))
        part_size = int(str(partition.get("size", "0")))
        part_sectors = (part_size + logical_sector_size - 1) // logical_sector_size
        part_end = part_start + part_sectors - 1
        if not (end_sector < part_start or start_sector > part_end):
            raise LiveInstallError("Planned free-space extent is no longer free.")
    return {
        "disk_path": disk_path,
        "planned_start_sector": start_sector,
        "planned_end_sector": end_sector,
        "logical_sector_size": logical_sector_size,
        "sgdisk_print": gpt,
        "lsblk": payload,
    }


def _build_archinstall_config(
    plan: PlanContract,
) -> dict[str, Any]:
    return build_archinstall_config(plan).model_dump(mode="json", by_alias=True, exclude_none=True)


def _build_install_command_plan(
    *,
    target_disk_path: str,
    start_sector: int,
    end_sector: int,
    target_partition_path: str,
    crypt_mapper_name: str,
    mount_root: str,
    archinstall_config_path: Path,
    archinstall_credentials_path: Path,
    efi_partition_path: str,
    subvolumes: tuple[tuple[str, str, tuple[str, ...]], ...],
    gpt_backup_path: Path,
) -> list[list[str]]:
    mapper_path = f"/dev/mapper/{crypt_mapper_name}"
    commands = [
        ["sgdisk", f"--backup={gpt_backup_path}", target_disk_path],
        [
            "sgdisk",
            f"--new=0:{start_sector}:{end_sector}",
            "--typecode=0:8300",
            "--change-name=0:omarchy-linux",
            target_disk_path,
        ],
        ["partprobe", target_disk_path],
        ["udevadm", "settle"],
        ["cryptsetup", "luksFormat", "--type", "luks2", "--batch-mode", "--key-file", "-", target_partition_path],
        ["cryptsetup", "open", "--key-file", "-", target_partition_path, crypt_mapper_name],
        ["mkfs.btrfs", "-f", mapper_path],
        ["mkdir", "-p", mount_root],
        ["mount", mapper_path, mount_root],
    ]
    commands.extend(["btrfs", "subvolume", "create", f"{mount_root}/{name}"] for name, _, _ in subvolumes)
    commands.append(["umount", mount_root])
    root = next(item for item in subvolumes if item[1] == "/")
    commands.append(["mount", "-o", ",".join((f"subvol={root[0]}", *root[2])), mapper_path, mount_root])
    for name, relative_mount, options in subvolumes:
        if relative_mount == "/":
            continue
        target = f"{mount_root}{relative_mount}"
        commands.append(["mkdir", "-p", target])
        commands.append(["mount", "-o", ",".join((f"subvol={name}", *options)), mapper_path, target])
    esp_target = f"{mount_root}/boot"
    commands.extend(
        [
            ["mkdir", "-p", esp_target],
            ["mount", "-o", "umask=0077", efi_partition_path, esp_target],
            [
                "archinstall",
                "--config",
                str(archinstall_config_path),
                "--creds",
                str(archinstall_credentials_path),
                "--silent",
                "--mountpoint",
                mount_root,
            ],
            [
                "arch-chroot",
                mount_root,
                "/usr/bin/bash",
                "-c",
                "mkdir -p /etc/mkinitcpio.conf.d && printf '%s\\n' "
                "'MODULES=(btrfs)' "
                "'HOOKS=(base systemd autodetect microcode modconf kms keyboard "
                "sd-vconsole block sd-encrypt filesystems fsck)' "
                "> /etc/mkinitcpio.conf.d/omarchy.conf",
            ],
            ["arch-chroot", mount_root, "mkinitcpio", "-P"],
            [
                "bash",
                "-c",
                "set -euo pipefail; "
                f"luks_uuid=$(blkid -s UUID -o value {target_partition_path}); "
                f"mkdir -p {mount_root}/boot/EFI/BOOT; "
                f"cp {mount_root}/usr/share/limine/BOOTX64.EFI {mount_root}/boot/EFI/BOOT/BOOTX64.EFI; "
                f"cat > {mount_root}/boot/limine.conf <<LIMINECONF\n"
                "timeout: 5\n\n"
                "/Arch Linux\n"
                "    protocol: linux\n"
                "    kernel_path: boot():/vmlinuz-linux\n"
                f"    kernel_cmdline: rd.luks.name=$luks_uuid={crypt_mapper_name} "
                f"root=/dev/mapper/{crypt_mapper_name} rootflags=subvol=@ rw quiet\n"
                "    module_path: boot():/initramfs-linux.img\n"
                "LIMINECONF\n"
                f"arch-chroot {mount_root} efibootmgr --create --disk {target_disk_path} "
                "--part 1 --loader '\\EFI\\BOOT\\BOOTX64.EFI' --label Limine || true",
            ],
        ]
    )
    return commands


def execute_install_plan(
    plan_payload: PlanContract | dict | None = None,
    *,
    target_disk_path: str = "",
    stage_root: str | Path | None = None,
    dry_run: bool = True,
    encryption_passphrase: str = "",
    user_password_hash: str = "",
    efi_partition_path: str = "",
    crypt_mapper_name: str = DEFAULT_CRYPT_MAPPER_NAME,
    mount_root: str = DEFAULT_MOUNT_ROOT,
    cleanup_after_success: bool = False,
    finalize_target: bool = True,
    runner: CommandRunner | None = None,
) -> LiveInstallExecutionResult:
    """Orchestrate Linux partition + encrypted layout + archinstall execution."""
    if plan_payload is None:
        raise LiveInstallError("A validated plan_payload is required.")
    active_runner = runner or SubprocessCommandRunner()
    root = resolve_live_stage_root(stage_root)
    root.mkdir(parents=True, exist_ok=True)

    staged_files: list[str] = []
    commands: list[str] = []
    plan_contract = plan_payload if isinstance(plan_payload, PlanContract) else validate_plan_contract(plan_payload)
    plan_file = stage_live_runtime_artifact(root, "runtime/plan.json", plan_contract.model_dump(mode="json"))
    staged_files.append(str(plan_file))

    install_log_lines: list[str] = ["live install orchestration initialized"]
    target_partition_path = ""
    target_partition_start_sector = 0
    target_partition_end_sector = 0
    target_partition_size_bytes = 0
    target_partition_guid = ""
    removed_paths: tuple[str, ...] = tuple()
    status = "staged"
    target_finalization_status = "simulated" if dry_run else "not-run"
    failed = False

    try:
        if plan_contract is not None:
            if not target_disk_path.strip():
                raise LiveInstallError("target_disk_path is required when plan_payload is provided.")

            start_sector = plan_contract.prepared_free_space_range.start_sector
            end_sector = plan_contract.prepared_free_space_range.end_sector
            target_partition_path = f"{target_disk_path}-planned-partition"
            archinstall_config = _build_archinstall_config(
                plan_contract,
            )
            archinstall_config_path = stage_live_runtime_artifact(
                root,
                "runtime/archinstall-config.json",
                archinstall_config,
            )
            staged_files.append(str(archinstall_config_path))
            if not user_password_hash:
                user_password_hash = "$6$simulation$not-a-real-password-hash" if dry_run else ""
            if not user_password_hash:
                raise LiveInstallError("A crypt-format user_password_hash is required for real installation.")
            credentials = build_archinstall_credentials(
                plan_contract, user_password_hash=user_password_hash
            ).model_dump(mode="json")
            credentials_path = stage_live_runtime_artifact(
                root, "runtime/archinstall-credentials.json", credentials
            )
            credentials_path.chmod(0o600)
            staged_files.append(str(credentials_path))
            validate_archinstall_files(archinstall_config_path, credentials_path)
            if not efi_partition_path:
                efi_partition_path = "/dev/planned-esp" if dry_run else ""
            if not efi_partition_path:
                raise LiveInstallError("efi_partition_path is required for real installation.")

            subvolumes = tuple(
                (item.name, item.mountpoint, item.mount_options)
                for item in plan_contract.user_choices.filesystem.subvolumes
            )
            gpt_backup_path = root / "runtime" / "gpt-before.bin"

            command_plan = _build_install_command_plan(
                target_disk_path=target_disk_path,
                start_sector=start_sector,
                end_sector=end_sector,
                target_partition_path=target_partition_path,
                crypt_mapper_name=crypt_mapper_name,
                mount_root=mount_root,
                archinstall_config_path=archinstall_config_path,
                archinstall_credentials_path=credentials_path,
                efi_partition_path=efi_partition_path,
                subvolumes=subvolumes,
                gpt_backup_path=gpt_backup_path,
            )
            commands = [" ".join(command) for command in command_plan]

            if dry_run:
                install_log_lines.append("dry-run enabled; no destructive commands executed")
                for display_command in commands:
                    install_log_lines.append(f"DRY-RUN: {display_command}")
            else:
                if not encryption_passphrase:
                    raise LiveInstallError("encryption_passphrase is required when dry_run is False.")

                mapper_opened = False
                mounted_targets: list[str] = []
                try:
                    pre_partition_snapshot = _assert_planned_extent_is_still_free(
                        active_runner,
                        disk_path=target_disk_path,
                        start_sector=start_sector,
                        end_sector=end_sector,
                        logical_sector_size=plan_contract.disk_identity.logical_sector_size,
                    )
                    snapshot_path = stage_live_runtime_artifact(
                        root,
                        "runtime/pre-partition-snapshot.json",
                        pre_partition_snapshot,
                    )
                    staged_files.append(str(snapshot_path))
                    # Execute partition creation first, then resolve created partition path exactly.
                    for command in command_plan[:4]:
                        _run_checked(active_runner, command)
                        install_log_lines.append(f"EXECUTED: {' '.join(command)}")
                    if not gpt_backup_path.exists() or gpt_backup_path.stat().st_size == 0:
                        raise LiveInstallError("sgdisk GPT backup was not created before partition changes.")
                    staged_files.append(str(gpt_backup_path))

                    created_partition = _discover_partition(
                        active_runner,
                        disk_path=target_disk_path,
                        logical_sector_size=plan_contract.disk_identity.logical_sector_size,
                    )
                    target_partition_path = created_partition.path
                    target_partition_start_sector = created_partition.start_sector
                    target_partition_end_sector = created_partition.end_sector
                    target_partition_size_bytes = created_partition.size_bytes
                    target_partition_guid = created_partition.partuuid
                    install_log_lines.append(f"resolved target partition: {target_partition_path}")
                    install_log_lines.append(
                        "actual target geometry: "
                        f"{target_partition_start_sector}-{target_partition_end_sector} "
                        f"size={target_partition_size_bytes} partuuid={target_partition_guid}"
                    )

                    # Rebuild archinstall config and command plan with concrete partition path.
                    archinstall_config = _build_archinstall_config(
                        plan_contract,
                    )
                    stage_live_runtime_artifact(root, "runtime/archinstall-config.json", archinstall_config)
                    command_plan = _build_install_command_plan(
                        target_disk_path=target_disk_path,
                        start_sector=start_sector,
                        end_sector=end_sector,
                        target_partition_path=target_partition_path,
                        crypt_mapper_name=crypt_mapper_name,
                        mount_root=mount_root,
                        archinstall_config_path=archinstall_config_path,
                        archinstall_credentials_path=credentials_path,
                        efi_partition_path=efi_partition_path,
                        subvolumes=subvolumes,
                        gpt_backup_path=gpt_backup_path,
                    )
                    commands = [" ".join(command) for command in command_plan]

                    for command in command_plan[4:]:
                        if command[:2] in (["cryptsetup", "luksFormat"], ["cryptsetup", "open"]):
                            _run_checked(active_runner, command, input_text=encryption_passphrase + "\n")
                        else:
                            _run_checked(active_runner, command)
                        if command[:2] == ["cryptsetup", "open"]:
                            mapper_opened = True
                        elif command and command[0] == "mount":
                            mounted_targets.append(command[-1])
                        install_log_lines.append(f"EXECUTED: {' '.join(command)}")
                    if finalize_target:
                        from ..installed_system.target_finalize import (
                            TargetMachineState,
                            finalize_target_system,
                        )
                        luks_uuid = _run_checked(
                            active_runner,
                            ["blkid", "-s", "UUID", "-o", "value", target_partition_path],
                        ).strip()
                        root_fs_uuid = _run_checked(
                            active_runner,
                            ["blkid", "-s", "UUID", "-o", "value", f"/dev/mapper/{crypt_mapper_name}"],
                        ).strip()
                        if not luks_uuid or not root_fs_uuid:
                            raise LiveInstallError("Unable to resolve target LUKS/Btrfs UUIDs for finalization.")
                        crypttab = (
                            f"{crypt_mapper_name} UUID={luks_uuid} none luks\n"
                        )
                        crypttab_path = Path(mount_root) / "etc" / "crypttab.initramfs"
                        crypttab_path.parent.mkdir(parents=True, exist_ok=True)
                        crypttab_path.write_text(crypttab, encoding="utf-8")
                        _run_checked(active_runner, ["arch-chroot", mount_root, "mkinitcpio", "-P"])
                        finalization = finalize_target_system(
                            mount_root,
                            TargetMachineState(
                                username=plan_contract.user_choices.username,
                                disk_guid=plan_contract.disk_identity.gpt_disk_guid,
                                root_partuuid=target_partition_guid,
                                root_fs_uuid=root_fs_uuid,
                                luks_uuid=luks_uuid,
                                mapper_name=crypt_mapper_name,
                                efi_mount=plan_contract.user_choices.filesystem.esp_mountpoint,
                                efi_filesystem_uuid=plan_contract.efi_identity.filesystem_uuid,
                                efi_partuuid=plan_contract.efi_identity.partuuid,
                                bootstrap_url=plan_contract.omarchy_assumptions.bootstrap_url,
                                expected_sha256=plan_contract.omarchy_assumptions.expected_sha256,
                                upstream_version=plan_contract.omarchy_assumptions.upstream_version,
                                release_tag=plan_contract.provenance.release_tag,
                                build_commit=plan_contract.provenance.build_commit,
                            ),
                            runner=active_runner,
                        )
                        install_log_lines.append(
                            f"target finalization: {finalization.status}; marker={finalization.success_marker}"
                        )
                        target_finalization_status = finalization.status
                    # Best-effort, not `_run_checked`: cleanup must be
                    # idempotent against a target that's already unmounted
                    # (e.g. finalize_target_system's own arch-chroot calls
                    # transiently bind/unbind /dev, /proc, /sys, /run inside
                    # the same tree) -- a harmless already-clean state must
                    # never discard an otherwise fully successful install.
                    for mounted in reversed(mounted_targets):
                        _run_cleanup_best_effort(active_runner, ["umount", mounted], install_log_lines)
                    mounted_targets.clear()
                    mapper_close_ok = False
                    for attempt in range(5):
                        completed = active_runner.run(["cryptsetup", "close", crypt_mapper_name])
                        if completed.returncode == 0:
                            install_log_lines.append(f"CLEANUP: cryptsetup close {crypt_mapper_name}")
                            mapper_close_ok = True
                            break
                        if attempt < 4:
                            time.sleep(1)
                    if not mapper_close_ok:
                        install_log_lines.append(
                            f"CLEANUP-FAILED: cryptsetup close {crypt_mapper_name} -> device remained busy"
                        )
                    mapper_opened = not mapper_close_ok
                except Exception as exc:
                    for mounted in reversed(mounted_targets):
                        _run_cleanup_best_effort(active_runner, ["umount", mounted], install_log_lines)
                    if mapper_opened:
                        _run_cleanup_best_effort(active_runner, ["cryptsetup", "close", crypt_mapper_name], install_log_lines)
                    install_log_lines.append(f"ERROR: {exc}")
                    raise

    except Exception:
        failed = True
        status = "failed"
        raise
    finally:
        credentials_candidate = root / "runtime" / "archinstall-credentials.json"
        if credentials_candidate.exists():
            credentials_candidate.unlink()
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
        target_partition_start_sector=target_partition_start_sector,
        target_partition_end_sector=target_partition_end_sector,
        target_partition_size_bytes=target_partition_size_bytes,
        target_partition_guid=target_partition_guid,
        mount_root=mount_root,
        encryption_mapper=f"/dev/mapper/{crypt_mapper_name}",
        target_finalization_status=target_finalization_status,
        dry_run=dry_run,
    )
