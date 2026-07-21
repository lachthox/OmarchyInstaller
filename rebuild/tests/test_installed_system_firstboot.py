from __future__ import annotations

import json
from pathlib import Path
import subprocess

try:
    from rebuild.installer.platforms.installed_system.firstboot import (
        FirstBootRuntimeContext,
        evaluate_firstboot_timing_policy,
        run_firstboot_handoff,
    )
    from rebuild.installer.platforms.installed_system.post_install import (
        build_bootstrap_contract,
        evaluate_bootstrap_health,
        normalize_boot_policy,
    )
except ModuleNotFoundError:  # pragma: no cover - fallback for package-local test runs
    from installer.platforms.installed_system.firstboot import (
        FirstBootRuntimeContext,
        evaluate_firstboot_timing_policy,
        run_firstboot_handoff,
    )
    from installer.platforms.installed_system.post_install import (
        build_bootstrap_contract,
        evaluate_bootstrap_health,
        normalize_boot_policy,
    )


class InstalledSystemRunner:
    def __init__(self, *, command_returncode: int = 0, boot_order: tuple[str, ...] = ("0002", "0001")) -> None:
        self.command_returncode = command_returncode
        self.commands: list[list[str]] = []
        self.boot_order = list(boot_order)

    def run(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        if command[:2] == ["efibootmgr", "-v"]:
            return subprocess.CompletedProcess(
                args=command,
                returncode=0,
                stdout=(
                    "Boot0001* Windows Boot Manager\tHD(1,GPT,deadbeef,0x800,0x100000)/File(\\EFI\\Microsoft\\Boot\\bootmgfw.efi)\n"
                    "Boot0002* Limine\tHD(2,GPT,feedface,0x1800,0x100000)/File(\\EFI\\Limine\\BOOTX64.EFI)\n"
                ),
                stderr="",
            )
        if command[:1] == ["efibootmgr"] and len(command) == 1:
            return subprocess.CompletedProcess(
                args=command,
                returncode=0,
                stdout=f"BootOrder: {','.join(self.boot_order)}\n",
                stderr="",
            )
        if command[:2] == ["efibootmgr", "-o"] and len(command) == 3:
            self.boot_order = command[2].split(",")
            return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")
        return subprocess.CompletedProcess(
            args=command,
            returncode=self.command_returncode,
            stdout="" if self.command_returncode == 0 else "failure",
            stderr="" if self.command_returncode == 0 else "failure",
        )


def _ready_context(*, completion_marker_exists: bool = False) -> FirstBootRuntimeContext:
    return FirstBootRuntimeContext(
        platform="linux",
        is_linux=True,
        os_release_id="arch",
        is_wsl=False,
        is_live_iso=False,
        pid1_comm="systemd",
        login_users=("alice",),
        install_marker_exists=True,
        completion_marker_exists=completion_marker_exists,
    )


def _write_bootstrap_fixture(root: Path) -> None:
    (root / "hooks").mkdir(parents=True, exist_ok=True)
    (root / "setup.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    (root / "main.py").write_text("print('ok')\n", encoding="utf-8")
    (root / "requirements.txt").write_text("pydantic\n", encoding="utf-8")
    (root / "runtime-packages.txt").write_text("python\n", encoding="utf-8")
    (root / "hooks" / "live-autostart.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    (root / "hooks" / "firstboot-wrapper.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    metadata = {
        "runtime": {
            "entrypoint": "python3 /opt/omarchy-installer/main.py",
            "setup_wrapper": "/opt/omarchy-setup/setup.sh",
            "entrypoint_compat_alias": "python3 /opt/omarchy-setup/main.py",
            "required_system_packages_file": "/opt/omarchy-setup/runtime-packages.txt",
        },
        "startup_hooks": {
            "live_tty_hook": "/usr/local/bin/omarchy-live-autostart",
            "payload_hook_reference": "/opt/omarchy-setup/hooks/live-autostart.sh",
        },
    }
    (root / "build-metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")


def _write_efi_fixture(root: Path) -> None:
    (root / "EFI" / "Microsoft" / "Boot").mkdir(parents=True, exist_ok=True)
    (root / "EFI" / "Limine").mkdir(parents=True, exist_ok=True)
    (root / "EFI" / "Microsoft" / "Boot" / "bootmgfw.efi").write_text("win", encoding="utf-8")
    (root / "EFI" / "Limine" / "BOOTX64.EFI").write_text("limine", encoding="utf-8")


def test_timing_policy_blocks_wsl_and_live_iso() -> None:
    context = FirstBootRuntimeContext(
        platform="linux",
        is_linux=True,
        os_release_id="arch",
        is_wsl=True,
        is_live_iso=True,
        pid1_comm="systemd",
        login_users=("alice",),
        install_marker_exists=True,
        completion_marker_exists=False,
    )
    can_proceed, blockers, _ = evaluate_firstboot_timing_policy(context)
    assert not can_proceed
    assert "WSL environment detected" in blockers
    assert "live ISO environment detected" in blockers


def test_firstboot_blocks_without_login(tmp_path: Path) -> None:
    context = FirstBootRuntimeContext(
        platform="linux",
        is_linux=True,
        os_release_id="arch",
        is_wsl=False,
        is_live_iso=False,
        pid1_comm="systemd",
        login_users=tuple(),
        install_marker_exists=True,
        completion_marker_exists=False,
    )
    result = run_firstboot_handoff(
        context=context,
        runner=InstalledSystemRunner(),
        attempt_log_path=tmp_path / "attempt.log.jsonl",
    )
    assert result.status == "blocked"
    assert result.exit_code == 3
    assert "no logged-in non-root user session detected" in result.blockers


def test_firstboot_writes_completion_marker_on_success(tmp_path: Path) -> None:
    install_marker = tmp_path / "install-success.json"
    install_marker.write_text("{\"status\":\"ok\"}\n", encoding="utf-8")
    completion_marker = tmp_path / "completed.json"
    attempt_log = tmp_path / "attempt.log.jsonl"

    bootstrap_root = tmp_path / "opt" / "omarchy-setup"
    _write_bootstrap_fixture(bootstrap_root)
    efi_mount = tmp_path / "boot" / "efi"
    _write_efi_fixture(efi_mount)

    runner = InstalledSystemRunner(command_returncode=0, boot_order=("0002", "0001"))
    result = run_firstboot_handoff(
        context=_ready_context(),
        bootstrap_root=bootstrap_root,
        install_marker_path=install_marker,
        completion_marker_path=completion_marker,
        attempt_log_path=attempt_log,
        command="echo test",
        efi_mount=efi_mount,
        runner=runner,
    )

    assert result.status == "completed"
    assert result.exit_code == 0
    assert completion_marker.exists()
    assert attempt_log.exists()
    assert ["bash", "-lc", "echo test"] in runner.commands
    assert result.bootstrap_health.can_proceed
    assert result.post_install_normalization is not None
    assert result.post_install_normalization.can_proceed


def test_bootstrap_health_blocks_when_contract_files_missing(tmp_path: Path) -> None:
    contract = build_bootstrap_contract(bootstrap_root=tmp_path / "missing-root")
    result = evaluate_bootstrap_health(contract)
    assert not result.can_proceed
    assert any("bootstrap root is missing" in blocker for blocker in result.blockers)


def test_bootstrap_health_accepts_complete_contract(tmp_path: Path) -> None:
    bootstrap_root = tmp_path / "opt" / "omarchy-setup"
    _write_bootstrap_fixture(bootstrap_root)
    contract = build_bootstrap_contract(bootstrap_root=bootstrap_root)
    result = evaluate_bootstrap_health(contract)
    assert result.can_proceed
    assert not result.blockers
    assert result.metadata["runtime"]["setup_wrapper"] == "/opt/omarchy-setup/setup.sh"


def test_boot_policy_normalization_repairs_boot_order(tmp_path: Path) -> None:
    efi_mount = tmp_path / "boot" / "efi"
    _write_efi_fixture(efi_mount)
    runner = InstalledSystemRunner(boot_order=("0001", "0002"))

    result = normalize_boot_policy(efi_mount=efi_mount, runner=runner)

    assert result.can_proceed
    assert result.repair_actions == ("efibootmgr -o 0002,0001",)
    assert runner.boot_order == ["0002", "0001"]


def test_firstboot_returns_already_completed_when_marker_exists(tmp_path: Path) -> None:
    completion_marker = tmp_path / "completed.json"
    completion_marker.parent.mkdir(parents=True, exist_ok=True)
    completion_marker.write_text("{}\n", encoding="utf-8")
    bootstrap_root = tmp_path / "opt" / "omarchy-setup"
    _write_bootstrap_fixture(bootstrap_root)

    result = run_firstboot_handoff(
        context=_ready_context(completion_marker_exists=True),
        bootstrap_root=bootstrap_root,
        completion_marker_path=completion_marker,
        runner=InstalledSystemRunner(),
    )
    assert result.status == "already-completed"
    assert result.exit_code == 0
    assert not result.executed
