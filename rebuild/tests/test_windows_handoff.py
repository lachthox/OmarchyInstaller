from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import subprocess
import zipfile

import pytest

import rebuild.installer.platforms.windows.handoff as handoff
from rebuild.installer.platforms.windows.handoff import (
    _usb_layout_script,
    VentoyCliInfo,
    VentoyError,
    VentoyUsbValidation,
    build_usb_erase_confirmation,
    copy_iso_to_ventoy_root,
    download_official_ventoy_cli,
    install_ventoy_to_usb,
    stage_ventoy_handoff_bundle,
)
from rebuild.installer.shared.validation import validate_plan_contract


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_usb_layout_script_has_no_duplicate_disk_size_key() -> None:
    script = _usb_layout_script(1)

    assert script.count("size_bytes = [int64]$disk.Size") == 1


def device_payload(
    *,
    bus_type: str = "USB",
    serial: str = "USB-SERIAL",
    disk_guid: str = "usb-guid",
    is_system: bool = False,
) -> dict[str, object]:
    return {
        "disk_number": 7,
        "bus_type": bus_type,
        "partition_style": "GPT",
        "size_bytes": 64 * 1024**3,
        "partition_count": 2,
        "model": "Fixture USB",
        "serial": serial,
        "disk_guid": disk_guid,
        "is_boot": False,
        "is_system": is_system,
        "contains_pagefile": False,
        "partitions": [],
    }


class LayoutRunner:
    def __init__(self, *layouts: dict[str, object]) -> None:
        self.layouts = list(layouts)
        self.commands: list[list[str]] = []

    def run(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        if command[0] == "powershell.exe":
            payload = self.layouts.pop(0) if len(self.layouts) > 1 else self.layouts[0]
            return subprocess.CompletedProcess(command, 0, json.dumps(payload), "")
        return subprocess.CompletedProcess(command, 0, "installed", "")


class FakeVentoyDownloader:
    def __init__(self, archive: bytes, *, advertised_hash: str | None = None) -> None:
        self.archive = archive
        digest = advertised_hash or hashlib.sha256(archive).hexdigest()
        self.release = {
            "tag_name": "v1.2.3",
            "assets": [
                {
                    "name": "ventoy-1.2.3-windows.zip",
                    "browser_download_url": (
                        "https://github.com/ventoy/Ventoy/releases/download/"
                        "v1.2.3/ventoy-1.2.3-windows.zip"
                    ),
                    "digest": f"sha256:{digest}",
                },
                {
                    "name": "sha256.txt",
                    "browser_download_url": (
                        "https://github.com/ventoy/Ventoy/releases/download/v1.2.3/sha256.txt"
                    ),
                },
            ],
        }
        self.checksums = f"{digest}  ventoy-1.2.3-windows.zip\n"
        self.download_count = 0

    def fetch_json(self, _url: str) -> dict:
        return self.release

    def fetch_text(self, _url: str) -> str:
        return self.checksums

    def download(self, _url: str, destination: Path) -> None:
        self.download_count += 1
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(self.archive)


def ventoy_zip() -> bytes:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("ventoy-1.2.3/Ventoy2Disk.exe", b"fixture executable")
        archive.writestr("ventoy-1.2.3/ventoy/ventoy.disk.img.xz", b"fixture image")
    return payload.getvalue()


def plan():
    payload = json.loads(
        (REPO_ROOT / "rebuild" / "assets" / "templates" / "plan.template.json").read_text(
            encoding="utf-8"
        )
    )
    return validate_plan_contract(payload)


def test_internal_disk_is_rejected_before_ventoy_command() -> None:
    runner = LayoutRunner(device_payload(bus_type="NVME", is_system=True))

    with pytest.raises(VentoyError, match="non-USB"):
        install_ventoy_to_usb(7, runner=runner, confirmation="ERASE ANYTHING")

    assert runner.commands
    assert all("Ventoy2Disk" not in command[0] for command in runner.commands)


def test_wrong_typed_confirmation_blocks_before_acquisition() -> None:
    runner = LayoutRunner(device_payload())

    with pytest.raises(VentoyError, match="Typed confirmation"):
        install_ventoy_to_usb(7, runner=runner, confirmation="ERASE WRONG")
    assert len(runner.commands) == 1


def test_guided_erase_confirmation_is_bound_to_live_usb_identity() -> None:
    payload = device_payload()
    runner = LayoutRunner(payload)

    confirmation = build_usb_erase_confirmation(7, runner=runner)

    assert confirmation == f"ERASE {handoff._stable_device_identifier(payload)}"
    assert len(runner.commands) == 1


def test_official_ventoy_download_is_verified_cached_and_extracted(tmp_path: Path) -> None:
    downloader = FakeVentoyDownloader(ventoy_zip())

    executable = download_official_ventoy_cli(downloader=downloader, cache_root=tmp_path)

    assert executable.read_bytes() == b"fixture executable"
    assert (executable.parent / "ventoy" / "ventoy.disk.img.xz").is_file()
    assert downloader.download_count == 1

    second = download_official_ventoy_cli(downloader=downloader, cache_root=tmp_path)
    assert second == executable
    assert downloader.download_count == 1


def test_official_ventoy_download_rejects_hash_mismatch(tmp_path: Path) -> None:
    downloader = FakeVentoyDownloader(ventoy_zip(), advertised_hash="0" * 64)

    with pytest.raises(VentoyError, match="SHA256 mismatch"):
        download_official_ventoy_cli(downloader=downloader, cache_root=tmp_path)

    assert not (tmp_path / "ventoy-1.2.3-windows.zip").exists()


def test_identity_change_immediately_before_write_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = LayoutRunner(device_payload(), device_payload(serial="DIFFERENT"))
    identifier = handoff._stable_device_identifier(device_payload())
    monkeypatch.setattr(
        handoff,
        "acquire_ventoy_cli",
        lambda **_kwargs: VentoyCliInfo("Ventoy2Disk.exe", "fixture"),
    )

    with pytest.raises(VentoyError, match="identity changed"):
        install_ventoy_to_usb(7, runner=runner, confirmation=f"ERASE {identifier}")
    assert all(command[0] != "Ventoy2Disk.exe" for command in runner.commands)


def test_ventoy_command_occurs_only_after_two_matching_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = device_payload()
    runner = LayoutRunner(payload, payload)
    identifier = handoff._stable_device_identifier(payload)
    validation = VentoyUsbValidation(
        disk_number=7,
        bus_type="USB",
        partition_style="GPT",
        partition_count=2,
        data_drive_letter="V",
        data_root="V:/",
        filesystem="EXFAT",
        free_bytes=1,
        required_bytes=1,
        payload_bytes=0,
        writable=True,
        structure_verified=True,
        warnings=(),
        stable_identifier=identifier,
    )
    monkeypatch.setattr(
        handoff,
        "acquire_ventoy_cli",
        lambda **_kwargs: VentoyCliInfo("Ventoy2Disk.exe", "fixture"),
    )
    monkeypatch.setattr(handoff, "validate_ventoy_usb", lambda *_args, **_kwargs: validation)

    result = install_ventoy_to_usb(7, runner=runner, confirmation=f"ERASE {identifier}")

    assert result.validation.stable_identifier == identifier
    assert runner.commands[0][0] == "powershell.exe"
    assert runner.commands[1][0] == "powershell.exe"
    assert runner.commands[2][0] == "Ventoy2Disk.exe"


def test_iso_copy_verifies_source_and_destination_hash(tmp_path: Path) -> None:
    source = tmp_path / "source.iso"
    source.write_bytes(b"verified iso")

    destination = copy_iso_to_ventoy_root(source, tmp_path / "ventoy")

    assert hashlib.sha256(source.read_bytes()).digest() == hashlib.sha256(destination.read_bytes()).digest()


def test_corrupt_iso_copy_is_removed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = tmp_path / "source.iso"
    source.write_bytes(b"correct")

    def corrupt_copy(_source: Path, destination: Path) -> None:
        destination.write_bytes(b"corrupt")

    monkeypatch.setattr(handoff.shutil, "copy2", corrupt_copy)
    destination = tmp_path / "ventoy" / source.name

    with pytest.raises(VentoyError, match="SHA256"):
        copy_iso_to_ventoy_root(source, destination.parent)
    assert not destination.exists()


def test_fat32_rejects_sparse_file_over_four_gib(tmp_path: Path) -> None:
    source = tmp_path / "large.iso"
    with source.open("wb") as handle:
        handle.seek(handoff.FAT32_MAX_FILE_BYTES)
        handle.write(b"x")

    with pytest.raises(VentoyError, match="FAT32 maximum"):
        copy_iso_to_ventoy_root(source, tmp_path / "ventoy", filesystem="FAT32")


def test_handoff_is_hash_bound_without_manual_key(tmp_path: Path) -> None:
    source = tmp_path / "release.iso"
    source.write_bytes(b"release")
    result = stage_ventoy_handoff_bundle(
        tmp_path / "ventoy",
        source,
        plan(),
        filesystem="EXFAT",
    )

    manifest_path = Path(result.handoff_manifest_path or "")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "1.1.0"
    assert "hmac_sha256" not in manifest
    assert manifest["file_sha256"]["iso"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert manifest["file_sha256"]["plan"] == hashlib.sha256(
        Path(result.plan_path).read_bytes()
    ).hexdigest()


def test_plaintext_wifi_handoff_is_disabled(tmp_path: Path) -> None:
    source = tmp_path / "release.iso"
    source.write_bytes(b"release")

    with pytest.raises(VentoyError, match="Plaintext Wi-Fi"):
        stage_ventoy_handoff_bundle(
            tmp_path / "ventoy",
            source,
            plan(),
            wifi_profile={"ssid": "home", "password": "secret"},
            integrity_key=b"k" * 32,
        )
