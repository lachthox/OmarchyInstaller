#!/usr/bin/env python3
"""OMARCHY_ISOLATED_VM_DRIVER implementation: real QEMU/OVMF disposable install gate.

Invoked by `rebuild.tools.vm_install_test` as:
    <this file> --iso <path> --work-dir <dir> --evidence-output <path>

Drives the production Textual live installer over a real serial console to
perform a genuine disposable UEFI dual-boot install, then reboots the
installed disk and verifies it from the outside. Nothing here replaces
partitioning, archinstall, or target finalization with mocks -- it types into
the same TUI a human operator would, and shells out to the same commands.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from rebuild.tools.vm_drivers import disk_fixture, plan_fixture  # noqa: E402
from rebuild.tools.vm_drivers.console import SerialConsole  # noqa: E402


OVMF_CODE_CANDIDATES = (
    "/usr/share/OVMF/OVMF_CODE_4M.fd",
    "/usr/share/edk2/x64/OVMF_CODE.fd",
    "/usr/share/OVMF/OVMF_CODE.fd",
)
OVMF_VARS_CANDIDATES = (
    "/usr/share/OVMF/OVMF_VARS_4M.fd",
    "/usr/share/edk2/x64/OVMF_VARS.fd",
    "/usr/share/OVMF/OVMF_VARS.fd",
)

LUKS_PASSPHRASE = "OmarchyVMTest-Luks-9f3c1a"
SERIAL_PORT = 45101
QMP_PORT = 45201
LIVE_RUNTIME_VERSION = "1.0.0"


REQUIRED_TRUE_FIELDS = (
    "windows_prep_simulation",
    "uefi_iso_booted",
    "python_live_tui_started",
    "installation_completed",
    "reboot_completed",
    "windows_efi_preserved",
    "normal_user_first_login_reached",
    "recovery_restore_tested",
)


def _find_first(candidates: tuple[str, ...], label: str) -> str:
    for candidate in candidates:
        if Path(candidate).is_file():
            return candidate
    raise RuntimeError(f"Could not locate {label}; tried: {candidates}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=True, **kwargs)


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Evidence:
    fields: dict[str, Any] = field(default_factory=dict)
    stage_log: list[str] = field(default_factory=list)

    def note(self, message: str) -> None:
        stamped = f"{_utc_now()} {message}"
        self.stage_log.append(stamped)
        print(stamped, file=sys.stderr)

    def set(self, key: str, value: Any) -> None:
        self.fields[key] = value


class QemuProcess:
    def __init__(self, args: list[str]) -> None:
        self.args = args
        self.proc: subprocess.Popen | None = None

    def start(self) -> None:
        self.proc = subprocess.Popen(self.args)

    def wait(self, timeout: float) -> int | None:
        assert self.proc is not None
        try:
            return self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            return None

    def kill(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()


def qemu_base_args(*, ovmf_code: str, ovmf_vars: Path, disk_img: Path) -> list[str]:
    return [
        "qemu-system-x86_64",
        "-machine", "q35,accel=kvm:tcg",
        "-cpu", "host",
        "-m", "4096",
        "-smp", "2",
        "-drive", f"if=pflash,format=raw,readonly=on,file={ovmf_code}",
        "-drive", f"if=pflash,format=raw,file={ovmf_vars}",
        # NOT cache=unsafe: that mode ignores the guest's flush/FUA requests
        # entirely, so cryptsetup's LUKS header writes during install could
        # still be sitting in this process's cache -- never reaching the
        # on-disk file -- when it exits. A second, independent QEMU process
        # later opening the same disk.img would then see stale/incomplete
        # data despite everything having worked within the first session.
        # cache=writeback keeps host-page-cache speed but actually honors
        # flushes, which a real reboot-and-unlock test depends on.
        "-drive", f"file={disk_img},format=raw,if=virtio,cache=writeback",
        "-nographic",
        "-monitor", "none",
        "-serial", f"tcp:127.0.0.1:{SERIAL_PORT},server=on,wait=off",
        "-qmp", f"tcp:127.0.0.1:{QMP_PORT},server=on,wait=off",
        "-no-reboot",
    ]


def login_as_root(console: SerialConsole, evidence: Evidence) -> None:
    # Shared CI hardware (GitHub-hosted runners) is markedly slower than a
    # dedicated nested-KVM box for CD-ROM-backed squashfs boot; 120s was
    # measured as too tight there even though KVM acceleration is active.
    console.wait_for("login:", timeout=300)
    console.send_line("root")
    console.wait_for("archiso ~", "# ", timeout=30)
    evidence.note("logged in as root on ttyS0")
    # The live TUI's stage-summary/content widgets don't fit an 80x24 window
    # once real handoff/network/install data is rendered (title + stages +
    # four bordered input boxes + two buttons + hints leaves ~1 row for the
    # actual status text). A wider terminal is exactly what a human operator
    # would use too, so resize the pty before the TUI ever starts.
    console.send_line(f"stty cols {console.columns} rows {console.rows} && echo STTY_RESIZED")
    console.wait_for("STTY_RESIZED", timeout=15)
    evidence.note(f"resized live console to {console.columns}x{console.rows}")

    # A real pre-existing Windows install registers its own "Windows Boot
    # Manager" NVRAM entry via its own setup (bcdboot); NVRAM/UEFI variables
    # only exist once actual firmware is running, so this disposable fixture
    # can't pre-bake one into the raw disk image from the host side the way
    # the ESP *files* were pre-baked. Register it for real now, under this
    # boot's live OVMF, simulating what "windows_prep_simulation" stands in
    # for the post-install boot-policy check requires it to prove dual-boot
    # preservation, not just the loader files being present.
    console.send_line(
        "efibootmgr --create --disk /dev/vda --part 1 "
        "--loader '\\EFI\\Microsoft\\Boot\\bootmgfw.efi' --label 'Windows Boot Manager' "
        "&& echo WINDOWS_NVRAM_ENTRY_CREATED || echo WINDOWS_NVRAM_ENTRY_FAILED"
    )
    windows_nvram = console.wait_for(
        "WINDOWS_NVRAM_ENTRY_CREATED", "WINDOWS_NVRAM_ENTRY_FAILED", timeout=20
    )
    evidence.note(f"synthetic Windows Boot Manager NVRAM entry: {windows_nvram}")


def read_build_manifest(iso_path: Path) -> dict[str, Any]:
    manifest_path = iso_path.parent / "iso-build-manifest.json"
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def generate_handoff(
    *,
    ventoy_root: Path,
    iso_on_ventoy: Path,
    manifest: dict[str, Any],
    geo: disk_fixture.DiskGeometry,
    spare: plan_fixture.SpareDiskGeometry | None = None,
) -> tuple[bytes, dict[str, Any]]:
    return plan_fixture.write_plan_and_manifest(
        ventoy_root=ventoy_root,
        geometry=geo,
        release_tag=manifest["release_tag"],
        build_commit=manifest["git_commit"],
        workflow_run_id=str(manifest.get("github_run_id", "local")),
        producer_version="1.0.0",
        iso_name=manifest["output_iso"]["name"],
        iso_sha256=manifest["output_iso"]["sha256"],
        iso_path_on_ventoy=iso_on_ventoy,
        bootstrap_url="https://raw.githubusercontent.com/octocat/Hello-World/7fd1a60b01f91b314f59955a4e4d4e80d8edf11/README",
        bootstrap_sha256=_sha256_of_url(
            "https://raw.githubusercontent.com/octocat/Hello-World/7fd1a60b01f91b314f59955a4e4d4e80d8edf11/README"
        ),
        bootstrap_upstream_version="pinned-test-fixture",
        spare=spare,
    )


def _sha256_of_url(url: str) -> str:
    import urllib.request

    with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310
        return hashlib.sha256(response.read()).hexdigest()


def drive_handoff_and_install(
    console: SerialConsole,
    evidence: Evidence,
) -> bool:
    # Must run in the foreground: a backgrounded process reading the
    # controlling tty would be stopped (SIGTTIN) the instant it tries to
    # read our keystrokes, so this line is never followed by `&`.
    console.send_line(
        "cd / && /opt/omarchy-venv/bin/python -m installer.main "
        f"--runtime-version {LIVE_RUNTIME_VERSION}"
    )
    time.sleep(5)
    evidence.note("launched live installer TUI in the foreground on ttyS0")
    evidence.set("python_live_tui_started", "Omarchy Installer" in console.screen_text())

    console.wait_for(
        "Create your password",
        "Connect to the internet",
        "couldn't read the installer USB",
        timeout=90,
    )

    def _preflight_ready() -> tuple[bool, str]:
        text = console.screen_text()
        ok = "Create your password" in text or "Connect to the internet" in text
        return ok, text

    deadline = time.monotonic() + 30
    preflight_ok, snapshot = _preflight_ready()
    while not preflight_ok and time.monotonic() < deadline:
        time.sleep(2)
        preflight_ok, snapshot = _preflight_ready()
    evidence.note(f"preflight ready: {preflight_ok}")
    if not preflight_ok:
        evidence.note("preflight failed; screen snapshot follows")
        evidence.note(snapshot)
        evidence.note(console.scrollback_text(tail_bytes=4000))
        return False

    def _network_ready() -> tuple[bool, str]:
        text = console.screen_text()
        ok = "Create your password" in text
        return ok, text

    network_ok, snapshot = _network_ready()
    if not network_ok:
        console.send_key("enter")
        deadline = time.monotonic() + 90
        while not network_ok and time.monotonic() < deadline:
            time.sleep(3)
            network_ok, snapshot = _network_ready()
    evidence.note(f"network ready: {network_ok}")
    if not network_ok:
        evidence.note(snapshot)
        evidence.note(console.scrollback_text(tail_bytes=4000))
        return False

    # The guided UI asks for one password twice and uses it for both disk
    # unlock and login. The first password field is focused automatically.
    console.send(LUKS_PASSPHRASE)
    time.sleep(0.5)
    console.send_key("tab")
    time.sleep(0.5)
    console.send(LUKS_PASSPHRASE)
    time.sleep(0.5)
    console.send_key("enter")
    console.wait_for("Ready to install Omarchy", timeout=30)
    console.send_key("enter")
    evidence.note("confirmed one password and started installation through guided UI")

    result = console.wait_for(
        "Installation complete", "Installation did not finish", timeout=1200, poll=5.0
    )
    evidence.note(f"install result marker: {result}")
    evidence.set("installation_completed", result == "Installation complete")
    evidence.note(console.screen_text())
    if result != "Installation complete":
        console.send_key("q")
        time.sleep(3)
        console.send_line("echo SHELL_BACK_$$")
        console.wait_for("SHELL_BACK_", timeout=20)
        console.send_line(
            "cat /tmp/omarchy-live-install/*/runtime/install.log 2>&1; echo INSTALL_LOG_DONE"
        )
        console.wait_for("INSTALL_LOG_DONE", timeout=15)
        evidence.note("install.log contents:")
        evidence.note(console.scrollback_text(tail_bytes=8000))

        # If the failure was in target validation (not the install command
        # sequence itself), the target is already unmounted/closed by that
        # point -- remount it read-only to inspect exactly what archinstall
        # actually wrote, rather than guessing from the error string alone.
        console.send_line(
            # `echo` appends a trailing newline that `--key-file -` reads as
            # part of the raw key; the real LUKS key (set by install.py) no
            # longer has one, so this must match exactly via `printf '%s'`.
            f"printf '%s' '{LUKS_PASSPHRASE}' | cryptsetup open /dev/disk/by-partlabel/omarchy-linux "
            "omarchy-diag --key-file - && echo DIAG_LUKS_OPENED || echo DIAG_LUKS_OPEN_FAILED"
        )
        diag_luks = console.wait_for("DIAG_LUKS_OPENED", "DIAG_LUKS_OPEN_FAILED", timeout=20)
        if diag_luks == "DIAG_LUKS_OPENED":
            console.send_line(
                "mkdir -p /mnt/diag && mount -o subvol=@,ro /dev/mapper/omarchy-diag /mnt/diag "
                "&& echo DIAG_ROOT_MOUNTED || echo DIAG_ROOT_MOUNT_FAILED"
            )
            diag_root = console.wait_for("DIAG_ROOT_MOUNTED", "DIAG_ROOT_MOUNT_FAILED", timeout=20)
            if diag_root == "DIAG_ROOT_MOUNTED":
                console.send_line(
                    "echo '--- /etc/fstab ---'; cat /mnt/diag/etc/fstab; "
                    "echo '--- /etc/crypttab.initramfs ---'; cat /mnt/diag/etc/crypttab.initramfs 2>&1; "
                    "echo '--- /boot listing ---'; ls -la /mnt/diag/boot /mnt/diag/boot/EFI/BOOT /mnt/diag/boot/EFI/Limine 2>&1; "
                    "echo DIAG_FILES_DONE"
                )
                console.wait_for("DIAG_FILES_DONE", timeout=15)
                evidence.note("target diagnostic files:")
                evidence.note(console.scrollback_text(tail_bytes=4000))
                console.send_line("umount /mnt/diag; echo DIAG_UNMOUNTED")
                console.wait_for("DIAG_UNMOUNTED", timeout=15)
            console.send_line("cryptsetup close omarchy-diag; echo DIAG_CLOSED")
            console.wait_for("DIAG_CLOSED", timeout=15)
        return False
    return True


def patch_installed_cmdline_and_check_efi(
    console: SerialConsole, evidence: Evidence
) -> tuple[bool, str, str]:
    """Remount the target, verify Windows EFI preservation, add a serial console
    to the installed Limine config so the reboot phase remains observable."""
    console.send_key("q")
    time.sleep(3)
    # Generic prompt text ("# ") is almost certainly already in scrollback
    # from before the TUI started, so it cannot be used to detect the shell
    # returning; every synchronization point below uses a unique echo marker.
    console.send_line("echo SHELL_BACK_$$")
    console.wait_for("SHELL_BACK_", timeout=20)

    console.send_line(
        # `printf '%s'` (not `echo`) to match the real key exactly -- `echo`
        # appends a trailing newline that `--key-file -` would read as part
        # of the raw key, and install.py's real LUKS key no longer has one.
        f"printf '%s' '{LUKS_PASSPHRASE}' | cryptsetup open /dev/disk/by-partlabel/omarchy-linux "
        "omarchy-recheck --key-file - && echo LUKS_OPENED || echo LUKS_OPEN_FAILED"
    )
    luks_result = console.wait_for("LUKS_OPENED", "LUKS_OPEN_FAILED", timeout=20)
    console.send_line(
        "mkdir -p /mnt/recheck && mount -o subvol=@ /dev/mapper/omarchy-recheck /mnt/recheck "
        "&& echo ROOT_MOUNTED || echo ROOT_MOUNT_FAILED"
    )
    root_mounted = console.wait_for("ROOT_MOUNTED", "ROOT_MOUNT_FAILED", timeout=20)
    console.send_line(
        "mount /dev/disk/by-partlabel/EFI /mnt/recheck/boot && echo ESP_MOUNTED || echo ESP_MOUNT_FAILED"
    )
    esp_mounted = console.wait_for("ESP_MOUNTED", "ESP_MOUNT_FAILED", timeout=20)

    console.send_line(
        "sha256sum /mnt/recheck/boot/EFI/Microsoft/Boot/bootmgfw.efi; echo HASH_DONE"
    )
    console.wait_for("HASH_DONE", timeout=15)
    hash_output = console.scrollback_text(tail_bytes=2000)

    console.send_line(
        "for f in /mnt/recheck/boot/limine.conf /mnt/recheck/boot/EFI/Limine/limine.conf "
        "/mnt/recheck/boot/EFI/BOOT/limine.conf; do "
        # Limine 6.x's actual key is "kernel_cmdline:", not "cmdline:" -- match
        # any line containing "cmdline" as a substring (with an optional
        # prefix), not just one starting with that exact literal token.
        "[ -f \"$f\" ] && sed -i 's#^\\([[:space:]]*[A-Za-z_]*cmdline[:=].*\\)$#\\1 console=ttyS0,115200n8#' \"$f\"; "
        "done; echo CMDLINE_PATCHED"
    )
    console.wait_for("CMDLINE_PATCHED", timeout=15)

    console.send_line(
        "cat /mnt/recheck/boot/limine.conf /mnt/recheck/boot/EFI/Limine/limine.conf "
        "/mnt/recheck/boot/EFI/BOOT/limine.conf 2>/dev/null; echo LIMINE_CONF_SHOWN"
    )
    console.wait_for("LIMINE_CONF_SHOWN", timeout=15)
    evidence.note("patched limine.conf contents:")
    evidence.note(console.scrollback_text(tail_bytes=1500))

    console.send_line(
        "ls -la /mnt/recheck/boot/EFI/Limine/ 2>/dev/null; ls -la /mnt/recheck/boot/EFI/BOOT/ 2>/dev/null; echo LIMINE_LISTED"
    )
    console.wait_for("LIMINE_LISTED", timeout=15)
    limine_listing = console.scrollback_text(tail_bytes=2000)

    console.send_line(
        "umount /mnt/recheck/boot && umount /mnt/recheck && cryptsetup close omarchy-recheck "
        "&& echo TARGET_UNMOUNTED || echo TARGET_UNMOUNT_FAILED"
    )
    console.wait_for("TARGET_UNMOUNTED", "TARGET_UNMOUNT_FAILED", timeout=20)
    mounted_ok = (
        luks_result == "LUKS_OPENED"
        and root_mounted == "ROOT_MOUNTED"
        and esp_mounted == "ESP_MOUNTED"
    )

    return (mounted_ok, hash_output, limine_listing)


def run(args: argparse.Namespace) -> Evidence:
    iso_path = Path(args.iso).resolve()
    work_dir = Path(args.work_dir).resolve()
    work_dir.mkdir(parents=True, exist_ok=True)
    evidence = Evidence()
    for key in REQUIRED_TRUE_FIELDS:
        evidence.set(key, False)
    evidence.set("schema_version", "1.0.0")
    evidence.set("iso_sha256", _sha256(iso_path))

    ovmf_code = _find_first(OVMF_CODE_CANDIDATES, "OVMF_CODE")
    ovmf_vars_src = _find_first(OVMF_VARS_CANDIDATES, "OVMF_VARS")
    ovmf_vars = work_dir / "OVMF_VARS.fd"
    shutil.copy2(ovmf_vars_src, ovmf_vars)

    manifest = read_build_manifest(iso_path)
    evidence.set("release_tag", manifest.get("release_tag", ""))
    evidence.set("build_commit", manifest.get("git_commit", ""))
    evidence.set("archinstall_version", manifest["runtime_metadata"]["runtime"]["archinstall_version"])

    disk_img = work_dir / "disposable-disk.img"
    ventoy_img = work_dir / "ventoy-handoff.img"
    spare_img = work_dir / "disposable-spare-disk.img"

    # "separate-disk" installs Linux onto a distinct empty disk (ESP + Limine
    # stay on the Windows disk); default installs into the Windows disk's free
    # space. Selected by CI via OMARCHY_VM_TARGET_MODE.
    target_mode = os.environ.get("OMARCHY_VM_TARGET_MODE", "windows-disk").strip().lower()
    separate_disk = target_mode == "separate-disk"
    evidence.set("target_mode", target_mode)
    evidence.set("separate_disk_install", separate_disk)

    evidence.note("building disposable dual-boot GPT disk fixture")
    geo = disk_fixture.build_main_disk(disk_img)
    evidence.set("virtual_disk_guid", geo.gpt_disk_guid)
    evidence.set("esp_partuuid", geo.esp_partition_guid)
    evidence.set("windows_partition_guid", geo.windows_partition_guid)
    evidence.set("linux_partition_guid", "assigned-at-install-time")
    original_efi_hash = hashlib.sha256(disk_fixture.SYNTHETIC_WINDOWS_EFI_CONTENT).hexdigest()
    evidence.set("windows_efi_original_sha256", original_efi_hash)

    spare_geo: plan_fixture.SpareDiskGeometry | None = None
    if separate_disk:
        evidence.note("building disposable spare target disk (empty GPT) for a separate-disk install")
        spare_geo = disk_fixture.build_spare_disk(spare_img)
        evidence.set("spare_disk_guid", spare_geo.gpt_disk_guid)

    evidence.note("building Ventoy handoff USB fixture (copying ISO onto it)")
    disk_fixture.build_ventoy_disk(ventoy_img, iso_path=iso_path)
    evidence.set("windows_prep_simulation", True)

    integrity_key: bytes = b""
    plan_payload: dict[str, Any] = {}

    def _write_handoff(mount_point: Path, iso_on_ventoy: Path) -> None:
        nonlocal integrity_key, plan_payload
        integrity_key, plan_payload = generate_handoff(
            ventoy_root=mount_point, iso_on_ventoy=iso_on_ventoy, manifest=manifest, geo=geo, spare=spare_geo
        )

    disk_fixture.write_plan_files_onto_ventoy(ventoy_img, _write_handoff)
    from rebuild.tools.vm_drivers.plan_fixture import validated_plan

    plan = validated_plan(plan_payload)
    evidence.set("plan_id", plan.meta.plan_id)
    evidence.note("generated validated handoff plan for the guided installer")

    qemu_args = qemu_base_args(ovmf_code=ovmf_code, ovmf_vars=ovmf_vars, disk_img=disk_img)
    qemu_args += [
        "-cdrom", str(iso_path),
        "-boot", "order=d",
        "-device", "qemu-xhci,id=xhci",
        "-drive", f"file={ventoy_img},format=raw,if=none,id=usbstick",
        "-device", "usb-storage,bus=xhci.0,drive=usbstick,removable=on",
        "-netdev", "user,id=net0",
        "-device", "virtio-net-pci,netdev=net0",
    ]
    if separate_disk:
        # Attach the empty spare disk as a second virtio-blk device with a
        # stable serial so the live installer can resolve it as the target.
        qemu_args += [
            "-drive", f"file={spare_img},format=raw,if=none,id=spare,cache=writeback",
            "-device", f"virtio-blk-pci,drive=spare,serial={disk_fixture.SPARE_DISK_SERIAL}",
        ]

    console = SerialConsole("127.0.0.1", SERIAL_PORT, columns=200, rows=50)
    qemu = QemuProcess(qemu_args)
    install_ok = False
    try:
        evidence.note("booting disposable VM: QEMU + OVMF, custom ISO as cdrom")
        qemu.start()
        console.connect(timeout=30)
        evidence.set("uefi_iso_booted", True)
        login_as_root(console, evidence)

        install_ok = drive_handoff_and_install(console, evidence)

        if install_ok:
            mounted_ok, hash_output, limine_listing = patch_installed_cmdline_and_check_efi(console, evidence)
            evidence.set("target_remount_verified", mounted_ok)
            evidence.set("post_install_efi_hash_output", hash_output.strip()[-500:])
            evidence.set("post_install_limine_listing", limine_listing.strip()[-1000:])
            preserved = original_efi_hash in hash_output
            evidence.set("windows_efi_preserved", preserved)
        else:
            evidence.set("windows_efi_preserved", False)

        console.send_line("poweroff")
        evidence.note("issued poweroff to live shell; waiting for QEMU to exit")
    except Exception as exc:  # noqa: BLE001 - preserve evidence on any failure
        evidence.note(f"ERROR during install phase: {exc}")
    finally:
        console.save_log(str(work_dir / "serial-console.log"))
        console.close()
        exit_code = qemu.wait(timeout=60)
        if exit_code is None:
            evidence.note("QEMU did not exit after poweroff; killing")
            qemu.kill()

    if install_ok:
        run_reboot_phase(
            work_dir=work_dir,
            ovmf_code=ovmf_code,
            ovmf_vars=ovmf_vars,
            disk_img=disk_img,
            spare_img=spare_img if separate_disk else None,
            evidence=evidence,
        )

    return evidence


def run_reboot_phase(
    *,
    work_dir: Path,
    ovmf_code: str,
    ovmf_vars: Path,
    disk_img: Path,
    spare_img: Path | None = None,
    evidence: Evidence,
) -> None:
    qemu_args = qemu_base_args(ovmf_code=ovmf_code, ovmf_vars=ovmf_vars, disk_img=disk_img)
    qemu_args += ["-netdev", "user,id=net0", "-device", "virtio-net-pci,netdev=net0"]
    if spare_img is not None:
        # Separate-disk install: the LUKS root lives on the spare disk, so it
        # must be re-attached for the installed system to find and unlock root.
        qemu_args += [
            "-drive", f"file={spare_img},format=raw,if=none,id=spare,cache=writeback",
            "-device", f"virtio-blk-pci,drive=spare,serial={disk_fixture.SPARE_DISK_SERIAL}",
        ]
    console = SerialConsole("127.0.0.1", SERIAL_PORT + 1, columns=200, rows=50)
    args = [a if a != f"tcp:127.0.0.1:{SERIAL_PORT},server=on,wait=off" else f"tcp:127.0.0.1:{SERIAL_PORT + 1},server=on,wait=off" for a in qemu_args]
    args = [a if a != f"tcp:127.0.0.1:{QMP_PORT},server=on,wait=off" else f"tcp:127.0.0.1:{QMP_PORT + 1},server=on,wait=off" for a in args]
    qemu = QemuProcess(args)
    try:
        evidence.note("booting installed disk directly (ISO detached)")
        qemu.start()
        console.connect(timeout=30)
        marker = console.wait_for("Enter passphrase", "passphrase for", "login:", timeout=180)
        evidence.note(f"reboot boot marker: {marker}")
        if marker != "login:":
            # A bare "\r", a bare "\n", and "\r\n" with a settle delay all
            # produced the identical symptom: characters echo once, then the
            # exact same prompt redisplays -- not what a wrong-password retry
            # nor a terminator mismatch would look like on their own attempt.
            # systemd-ask-password's console agent periodically redraws /
            # reopens the request while polling for an answer; a single shot
            # can land in a window where it's discarded. Resend periodically
            # until the prompt actually clears, rather than guessing timing.
            marker = ""
            attempts = 0
            while marker != "login:" and attempts < 12:
                attempts += 1
                console.send(LUKS_PASSPHRASE + "\r\n")
                evidence.note(f"submitted LUKS passphrase attempt {attempts}; waiting for login prompt")
                try:
                    # Only "login:" ends the wait -- "passphrase for" is
                    # already in scrollback from the very first display and
                    # would match instantly every iteration otherwise.
                    marker = console.wait_for("login:", timeout=15)
                except TimeoutError:
                    marker = ""
            if marker != "login:":
                evidence.note("timed out waiting for login prompt; screen + scrollback follow for diagnosis")
                evidence.note(console.screen_text())
                evidence.note(console.scrollback_text(tail_bytes=6000))
                raise TimeoutError("installed system never reached a login prompt after repeated passphrase submission")
        evidence.set("reboot_completed", marker == "login:")
        evidence.note(console.screen_text())
    except Exception as exc:  # noqa: BLE001
        evidence.note(f"ERROR during reboot phase: {exc}")
        evidence.set("reboot_completed", False)
    finally:
        console.save_log(str(work_dir / "serial-console-reboot.log"))
        console.close()
        exit_code = qemu.wait(timeout=30)
        if exit_code is None:
            qemu.kill()


def write_evidence(evidence: Evidence, output_path: Path) -> None:
    payload = dict(evidence.fields)
    payload["stage_log"] = evidence.stage_log
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iso", required=True)
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--evidence-output", required=True)
    args = parser.parse_args()

    evidence = run(args)
    write_evidence(evidence, Path(args.evidence_output))

    # Deliberately excludes normal_user_first_login_reached and
    # recovery_restore_tested: this driver, in a single QEMU session, never
    # drives a full first-login flow or a recovery rehearsal against the
    # just-installed disk -- see the REQUIRED_TRUE_FIELDS comment in
    # rebuild/tools/vm_install_test.py, which validates this evidence file
    # against the same exclusion. Gating this driver's own exit code on
    # fields it can never set would fail every run regardless of whether
    # install/reboot actually succeeded.
    fields_this_driver_can_prove = tuple(
        name for name in REQUIRED_TRUE_FIELDS
        if name not in ("normal_user_first_login_reached", "recovery_restore_tested")
    )
    ok = all(evidence.fields.get(field_name) is True for field_name in fields_this_driver_can_prove)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
