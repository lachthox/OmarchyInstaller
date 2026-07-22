from __future__ import annotations

import json
from pathlib import Path

import pytest

from rebuild.installer.platforms.linux_live.identity import (
    MachineIdentityError,
    resolve_target_disk_path,
)
from rebuild.installer.platforms.linux_live.install import execute_install_plan
from rebuild.installer.shared.validation import validate_plan_contract


REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = REPO_ROOT / "rebuild" / "assets" / "templates" / "plan.template.json"
GIB = 1024**3


def base_plan() -> dict:
    return json.loads(TEMPLATE.read_text(encoding="utf-8"))


def with_target(payload: dict, *, install_gib: int = 200, guid: str = "target-disk-guid") -> dict:
    sector = 512
    start = (1024**2) // sector
    span = install_gib * GIB // sector
    end = start + span - 1
    payload["linux_install_target"] = {
        "disk_identity": {
            "gpt_disk_guid": guid,
            "disk_size_bytes": 1000 * GIB,
            "logical_sector_size": sector,
            "disk_model": "Target NVMe",
            "disk_serial": "TGT",
            "runtime_disk_number": 1,
            "partition_style": "GPT",
        },
        "install_range": {
            "start_sector": start,
            "end_sector": end,
            "logical_sector_size": sector,
            "size_bytes": (end - start + 1) * sector,
        },
        "mode": "free_space",
        "erases_existing_data": False,
    }
    return payload


def _commands(payload: dict, **kwargs) -> list[str]:
    result = execute_install_plan(payload, dry_run=True, **kwargs)
    return list(result.commands)


def test_single_disk_efibootmgr_uses_the_same_disk() -> None:
    commands = _commands(base_plan(), target_disk_path="/dev/nvme0n1")
    efibootmgr = next(c for c in commands if "efibootmgr" in c)
    assert "--disk /dev/nvme0n1" in efibootmgr
    assert "--part 1" in efibootmgr
    # Linux partition is created on the same disk.
    new = next(c for c in commands if c.startswith("sgdisk --new="))
    assert "/dev/nvme0n1" in new


def test_separate_disk_puts_root_on_target_but_esp_on_windows_disk() -> None:
    payload = with_target(base_plan(), install_gib=200)
    plan = validate_plan_contract(payload)
    esp_part = plan.efi_identity.partition_number
    install_start = plan.linux_install_target.install_range.start_sector

    commands = _commands(
        payload,
        target_disk_path="/dev/sdb",       # Linux disk
        esp_disk_path="/dev/sda",          # Windows disk (holds the ESP)
        efi_partition_path="/dev/sda1",    # Windows ESP
    )

    # The new Linux partition is created on the target disk at the target's range.
    new = next(c for c in commands if c.startswith("sgdisk --new="))
    assert "/dev/sdb" in new
    assert f"--new=0:{install_start}:" in new

    # The bootloader entry points at the Windows disk / ESP partition, not the
    # Linux disk. (The same bash block legitimately reads the root partition's
    # LUKS UUID off the Linux disk via blkid, so scope the check to efibootmgr.)
    efibootmgr = next(c for c in commands if "efibootmgr" in c)
    assert f"efibootmgr --create --disk /dev/sda --part {esp_part}" in efibootmgr
    # The LUKS UUID for the boot entry is read from the root partition on the Linux disk.
    assert "blkid -s UUID -o value /dev/sdb-planned-partition" in efibootmgr

    # The ESP is still mounted at /boot from the Windows ESP.
    mount_esp = next(c for c in commands if c.startswith("mount") and "/dev/sda1" in c and "/boot" in c)
    assert "/mnt/archinstall/boot" in mount_esp


class FakeBlockProbe:
    def __init__(self, devices: list[dict]) -> None:
        self._devices = devices

    def collect_block_devices(self) -> dict:
        return {"blockdevices": self._devices}


def test_resolve_target_disk_matches_by_guid_and_excludes_windows() -> None:
    payload = with_target(base_plan(), install_gib=200, guid="00000000-0000-4000-8000-0000000000aa")
    payload["linux_install_target"]["disk_identity"]["disk_serial"] = "OMARCHYSPARE"
    plan = validate_plan_contract(payload)
    win_guid = plan.disk_identity.gpt_disk_guid
    target_guid = plan.linux_install_target.disk_identity.gpt_disk_guid
    probe = FakeBlockProbe(
        [
            {"type": "disk", "path": "/dev/vda", "ptuuid": win_guid, "serial": "WIN", "size": 512 * GIB},
            {"type": "disk", "path": "/dev/vdb", "ptuuid": target_guid, "serial": "OMARCHYSPARE", "size": 1000 * GIB},
        ]
    )
    assert resolve_target_disk_path(plan, probe=probe) == "/dev/vdb"


def test_resolve_target_disk_no_match_raises() -> None:
    payload = with_target(base_plan(), install_gib=200, guid="00000000-0000-4000-8000-0000000000bb")
    plan = validate_plan_contract(payload)
    probe = FakeBlockProbe([{"type": "disk", "path": "/dev/vda", "ptuuid": "other-guid", "serial": "OTHER", "size": 1 * GIB}])
    with pytest.raises(MachineIdentityError):
        resolve_target_disk_path(plan, probe=probe)
