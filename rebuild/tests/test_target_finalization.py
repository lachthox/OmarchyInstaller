from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from rebuild.installer.platforms.installed_system.target_finalize import (
    TargetFinalizationError,
    TargetMachineState,
    deploy_target_assets,
    finalize_target_system,
    validate_target_root,
)


REBUILD_ROOT = Path(__file__).resolve().parents[1]


class FinalizeRunner:
    def __init__(self, returncode: int = 0) -> None:
        self.returncode = returncode
        self.commands: list[list[str]] = []

    def run(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        return subprocess.CompletedProcess(command, self.returncode, "", "invalid target")


def machine() -> TargetMachineState:
    return TargetMachineState(
        username="alice",
        disk_guid="00000000-0000-4000-8000-000000000010",
        root_partuuid="00000000-0000-4000-8000-000000000099",
        root_fs_uuid="11111111-2222-3333-4444-555555555555",
        luks_uuid="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    )


def prepare_base_target(root: Path, *, include_windows: bool = True) -> None:
    files = {
        "boot/vmlinuz-linux": "kernel",
        "boot/initramfs-linux.img": "initramfs",
        "boot/EFI/Limine/BOOTX64.EFI": "limine",
        "boot/limine.conf": "timeout: 5",
        "etc/fstab": "UUID=root / btrfs rw 0 0\nUUID=esp /boot vfat rw 0 2\n",
        "etc/crypttab.initramfs": f"omarchy-cryptroot UUID={machine().luks_uuid} none luks\n",
        "etc/mkinitcpio.conf.d/omarchy.conf": "MODULES=(btrfs)\nHOOKS=(base systemd sd-encrypt filesystems)\n",
        "etc/passwd": "root:x:0:0:root:/root:/bin/bash\nalice:x:1000:1000::/home/alice:/bin/bash\n",
        "etc/group": "wheel:x:998:alice\nalice:x:1000:\n",
        "etc/sudoers": "%wheel ALL=(ALL:ALL) ALL\n",
        "usr/lib/systemd/system/NetworkManager.service": "[Service]\nExecStart=/usr/bin/NetworkManager\n",
        "etc/systemd/system/multi-user.target.wants/NetworkManager.service": "enabled\n",
    }
    if include_windows:
        files["boot/EFI/Microsoft/Boot/bootmgfw.efi"] = "windows"
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def test_finalization_is_atomic_and_machine_specific(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    prepare_base_target(target)
    runner = FinalizeRunner()

    result = finalize_target_system(target, machine(), source_root=REBUILD_ROOT, runner=runner)

    assert result.status == "completed"
    marker = target / "var/lib/omarchy/install/install-success.json"
    payload = json.loads(marker.read_text(encoding="utf-8"))
    assert payload["status"] == "success"
    assert payload["machine"]["root_partuuid"] == machine().root_partuuid
    assert (target / "var/lib/omarchy/install/base-install-complete.json").is_file()
    assert (target / "var/lib/omarchy/install/target-finalization-complete.json").is_file()
    assert not (target / "var/lib/omarchy/install/omarchy-complete.json").exists()
    assert (target / "etc/systemd/system/multi-user.target.wants/omarchy-boot-guardian.service").exists()
    assert not (target / "etc/systemd/system/multi-user.target.wants/omarchy-firstboot.service").exists()
    assert (target / "etc/profile.d/omarchy-first-login.sh").is_file()
    assert any(command[:2] == ["systemd-analyze", "verify"] for command in runner.commands)
    assert any("PYTHONPATH=/opt/omarchy-installer" in command for command in runner.commands)


def test_missing_windows_loader_blocks_activation_and_marker(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    prepare_base_target(target, include_windows=False)
    deploy_target_assets(target, machine(), source_root=REBUILD_ROOT)

    with pytest.raises(TargetFinalizationError, match="Windows EFI"):
        validate_target_root(target, machine())
    assert not (target / "var/lib/omarchy/install/install-success.json").exists()
    assert not (target / "etc/systemd/system/multi-user.target.wants/omarchy-firstboot.service").exists()


def test_runtime_or_unit_verification_failure_leaves_services_disabled(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    prepare_base_target(target)

    with pytest.raises(TargetFinalizationError, match="invalid target"):
        finalize_target_system(target, machine(), source_root=REBUILD_ROOT, runner=FinalizeRunner(1))
    assert not (target / "var/lib/omarchy/install/install-success.json").exists()
    assert not (target / "etc/systemd/system/multi-user.target.wants/omarchy-boot-guardian.service").exists()
