from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import subprocess

import pytest

try:
    from rebuild.installer.platforms.linux_live import install as install_module
except ModuleNotFoundError:  # pragma: no cover - fallback for package-local test runs
    from installer.platforms.linux_live import install as install_module


class _Runner:
    def __init__(self, responses: dict[str, subprocess.CompletedProcess[str]]) -> None:
        self.responses = responses
        self.calls: list[list[str]] = []

    def run(self, command: list[str], input_text: str | None = None) -> subprocess.CompletedProcess[str]:
        del input_text
        self.calls.append(command)
        key = " ".join(command)
        if key in self.responses:
            return self.responses[key]
        return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")


def _ok(command: list[str], stdout: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=command, returncode=0, stdout=stdout, stderr="")


def _plan_payload() -> dict[str, object]:
    return {
        "meta": {
            "schema_version": "0.1.0",
            "producer_version": "0.1.0-dev",
            "generated_at_utc": "2026-03-30T00:00:00Z",
            "build_commit": "",
            "release_tag": "",
        },
        "disk_identity": {
            "disk_serial": "SER-001",
            "disk_model": "TestDisk",
            "disk_size_bytes": 512000000000,
            "gpt_disk_guid": "GUID-001",
            "partition_style": "GPT",
        },
        "efi_identity": {
            "partition_guid": "EFI-GUID-001",
            "partuuid": "EFI-PARTUUID-001",
            "filesystem": "vfat",
            "start_sector": 2048,
            "end_sector": 4095,
            "size_bytes": 1048576,
        },
        "windows_partition_identity": {
            "partition_guid": "WIN-GUID-001",
            "partuuid": "WIN-PARTUUID-001",
            "filesystem": "ntfs",
            "start_sector": 4096,
            "end_sector": 999999,
            "size_bytes": 200000000000,
        },
        "prepared_free_space_range": {
            "start_sector": 4096,
            "end_sector": 8191,
            "size_bytes": 2097152,
        },
        "user_choices": {
            "hostname": "omarchy-test",
            "username": "tester",
            "timezone": "UTC",
            "locale": "en_US",
            "kb_layout": "us",
            "bootloader": "limine",
        },
        "network": None,
        "omarchy_assumptions": {},
        "compatibility": {
            "schema_version": "0.1.0",
            "minimum_windows_prep_version": "0.1.0",
            "minimum_live_runtime_version": "0.1.0",
            "required_plan_schema_version": "0.1.0",
            "bootstrap_expectation": "post-install-only",
            "ventoy_handoff_path": "omarchy/plan.json",
        },
    }


def test_execute_install_plan_config_mode_runs_successfully(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    lsblk_payload = {
        "blockdevices": [
            {
                "type": "disk",
                "children": [
                    {
                        "type": "part",
                        "pkname": "sda",
                        "start": "4096",
                        "size": "2097152",
                        "path": "/dev/sda3",
                    }
                ],
            }
        ]
    }
    responses = {
        "lsblk -b -J -o PATH,TYPE,START,SIZE,PKNAME": _ok(
            ["lsblk", "-b", "-J", "-o", "PATH,TYPE,START,SIZE,PKNAME"],
            stdout=json.dumps(lsblk_payload),
        ),
    }
    runner = _Runner(responses)
    monkeypatch.setattr(
        install_module,
        "match_machine_identity",
        lambda _plan: SimpleNamespace(
            disk=SimpleNamespace(path="/dev/sda"),
            efi_partition=SimpleNamespace(path="/dev/sda1"),
        ),
    )

    result = install_module.execute_install_plan(
        plan_payload=_plan_payload(),
        stage_root=tmp_path,
        dry_run=False,
        cleanup_after_success=False,
        user_password="user-secret",
        encryption_passphrase="disk-secret",
        runner=runner,
    )

    assert result.status == "installed"
    assert result.target_disk_path == "/dev/sda"
    assert result.efi_partition_path == "/dev/sda1"
    assert result.target_partition_path == "/dev/sda3"
    assert any(command[0] == "archinstall" for command in runner.calls)
    assert any(command[0] == "sgdisk" for command in runner.calls)
    assert Path(result.stage_root).exists()


def test_execute_install_plan_standalone_mode_runs_successfully(tmp_path: Path) -> None:
    lsblk_disks_payload = {
        "blockdevices": [
            {
                "path": "/dev/sda",
                "type": "disk",
                "size": "120000000000",
                "rm": "0",
                "hotplug": "0",
                "model": "PrimaryDisk",
            },
            {
                "path": "/dev/sdb",
                "type": "disk",
                "size": "32000000000",
                "rm": "1",
                "hotplug": "1",
                "model": "USB",
            },
        ]
    }
    lsblk_labels_payload = {
        "blockdevices": [
            {
                "type": "disk",
                "children": [
                    {
                        "type": "part",
                        "pkname": "sda",
                        "partlabel": "OmarchyEFI",
                        "path": "/dev/sda1",
                    },
                    {
                        "type": "part",
                        "pkname": "sda",
                        "partlabel": "OmarchyRoot",
                        "path": "/dev/sda2",
                    },
                ],
            }
        ]
    }
    responses = {
        "lsblk -b -J -o PATH,TYPE,SIZE,RM,HOTPLUG,MODEL": _ok(
            ["lsblk", "-b", "-J", "-o", "PATH,TYPE,SIZE,RM,HOTPLUG,MODEL"],
            stdout=json.dumps(lsblk_disks_payload),
        ),
        "blockdev --getss /dev/sda": _ok(["blockdev", "--getss", "/dev/sda"], stdout="512\n"),
        "blockdev --getsz /dev/sda": _ok(["blockdev", "--getsz", "/dev/sda"], stdout="200000000\n"),
        "lsblk -J -o PATH,TYPE,PARTLABEL,PKNAME": _ok(
            ["lsblk", "-J", "-o", "PATH,TYPE,PARTLABEL,PKNAME"],
            stdout=json.dumps(lsblk_labels_payload),
        ),
    }
    runner = _Runner(responses)

    result = install_module.execute_install_plan(
        stage_root=tmp_path,
        dry_run=False,
        cleanup_after_success=False,
        hostname="omarchy-standalone",
        username="standalone",
        timezone="UTC",
        locale="en_US",
        keyboard_layout="us",
        user_password="user-secret",
        encryption_passphrase="disk-secret",
        runner=runner,
    )

    assert result.status == "whole-disk-installed"
    assert result.target_disk_path == "/dev/sda"
    assert result.efi_partition_path == "/dev/sda1"
    assert result.target_partition_path == "/dev/sda2"
    assert any(command[:3] == ["mkfs.fat", "-F", "32"] for command in runner.calls)
    assert any(command[0] == "archinstall" for command in runner.calls)
    assert Path(result.stage_root).exists()


def test_build_archinstall_config_mounts_esp_to_boot_efi() -> None:
    config = install_module._build_archinstall_config(
        target_disk_path="/dev/sda",
        efi_partition_path="/dev/sda1",
        target_partition_path="/dev/sda2",
        hostname="omarchy",
        username="tester",
        user_password="secret",
        encryption_passphrase="secret",
        timezone="UTC",
        locale="en_US",
        keyboard_layout="us",
        bootloader="limine",
        wipe_efi=False,
    )
    efi_partition = config["disk_config"]["device_modifications"][0]["partitions"][0]
    assert efi_partition["mountpoint"] == "/boot/efi"


def test_invalid_bootloader_is_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    plan = _plan_payload()
    user_choices = dict(plan["user_choices"])
    user_choices["bootloader"] = "grub"
    plan["user_choices"] = user_choices

    monkeypatch.setattr(
        install_module,
        "match_machine_identity",
        lambda _plan: SimpleNamespace(
            disk=SimpleNamespace(path="/dev/sda"),
            efi_partition=SimpleNamespace(path="/dev/sda1"),
        ),
    )

    with pytest.raises(install_module.LiveInstallError, match="Unsupported bootloader"):
        install_module.execute_install_plan(
            plan_payload=plan,
            stage_root=tmp_path,
            dry_run=True,
            cleanup_after_success=False,
        )
