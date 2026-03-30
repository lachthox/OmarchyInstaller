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


def test_postinstall_staging_writes_runtime_and_services(
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

    mount_root = tmp_path / "mnt"
    result = install_module.execute_install_plan(
        plan_payload=_plan_payload(),
        stage_root=tmp_path / "stage",
        mount_root=str(mount_root),
        dry_run=False,
        cleanup_after_success=False,
        user_password="user-secret",
        encryption_passphrase="disk-secret",
        runner=runner,
    )

    assert result.status == "installed"

    runtime_root = mount_root / "opt" / "omarchy-setup"
    assert (runtime_root / "setup.sh").exists()
    assert (runtime_root / "main.py").exists()
    assert (runtime_root / "installer").is_dir()
    assert (runtime_root / "requirements.txt").exists()
    assert (runtime_root / "runtime-packages.txt").exists()
    assert (runtime_root / "hooks" / "live-autostart.sh").exists()
    assert (runtime_root / "hooks" / "firstboot-wrapper.sh").exists()
    assert (runtime_root / "build-metadata.json").exists()

    assert (mount_root / "var" / "lib" / "omarchy" / "install" / "install-success.json").exists()
    assert (mount_root / "var" / "lib" / "omarchy" / "boot" / "expected-state.json").exists()

    assert (mount_root / "etc" / "systemd" / "system" / "omarchy-firstboot.service").exists()
    assert (mount_root / "etc" / "systemd" / "system" / "boot-guardian.service").exists()

    assert (mount_root / "usr" / "local" / "bin" / "omarchy-firstboot-wrapper.sh").exists()
    assert (mount_root / "usr" / "local" / "bin" / "omarchy-boot-check").exists()
    assert (mount_root / "usr" / "local" / "bin" / "omarchy-boot-repair").exists()
    assert (mount_root / "usr" / "local" / "bin" / "omarchy-boot-guardian").exists()

    assert ["arch-chroot", str(mount_root), "systemctl", "enable", "omarchy-firstboot.service"] in runner.calls
    assert ["arch-chroot", str(mount_root), "systemctl", "enable", "boot-guardian.service"] in runner.calls


def test_postinstall_staging_failures_abort_install(
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

    mount_root_file = tmp_path / "mnt-file"
    mount_root_file.write_text("not-a-directory", encoding="utf-8")

    with pytest.raises(install_module.LiveInstallError, match="Post-install staging failed"):
        install_module.execute_install_plan(
            plan_payload=_plan_payload(),
            stage_root=tmp_path / "stage",
            mount_root=str(mount_root_file),
            dry_run=False,
            cleanup_after_success=False,
            user_password="user-secret",
            encryption_passphrase="disk-secret",
            runner=runner,
        )
