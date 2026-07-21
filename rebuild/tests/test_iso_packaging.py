from __future__ import annotations

import json
from pathlib import Path

from rebuild.tools.build_iso_pipeline import (
    ARCH_MIRROR_DEFAULT,
    LIVE_ENTRYPOINT,
    SUPPORTED_ARCHINSTALL,
    SUPPORTED_ARCH_ISO,
    IsoDescriptor,
    pinned_iso,
    prepare_payload,
)


WORKSPACE = Path(__file__).resolve().parents[2]


def test_source_iso_and_archinstall_contract_are_pinned() -> None:
    assert pinned_iso() == (
        "archlinux-2026.07.01-x86_64.iso",
        SUPPORTED_ARCH_ISO,
    )
    assert ARCH_MIRROR_DEFAULT.endswith(f"/iso/{SUPPORTED_ARCH_ISO}")
    assert SUPPORTED_ARCHINSTALL == "4.4-1"


def test_payload_has_one_cwd_independent_entrypoint(tmp_path: Path) -> None:
    iso = IsoDescriptor(
        name="archlinux-2026.07.01-x86_64.iso",
        date=SUPPORTED_ARCH_ISO,
        iso_url="https://example.invalid/pinned.iso",
        sha_url="https://example.invalid/sha256sums.txt",
        expected_sha256="abc123",
    )
    metadata = prepare_payload(WORKSPACE, tmp_path / "payload", iso, "commit", "1.2.3", "v1.2.3")

    runtime = metadata["runtime"]
    assert runtime["entrypoint"] == LIVE_ENTRYPOINT
    assert "compat_alias" not in runtime
    assert runtime["python_requirements_file"].endswith("requirements.lock")
    assert runtime["archinstall_version"] == SUPPORTED_ARCHINSTALL
    assert (tmp_path / "payload" / "main.py").exists() is False
    assert LIVE_ENTRYPOINT in (tmp_path / "payload" / "launch-installer").read_text(
        encoding="utf-8"
    )
    assert (tmp_path / "payload" / "assets" / "scripts" / "first-login-profile.sh").is_file()

    serialized = json.dumps(metadata)
    assert "/opt/omarchy-installer" in serialized
    assert "/opt/omarchy-setup" not in serialized


def test_iso_build_keeps_signatures_and_verifies_runtime() -> None:
    script = (WORKSPACE / "build-custom-iso.sh").read_text(encoding="utf-8")
    assert "SigLevel = Never" not in script
    assert "archive.archlinux.org/repos/2026/07/01" in script
    assert 'pacman -Q archinstall' in script
    assert '== "4.4-1"' in script
    assert "--require-hashes" in script
    assert "trap cleanup EXIT INT TERM" in script
    for command in (
        "cryptsetup",
        "mkfs.btrfs",
        "findmnt",
        "lsblk",
        "blkid",
        "udevadm",
        "partprobe",
        "sgdisk",
        "efibootmgr",
    ):
        assert command in script


def test_runtime_lock_is_exact_and_hashed() -> None:
    lock = (WORKSPACE / "rebuild" / "requirements.lock").read_text(encoding="utf-8")
    assert ">=" not in lock
    assert "--hash=sha256:" in lock
