from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

try:
    from rebuild.installer.platforms.installed_system.boot_guardian import (
        run_boot_guardian_check,
        run_boot_guardian_repair,
        record_boot_policy_completion,
    )
    from rebuild.installer.platforms.installed_system.boot_guardian_state import BootGuardianExpectedState
    from rebuild.installer.platforms.installed_system.boot_guardian_state import BootGuardianStateError
    from rebuild.installer.platforms.linux_live.boot_policy import summarize_preinstall_preservation
except ModuleNotFoundError:  # pragma: no cover - fallback for package-local test runs
    from installer.platforms.installed_system.boot_guardian import (
        run_boot_guardian_check,
        run_boot_guardian_repair,
        record_boot_policy_completion,
    )
    from installer.platforms.installed_system.boot_guardian_state import BootGuardianExpectedState
    from installer.platforms.installed_system.boot_guardian_state import BootGuardianStateError
    from installer.platforms.linux_live.boot_policy import summarize_preinstall_preservation


class BootPolicyRunner:
    def __init__(self, *, boot_order: str, mounted: bool = True, ambiguous: bool = False, fail_repair: bool = False) -> None:
        self.boot_order = boot_order
        self.mounted = mounted
        self.ambiguous = ambiguous
        self.fail_repair = fail_repair
        self.commands: list[list[str]] = []

    def run(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        if command[0] == "findmnt":
            if not self.mounted:
                return subprocess.CompletedProcess(command, 1, "", "not mounted")
            target = command[command.index("--target") + 1]
            return subprocess.CompletedProcess(
                command, 0,
                json.dumps({"filesystems": [{"target": target, "source": "/dev/nvme0n1p1", "fstype": "vfat", "uuid": "1111-2222", "partuuid": "00000000-0000-4000-8000-000000000001"}]}), "",
            )
        if command == ["efibootmgr", "-v"]:
            ambiguous = "Boot0004* Omarchy Linux\tHD(1,GPT,00000000-0000-0000-0000-000000000001,0x800,0x100000)\n" if self.ambiguous else ""
            return subprocess.CompletedProcess(
                args=command,
                returncode=0,
                stdout=(
                    "Boot0001* Limine\tHD(1,GPT,00000000-0000-0000-0000-000000000001,0x800,0x100000)\n"
                    "Boot0002* Windows Boot Manager\tHD(2,GPT,00000000-0000-0000-0000-000000000002,0x108000,0x100000)\n"
                    "Boot0003* UEFI PXE Network\tPciRoot(0x0)/Pci(0x1,0x0)\n" + ambiguous
                ),
                stderr="",
            )
        if command == ["efibootmgr"]:
            return subprocess.CompletedProcess(
                args=command,
                returncode=0,
                stdout=f"BootCurrent: 0002\nBootOrder: {self.boot_order}\nBoot0001* Limine\nBoot0002* Windows Boot Manager\n",
                stderr="",
            )
        if command[:2] == ["efibootmgr", "-o"] and len(command) == 3:
            if self.fail_repair:
                return subprocess.CompletedProcess(command, 1, "", "firmware rejected update")
            self.boot_order = command[2]
            return subprocess.CompletedProcess(args=command, returncode=0, stdout="BootOrder updated\n", stderr="")
        return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr=f"unexpected command: {' '.join(command)}")


def _write_expected_state(path: Path, efi_mount: Path) -> None:
    expected = BootGuardianExpectedState(
        efi_mount=str(efi_mount), efi_filesystem_uuid="1111-2222",
        efi_partuuid="00000000-0000-4000-8000-000000000001",
    )
    path.write_text(json.dumps(expected.to_dict(), indent=2) + "\n", encoding="utf-8")


def _write_efi_layout(root: Path, *, include_windows: bool = True, include_limine: bool = True) -> None:
    if include_windows:
        windows_path = root / "EFI" / "Microsoft" / "Boot" / "bootmgfw.efi"
        windows_path.parent.mkdir(parents=True, exist_ok=True)
        windows_path.write_text("windows", encoding="utf-8")
    if include_limine:
        limine_path = root / "EFI" / "Limine" / "BOOTX64.EFI"
        limine_path.parent.mkdir(parents=True, exist_ok=True)
        limine_path.write_text("limine", encoding="utf-8")


def test_check_reports_healthy_when_efi_and_boot_order_match(tmp_path: Path) -> None:
    efi_mount = tmp_path / "efi"
    _write_efi_layout(efi_mount)
    state_path = tmp_path / "expected-state.json"
    _write_expected_state(state_path, efi_mount)

    result = run_boot_guardian_check(
        state_path=state_path,
        efi_mount=efi_mount,
        runner=BootPolicyRunner(boot_order="0001,0002,0003"),
    )

    assert result.status == "healthy"
    assert result.severity == "healthy"
    assert result.exit_code == 0
    assert result.findings == ()
    assert result.observed_state.efi_mount_exists is True
    assert result.observed_state.windows_efi_exists is True
    assert result.observed_state.limine_efi_exists is True


def test_check_reports_warning_and_repair_command_for_boot_order_drift(tmp_path: Path) -> None:
    efi_mount = tmp_path / "efi"
    _write_efi_layout(efi_mount)
    state_path = tmp_path / "expected-state.json"
    _write_expected_state(state_path, efi_mount)

    result = run_boot_guardian_check(
        state_path=state_path,
        efi_mount=efi_mount,
        runner=BootPolicyRunner(boot_order="0002,0001,0003"),
    )

    assert result.status == "warning"
    assert result.severity == "warning"
    assert result.can_repair is True
    assert result.notify is False
    assert any(finding.code == "boot-order-drift" for finding in result.findings)
    assert result.repair_command == "efibootmgr -o 0001,0002,0003"


def test_repair_reorders_boot_order(tmp_path: Path) -> None:
    efi_mount = tmp_path / "efi"
    _write_efi_layout(efi_mount)
    state_path = tmp_path / "expected-state.json"
    _write_expected_state(state_path, efi_mount)
    runner = BootPolicyRunner(boot_order="0002,0001,0003")

    result = run_boot_guardian_repair(
        state_path=state_path,
        efi_mount=efi_mount,
        runner=runner,
    )

    assert result.status == "repaired"
    assert result.severity == "healthy"
    assert result.exit_code == 0
    assert result.repair_attempted is True
    assert result.repaired is True
    assert runner.boot_order == "0001,0002,0003"
    assert ["efibootmgr", "-o", "0001,0002,0003"] in runner.commands


def test_check_reports_critical_when_windows_efi_missing(tmp_path: Path) -> None:
    efi_mount = tmp_path / "efi"
    _write_efi_layout(efi_mount, include_windows=False, include_limine=True)
    state_path = tmp_path / "expected-state.json"
    _write_expected_state(state_path, efi_mount)

    result = run_boot_guardian_check(
        state_path=state_path,
        efi_mount=efi_mount,
        runner=BootPolicyRunner(boot_order="0001,0002,0003"),
    )

    assert result.status == "critical"
    assert result.severity == "critical"
    assert result.exit_code == 1
    assert any(finding.code == "windows-efi-missing" for finding in result.findings)
    assert result.can_repair is False


def test_missing_expected_state_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(BootGuardianStateError, match="Mandatory"):
        run_boot_guardian_check(state_path=tmp_path / "missing.json", runner=BootPolicyRunner(boot_order="0001,0002"))


def test_efi_directory_that_is_not_mounted_is_critical(tmp_path: Path) -> None:
    efi_mount = tmp_path / "efi"
    _write_efi_layout(efi_mount)
    state_path = tmp_path / "expected-state.json"
    _write_expected_state(state_path, efi_mount)
    result = run_boot_guardian_check(state_path=state_path, runner=BootPolicyRunner(boot_order="0001,0002", mounted=False))
    assert result.status == "critical"
    assert "not mounted" in result.observed_state.measurement_error


def test_ambiguous_similar_boot_labels_are_never_repaired(tmp_path: Path) -> None:
    efi_mount = tmp_path / "efi"
    _write_efi_layout(efi_mount)
    state_path = tmp_path / "expected-state.json"
    _write_expected_state(state_path, efi_mount)
    result = run_boot_guardian_repair(state_path=state_path, runner=BootPolicyRunner(boot_order="0002,0001,0004", ambiguous=True))
    assert result.status == "critical"
    assert not result.repair_attempted


def test_failed_boot_order_repair_is_critical(tmp_path: Path) -> None:
    efi_mount = tmp_path / "efi"
    _write_efi_layout(efi_mount)
    state_path = tmp_path / "expected-state.json"
    _write_expected_state(state_path, efi_mount)
    result = run_boot_guardian_repair(state_path=state_path, runner=BootPolicyRunner(boot_order="0002,0001", fail_repair=True))
    assert result.status == "critical"
    assert result.repair_attempted and not result.repaired


def test_preinstall_preservation_does_not_require_limine(tmp_path: Path) -> None:
    efi_mount = tmp_path / "efi"
    _write_efi_layout(efi_mount, include_limine=False)
    result = summarize_preinstall_preservation(efi_mount=efi_mount, runner=BootPolicyRunner(boot_order="0002"))
    assert result.can_proceed
    assert result.windows_efi_exists


def test_completion_markers_require_healthy_state_and_preserve_stage_independence(tmp_path: Path) -> None:
    efi_mount = tmp_path / "efi"
    _write_efi_layout(efi_mount)
    state_path = tmp_path / "expected-state.json"
    _write_expected_state(state_path, efi_mount)
    healthy = run_boot_guardian_check(state_path=state_path, runner=BootPolicyRunner(boot_order="0001,0002"))
    written = record_boot_policy_completion(healthy, marker_directory=tmp_path / "markers")
    assert len(written) == 1
    assert (tmp_path / "markers/boot-policy-complete.json").is_file()
    assert not (tmp_path / "markers/overall-setup-complete.json").exists()
    (tmp_path / "markers/omarchy-complete.json").write_text("{}", encoding="utf-8")
    written = record_boot_policy_completion(healthy, marker_directory=tmp_path / "markers")
    assert written == (str(tmp_path / "markers/overall-setup-complete.json"),)
