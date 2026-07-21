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


DEFAULT_LIVE_STAGE_ROOT = Path(gettempdir()) / "omarchy-live-install"
DEFAULT_CRYPT_MAPPER_NAME = "omarchy-cryptroot"
DEFAULT_MOUNT_ROOT = "/mnt"


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


def _build_archinstall_config(
    plan: PlanContract,
    *,
    target_disk_path: str,
    target_partition_path: str,
    crypt_mapper_name: str,
    mount_root: str,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0.0",
        "source": "omarchy-live-orchestrator",
        "hostname": plan.user_choices.hostname,
        "username": plan.user_choices.username,
        "timezone": plan.user_choices.timezone,
        "locale": plan.user_choices.locale,
        "target": {
            "disk_path": target_disk_path,
            "partition_path": target_partition_path,
            "partition_start_sector": plan.prepared_free_space_range.start_sector,
            "partition_end_sector": plan.prepared_free_space_range.end_sector,
            "partition_size_bytes": plan.prepared_free_space_range.size_bytes,
        },
        "layout": {
            "encryption": {
                "required": True,
                "luks_type": "luks2",
                "mapper_name": crypt_mapper_name,
            },
            "filesystem": "btrfs",
            "mount_root": mount_root,
            "bootloader_policy": "limine",
        },
    }


def _build_install_command_plan(
    *,
    target_disk_path: str,
    start_sector: int,
    end_sector: int,
    target_partition_path: str,
    crypt_mapper_name: str,
    mount_root: str,
    archinstall_config_path: Path,
) -> list[list[str]]:
    mapper_path = f"/dev/mapper/{crypt_mapper_name}"
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
        ["cryptsetup", "luksFormat", "--type", "luks2", "--batch-mode", "--key-file", "-", target_partition_path],
        ["cryptsetup", "open", "--key-file", "-", target_partition_path, crypt_mapper_name],
        ["mkfs.btrfs", "-f", mapper_path],
        ["mount", mapper_path, mount_root],
        ["archinstall", "--config", str(archinstall_config_path)],
    ]


def execute_install_plan(
    plan_payload: PlanContract | dict | None = None,
    *,
    target_disk_path: str = "",
    stage_root: str | Path | None = None,
    dry_run: bool = True,
    encryption_passphrase: str = "",
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
    removed_paths: tuple[str, ...] = tuple()
    status = "staged"
    failed = False

    try:
        if plan_contract is not None:
            if not target_disk_path.strip():
                raise LiveInstallError("target_disk_path is required when plan_payload is provided.")

            start_sector = plan_contract.prepared_free_space_range.start_sector
            end_sector = plan_contract.prepared_free_space_range.end_sector
            partition_size_bytes = plan_contract.prepared_free_space_range.size_bytes

            target_partition_path = f"{target_disk_path}-planned-partition"
            archinstall_config = _build_archinstall_config(
                plan_contract,
                target_disk_path=target_disk_path,
                target_partition_path=target_partition_path,
                crypt_mapper_name=crypt_mapper_name,
                mount_root=mount_root,
            )
            archinstall_config_path = stage_live_runtime_artifact(
                root,
                "runtime/archinstall-config.json",
                archinstall_config,
            )
            staged_files.append(str(archinstall_config_path))

            command_plan = _build_install_command_plan(
                target_disk_path=target_disk_path,
                start_sector=start_sector,
                end_sector=end_sector,
                target_partition_path=target_partition_path,
                crypt_mapper_name=crypt_mapper_name,
                mount_root=mount_root,
                archinstall_config_path=archinstall_config_path,
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
                mounted_target = False
                try:
                    # Execute partition creation first, then resolve created partition path exactly.
                    for command in command_plan[:3]:
                        _run_checked(active_runner, command)
                        install_log_lines.append(f"EXECUTED: {' '.join(command)}")

                    target_partition_path = _discover_partition_path(
                        active_runner,
                        disk_path=target_disk_path,
                        start_sector=start_sector,
                        expected_size_bytes=partition_size_bytes,
                    )
                    install_log_lines.append(f"resolved target partition: {target_partition_path}")

                    # Rebuild archinstall config and command plan with concrete partition path.
                    archinstall_config = _build_archinstall_config(
                        plan_contract,
                        target_disk_path=target_disk_path,
                        target_partition_path=target_partition_path,
                        crypt_mapper_name=crypt_mapper_name,
                        mount_root=mount_root,
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
                    )
                    commands = [" ".join(command) for command in command_plan]

                    for index, command in enumerate(command_plan[3:], start=4):
                        if index in (4, 5):
                            _run_checked(active_runner, command, input_text=encryption_passphrase + "\n")
                        else:
                            _run_checked(active_runner, command)
                        if index == 5:
                            mapper_opened = True
                        elif index == 7:
                            mounted_target = True
                        install_log_lines.append(f"EXECUTED: {' '.join(command)}")
                except Exception as exc:
                    if mounted_target:
                        _run_cleanup_best_effort(active_runner, ["umount", mount_root], install_log_lines)
                    if mapper_opened:
                        _run_cleanup_best_effort(active_runner, ["cryptsetup", "close", crypt_mapper_name], install_log_lines)
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
        mount_root=mount_root,
        encryption_mapper=f"/dev/mapper/{crypt_mapper_name}",
        dry_run=dry_run,
    )
