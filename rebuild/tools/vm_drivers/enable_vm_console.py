"""Opt-in post-build step: add a serial console to the ISO's systemd-boot entries.

Production ISO builds never call this. It exists solely so an isolated VM test
runner (OMARCHY_ISOLATED_VM_DRIVER and friends) can observe and drive the live
Textual TUI over a QEMU serial line -- the production kernel/boot entries are
otherwise untouched; this only appends `console=ttyS0,115200n8` so kernel and
TUI output also reaches the serial port in addition to the normal VGA console.

This is a deliberate, reviewable CI-only hook (see docs/testing.md), not a
runtime behavior change: it edits the ISO's embedded FAT-formatted EFI System
Partition (the isohybrid image's real UEFI boot medium) in place, after the
production build has already produced and hashed the ISO.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


SERIAL_CONSOLE_ARGS = "console=ttyS0,115200n8 console=tty0"


def _run(command: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=True, **kwargs)


def _find_esp_partition(iso_path: Path) -> tuple[int, int]:
    """Return (byte_offset, byte_size) of the embedded FAT EFI System Partition."""
    completed = _run(["sfdisk", "-J", str(iso_path)])
    payload = json.loads(completed.stdout)
    partitions = payload.get("partitiontable", {}).get("partitions", [])
    sector_size = int(payload.get("partitiontable", {}).get("sectorsize", 512))
    for partition in partitions:
        part_type = str(partition.get("type", "")).lower()
        if part_type in {"ef", "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"}:
            start = int(partition["start"]) * sector_size
            size = int(partition["size"]) * sector_size
            return start, size
    raise RuntimeError("Could not locate an EFI System Partition inside the ISO's partition table.")


def _patch_loader_entry(text: str) -> str:
    lines = text.splitlines()
    out = []
    patched = False
    for line in lines:
        if line.strip().startswith("options"):
            if SERIAL_CONSOLE_ARGS not in line:
                line = line.rstrip() + f" {SERIAL_CONSOLE_ARGS}"
            patched = True
        out.append(line)
    if not patched:
        out.append(f"options  {SERIAL_CONSOLE_ARGS}")
    return "\n".join(out) + "\n"


def enable_vm_console(iso_path: Path) -> None:
    offset, size = _find_esp_partition(iso_path)
    with tempfile.TemporaryDirectory(prefix="omarchy-vm-console-") as tmp:
        mount_point = Path(tmp) / "esp"
        mount_point.mkdir()
        loop_dev = _run(
            ["losetup", "--show", "-f", "-o", str(offset), "--sizelimit", str(size), str(iso_path)]
        ).stdout.strip()
        try:
            _run(["mount", "-o", "rw", loop_dev, str(mount_point)])
            try:
                entries_dir = mount_point / "loader" / "entries"
                if not entries_dir.is_dir():
                    raise RuntimeError(f"No loader/entries directory inside embedded ESP at {mount_point}")
                edited = []
                for conf in sorted(entries_dir.glob("*.conf")):
                    original = conf.read_text(encoding="utf-8")
                    updated = _patch_loader_entry(original)
                    if updated != original:
                        conf.write_text(updated, encoding="utf-8")
                        edited.append(conf.name)
                if not edited:
                    raise RuntimeError("No loader entries were patched; refusing to claim success silently.")
            finally:
                _run(["umount", str(mount_point)])
        finally:
            _run(["losetup", "-d", loop_dev])


def refresh_manifest_hash(iso_path: Path, manifest_path: Path) -> str:
    digest = hashlib.sha256()
    with iso_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    new_sha256 = digest.hexdigest()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["output_iso"]["sha256"] = new_sha256
    manifest["vm_test_console_enabled"] = True
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    sidecar = iso_path.parent / f"{iso_path.name}.sha256"
    sidecar.write_text(f"{new_sha256}  {iso_path.name}\n", encoding="utf-8")
    return new_sha256


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iso", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    if shutil.which("losetup") is None or shutil.which("sfdisk") is None:
        print("losetup/sfdisk are required to patch the embedded ESP.", file=sys.stderr)
        return 1
    enable_vm_console(args.iso)
    new_hash = refresh_manifest_hash(args.iso, args.manifest)
    print(f"VM test serial console enabled. Updated ISO SHA256: {new_hash}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
