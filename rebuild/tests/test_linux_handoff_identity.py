from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from rebuild.installer.platforms.linux_live.discovery import (
    HandoffDiscoveryError,
    HandoffValidationContext,
    discover_and_validate_handoff_plan,
    discover_handoff_sources,
    open_validated_handoff,
)
from rebuild.installer.platforms.linux_live.identity import (
    MachineIdentityError,
    match_machine_identity,
)
from rebuild.installer.platforms.linux_live.install import LiveInstallError, execute_install_plan
from rebuild.installer.platforms.windows.handoff import stage_ventoy_handoff_bundle


WORKSPACE = Path(__file__).resolve().parents[2]
KEY = b"phase-nine-one-time-integrity-key!!"


def plan_payload() -> dict:
    return json.loads(
        (WORKSPACE / "rebuild" / "assets" / "templates" / "plan.template.json").read_text(
            encoding="utf-8"
        )
    )


def make_bundle(root: Path, payload: dict | None = None) -> Path:
    iso = root.parent / "omarchy.iso"
    iso.parent.mkdir(parents=True, exist_ok=True)
    iso.write_bytes(b"pinned-iso")
    stage_ventoy_handoff_bundle(root, iso, payload or plan_payload(), integrity_key=KEY)
    return root


def context(*, max_age: int | None = None) -> HandoffValidationContext:
    return HandoffValidationContext(
        live_runtime_version="1.0.0",
        expected_release_tag="v1.0.0",
        expected_build_commit="0" * 40,
        max_plan_age_hours=max_age,
        integrity_key=KEY,
    )


def test_recursive_topology_and_authenticated_handoff(tmp_path: Path) -> None:
    root = make_bundle(tmp_path / "media" / "user" / "VENTOY")
    assert discover_handoff_sources([root]) == [str(root.resolve())]
    result = discover_and_validate_handoff_plan(context(), search_roots=[root])
    assert result.plan.disk_identity.gpt_disk_guid.endswith("0010")


def test_tampered_and_stale_handoffs_fail_closed(tmp_path: Path) -> None:
    root = make_bundle(tmp_path / "VENTOY")
    plan_path = root / "omarchy" / "plan.json"
    plan_path.write_text(plan_path.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(HandoffDiscoveryError, match="hash"):
        discover_and_validate_handoff_plan(context(), search_roots=[root])

    stale = plan_payload()
    stale["meta"]["generated_at_utc"] = (datetime.now(UTC) - timedelta(hours=5)).isoformat()
    stale_root = make_bundle(tmp_path / "STALE", stale)
    with pytest.raises(HandoffDiscoveryError, match="older"):
        discover_and_validate_handoff_plan(context(max_age=1), search_roots=[stale_root])


def test_multiple_valid_handoffs_are_ambiguous(tmp_path: Path) -> None:
    first = make_bundle(tmp_path / "one")
    second = make_bundle(tmp_path / "two")
    with pytest.raises(HandoffDiscoveryError, match="ambiguous"):
        discover_and_validate_handoff_plan(context(), search_roots=[first, second])


class FakeMountRunner:
    def __init__(self, source: Path) -> None:
        self.source = source
        self.commands: list[list[str]] = []

    def run(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        if command[0] == "lsblk":
            payload = {
                "blockdevices": [
                    {
                        "path": "/dev/sdz",
                        "type": "disk",
                        "rm": True,
                        "children": [
                            {
                                "path": "/dev/sdz1",
                                "type": "part",
                                "rm": False,
                                "label": "VENTOY",
                                "fstype": "exfat",
                            }
                        ],
                    }
                ]
            }
            return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")
        if command[0] == "mount":
            shutil.copytree(self.source, Path(command[-1]), dirs_exist_ok=True)
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[0] == "umount":
            return subprocess.CompletedProcess(command, 0, "", "")
        raise AssertionError(command)


def test_controlled_read_only_mount_is_always_unmounted(tmp_path: Path) -> None:
    source = make_bundle(tmp_path / "source")
    runner = FakeMountRunner(source)
    mountpoint = tmp_path / "runtime" / "handoff"
    with open_validated_handoff(context(), runner=runner, mountpoint=mountpoint) as result:
        assert result.plan.meta.schema_version == "1.0.0"
    assert runner.commands[-1] == ["umount", str(mountpoint)]
    assert runner.commands[1][0:3] == ["mount", "-o", "ro,nosuid,nodev,noexec"]


class IdentityProbe:
    def __init__(self, devices: list[dict]) -> None:
        self.devices = devices

    def collect_block_devices(self) -> dict:
        return {"blockdevices": self.devices}


def disk_record(*, path: str = "/dev/nvme0n1", serial: str = "", guid: str | None = None) -> dict:
    plan = plan_payload()
    identity = plan["disk_identity"]
    esp = plan["efi_identity"]
    windows = plan["windows_partition_identity"]
    return {
        "name": Path(path).name,
        "path": path,
        "type": "disk",
        "size": identity["disk_size_bytes"],
        "model": identity["disk_model"],
        "serial": serial,
        "ptuuid": guid or identity["gpt_disk_guid"],
        "log-sec": identity["logical_sector_size"],
        "first_usable_sector": 34,
        "last_usable_sector": identity["disk_size_bytes"] // 512 - 34,
        "children": [
            {
                "path": f"{path}p1",
                "type": "part",
                "size": esp["size_bytes"],
                "start": esp["start_sector"],
                "partuuid": esp["partuuid"],
                "uuid": esp["filesystem_uuid"],
                "fstype": esp["filesystem_type"],
            },
            {
                "path": f"{path}p2",
                "type": "part",
                "size": windows["size_bytes"],
                "start": windows["start_sector"],
                "partuuid": windows["partuuid"],
                "uuid": windows["filesystem_uuid"],
                "fstype": windows["filesystem_type"],
            },
        ],
    }


def test_gpt_guid_namespaces_geometry_and_usable_end_are_independent() -> None:
    result = match_machine_identity(plan_payload(), probe=IdentityProbe([disk_record()]))
    assert result.disk.first_usable_sector == 34
    assert result.validated_free_space_start_sector == 943718400

    wrong_fs = disk_record()
    wrong_fs["children"][0]["uuid"] = "wrong-filesystem-uuid"
    with pytest.raises(MachineIdentityError, match="filesystem UUID"):
        match_machine_identity(plan_payload(), probe=IdentityProbe([wrong_fs]))

    wrong_guid = disk_record(guid="10000000-0000-4000-8000-000000000010")
    with pytest.raises(MachineIdentityError, match="No live disk"):
        match_machine_identity(plan_payload(), probe=IdentityProbe([wrong_guid]))


def test_absent_serial_is_safe_but_duplicate_exact_identities_are_ambiguous() -> None:
    match_machine_identity(plan_payload(), probe=IdentityProbe([disk_record(serial="")]))
    with pytest.raises(MachineIdentityError, match="ambiguous"):
        match_machine_identity(
            plan_payload(),
            probe=IdentityProbe([disk_record(path="/dev/sda"), disk_record(path="/dev/sdb")]),
        )


class InstallRunner:
    def __init__(self, *, stale: bool = False) -> None:
        self.created = False
        self.stale = stale
        self.commands: list[list[str]] = []

    def run(
        self, command: list[str], input_text: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        if command[:2] == ["sgdisk", "--print"]:
            return subprocess.CompletedProcess(
                command,
                0,
                "Disk identifier (GUID): 00000000-0000-4000-8000-000000000010\n"
                "First usable sector is 34, last usable sector is 1073741790\n",
                "",
            )
        if command[0] == "sgdisk":
            self.created = True
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[0] == "lsblk":
            partitions: list[dict] = []
            if self.stale and not self.created:
                partitions.append(
                    {
                        "path": "/dev/nvme0n1p9",
                        "type": "part",
                        "start": 943718400,
                        "size": 1024 * 1024,
                        "pkname": "nvme0n1",
                    }
                )
            if self.created:
                partitions.append(
                    {
                        "path": "/dev/nvme0n1p3",
                        "type": "part",
                        "start": 943720448,
                        "size": 42948624384,
                        "pkname": "nvme0n1",
                        "partlabel": "omarchy-linux",
                        "partuuid": "00000000-0000-4000-8000-000000000099",
                    }
                )
            return subprocess.CompletedProcess(
                command, 0, json.dumps({"blockdevices": partitions}), ""
            )
        return subprocess.CompletedProcess(command, 0, "", "")


def test_extent_rechecked_and_actual_aligned_geometry_replaces_requested(tmp_path: Path) -> None:
    runner = InstallRunner()
    result = execute_install_plan(
        plan_payload(),
        target_disk_path="/dev/nvme0n1",
        stage_root=tmp_path,
        dry_run=False,
        encryption_passphrase="not-a-real-secret",
        cleanup_after_success=False,
        runner=runner,
    )
    assert result.target_partition_start_sector == 943720448
    assert result.target_partition_guid.endswith("0099")
    config = json.loads((Path(result.stage_root) / "runtime" / "archinstall-config.json").read_text())
    assert config["target"]["partition_start_sector"] == 943720448
    assert runner.commands[0][:2] == ["sgdisk", "--print"]


def test_stale_extent_blocks_before_partition_command(tmp_path: Path) -> None:
    runner = InstallRunner(stale=True)
    with pytest.raises(LiveInstallError, match="no longer free"):
        execute_install_plan(
            plan_payload(),
            target_disk_path="/dev/nvme0n1",
            stage_root=tmp_path,
            dry_run=False,
            encryption_passphrase="not-a-real-secret",
            runner=runner,
        )
    assert not any(command[0] == "sgdisk" and command[1].startswith("--new") for command in runner.commands)
