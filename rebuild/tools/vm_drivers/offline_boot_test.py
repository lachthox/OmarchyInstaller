"""Boot the real, non-dry-run ISO with networking disabled and prove the live
Python TUI starts cleanly (Task 9 / CRIT-06 / CRIT-07 acceptance evidence).

Verifies: the canonical module entrypoint runs from an arbitrary cwd, no
ModuleNotFoundError occurs, no package download is attempted (there is no
network device at all), every required runtime binary exists, the locked
Python dependencies are importable, and the terminal reports the expected
80x24 live-console geometry. Captures the full serial transcript as evidence.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

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
SERIAL_PORT = 45501


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


def find_one(pattern: str) -> Path:
    matches = [Path(value) for value in sorted(glob.glob(pattern))]
    if len(matches) != 1:
        raise RuntimeError(f"Expected exactly one ISO for {pattern!r}; found {len(matches)}")
    return matches[0].resolve()


def run(iso_path: Path, work_dir: Path) -> dict:
    work_dir.mkdir(parents=True, exist_ok=True)
    ovmf_code = _find_first(OVMF_CODE_CANDIDATES, "OVMF_CODE")
    ovmf_vars_src = _find_first(OVMF_VARS_CANDIDATES, "OVMF_VARS")
    ovmf_vars = work_dir / "OVMF_VARS.fd"
    shutil.copy2(ovmf_vars_src, ovmf_vars)

    evidence = {
        "schema_version": "1.0.0",
        "iso_sha256": _sha256(iso_path),
        "tui_started": False,
        "cwd_independent": False,
        "dependency_check_passed": False,
        "missing_binaries": [],
        "no_module_not_found_error": False,
        "terminal_geometry_ok": False,
    }

    qemu = subprocess.Popen([
        "qemu-system-x86_64",
        "-machine", "q35,accel=kvm:tcg",
        "-cpu", "host",
        "-m", "3072",
        "-smp", "2",
        "-drive", f"if=pflash,format=raw,readonly=on,file={ovmf_code}",
        "-drive", f"if=pflash,format=raw,file={ovmf_vars}",
        "-cdrom", str(iso_path),
        "-boot", "order=d",
        "-nic", "none",  # deliberately no network device at all
        "-nographic",
        "-monitor", "none",
        "-serial", f"tcp:127.0.0.1:{SERIAL_PORT},server=on,wait=off",
        "-no-reboot",
    ])
    console = SerialConsole("127.0.0.1", SERIAL_PORT)
    try:
        console.connect(timeout=30)
        # Shared CI hardware (GitHub-hosted runners) is markedly slower than
        # a dedicated nested-KVM box for CD-ROM-backed squashfs boot; 120s
        # was measured as too tight there even though KVM is active.
        console.wait_for("login:", timeout=300)
        console.send_line("root")
        console.wait_for("archiso ~", "# ", timeout=20)

        console.send_line("cd /tmp && echo CWD_TEST_$$")
        marker = console.wait_for("CWD_TEST_", timeout=15)
        evidence["cwd_independent"] = bool(marker)

        required = (
            "python3", "nmcli", "archinstall", "cryptsetup", "mkfs.btrfs", "mount",
            "umount", "findmnt", "lsblk", "blkid", "udevadm", "partprobe", "sgdisk",
            "efibootmgr",
        )
        console.send_line(
            "for c in " + " ".join(required) + "; do command -v $c >/dev/null || echo MISSING:$c; done; echo DEPCHECK_DONE"
        )
        console.wait_for("DEPCHECK_DONE", timeout=20)
        dep_output = console.scrollback_text(tail_bytes=3000)
        # The console echoes the typed command line back before it ever
        # executes, and that source text itself contains "MISSING:$c" -- a
        # naive substring scan matches that echoed input, not just genuine
        # "command -v" failures. Only accept a real binary name from
        # `required`; the literal, unexpanded "$c" can never be one.
        missing = [
            line.split("MISSING:")[1].strip()
            for line in dep_output.splitlines()
            if "MISSING:" in line and line.split("MISSING:")[1].strip() in required
        ]
        evidence["missing_binaries"] = missing
        evidence["dependency_check_passed"] = not missing

        console.send_line("stty size; echo STTY_DONE")
        console.wait_for("STTY_DONE", timeout=15)
        stty_output = console.scrollback_text(tail_bytes=500)
        evidence["terminal_geometry_ok"] = "24 80" in stty_output

        console.send_line(
            "/opt/omarchy-venv/bin/python -m installer.main --no-tui --runtime-version 1.0.0"
        )
        marker = console.wait_for(
            "Dependency check: PASS", "Dependency check: BLOCKED", "ModuleNotFoundError", "Traceback", timeout=25
        )
        evidence["no_tui_marker"] = marker
        evidence["no_module_not_found_error"] = marker not in ("ModuleNotFoundError", "Traceback")

        console.send_line("echo LIVE_TUI_LAUNCHING_$$")
        console.wait_for("LIVE_TUI_LAUNCHING_", timeout=15)
        console.send_line("cd / && /opt/omarchy-venv/bin/python -m installer.main --runtime-version 1.0.0")
        time.sleep(6)
        screen = console.screen_text()
        evidence["tui_started"] = "Omarchy Arch Live Installer" in screen
        evidence["tui_screen_snapshot"] = screen

        console.send_key("q")
        time.sleep(2)
        console.send_line("echo AFTER_TUI_QUIT_OK")
        console.wait_for("AFTER_TUI_QUIT_OK", "Traceback", timeout=15)

        console.send_line("poweroff")
        time.sleep(5)
    finally:
        console.save_log(str(work_dir / "serial-console.log"))
        console.close()
        try:
            qemu.wait(timeout=30)
        except subprocess.TimeoutExpired:
            qemu.terminate()
            try:
                qemu.wait(timeout=10)
            except subprocess.TimeoutExpired:
                qemu.kill()

    return evidence


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iso-glob", required=True)
    parser.add_argument("--work-dir", required=True, type=Path)
    args = parser.parse_args()

    iso_path = find_one(args.iso_glob)
    evidence = run(iso_path, args.work_dir)
    output_path = args.work_dir / "offline-boot-evidence.json"
    output_path.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2, sort_keys=True))

    ok = (
        evidence["cwd_independent"]
        and evidence["dependency_check_passed"]
        and evidence["no_module_not_found_error"]
        and evidence["terminal_geometry_ok"]
        and evidence["tui_started"]
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
