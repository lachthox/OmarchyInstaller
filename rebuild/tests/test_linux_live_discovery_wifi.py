from __future__ import annotations

import json
from pathlib import Path

try:
    from rebuild.installer.platforms.linux_live.discovery import (
        HandoffValidationContext,
        discover_and_validate_handoff_plan,
    )
except ModuleNotFoundError:  # pragma: no cover - fallback for package-local test runs
    from installer.platforms.linux_live.discovery import (
        HandoffValidationContext,
        discover_and_validate_handoff_plan,
    )


def _plan_payload() -> dict[str, object]:
    return {
        "meta": {
            "schema_version": "0.1.0",
            "producer_version": "0.1.0",
            "generated_at_utc": "2026-03-30T00:00:00Z",
            "build_commit": "",
            "release_tag": "",
        },
        "disk_identity": {
            "disk_serial": "SER-001",
            "disk_model": "TestDisk",
            "disk_size_bytes": 512000000000,
            "gpt_disk_guid": "GUID-001",
            "partition_style": "GPT",
        },
        "efi_identity": {
            "partition_guid": "EFI-GUID-001",
            "partuuid": "EFI-PARTUUID-001",
            "filesystem": "vfat",
            "start_sector": 2048,
            "end_sector": 4095,
            "size_bytes": 1048576,
        },
        "windows_partition_identity": {
            "partition_guid": "WIN-GUID-001",
            "partuuid": "WIN-PARTUUID-001",
            "filesystem": "ntfs",
            "start_sector": 4096,
            "end_sector": 999999,
            "size_bytes": 200000000000,
        },
        "prepared_free_space_range": {
            "start_sector": 4096,
            "end_sector": 8191,
            "size_bytes": 2097152,
        },
        "user_choices": {
            "hostname": "omarchy-test",
            "username": "tester",
            "timezone": "UTC",
            "locale": "en_US",
            "kb_layout": "us",
            "bootloader": "limine",
        },
        "network": None,
        "omarchy_assumptions": {},
        "compatibility": {
            "schema_version": "0.1.0",
            "minimum_windows_prep_version": "0.1.0",
            "minimum_live_runtime_version": "0.1.0",
            "required_plan_schema_version": "0.1.0",
            "bootstrap_expectation": "post-install-only",
            "ventoy_handoff_path": "omarchy/plan.json",
        },
    }


def test_discovery_loads_valid_wifi_profile(tmp_path: Path) -> None:
    root = tmp_path / "ventoy"
    omarchy = root / "omarchy"
    omarchy.mkdir(parents=True, exist_ok=True)
    (omarchy / "plan.json").write_text(json.dumps(_plan_payload(), indent=2) + "\n", encoding="utf-8")
    (omarchy / "wifi.json").write_text(
        json.dumps(
            {
                "ssid": "HomeNet",
                "passphrase": "secret-pass",
                "wifi_security": "wpa2",
                "interface_name": "wlan0",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    result = discover_and_validate_handoff_plan(
        HandoffValidationContext(live_runtime_version="0.1.0", max_plan_age_hours=None),
        search_roots=[root],
    )

    assert result.wifi_profile is not None
    assert result.wifi_profile["ssid"] == "HomeNet"
    assert result.wifi_warning == ""

    serialized = result.to_dict()
    assert serialized["wifi_profile"]["has_credentials"] is True
    assert "passphrase" not in json.dumps(serialized)


def test_discovery_treats_invalid_wifi_payload_as_warning(tmp_path: Path) -> None:
    root = tmp_path / "ventoy"
    omarchy = root / "omarchy"
    omarchy.mkdir(parents=True, exist_ok=True)
    (omarchy / "plan.json").write_text(json.dumps(_plan_payload(), indent=2) + "\n", encoding="utf-8")
    (omarchy / "wifi.json").write_text(json.dumps({"passphrase": "secret-pass"}) + "\n", encoding="utf-8")

    result = discover_and_validate_handoff_plan(
        HandoffValidationContext(live_runtime_version="0.1.0", max_plan_age_hours=None),
        search_roots=[root],
    )

    assert result.wifi_profile is None
    assert "missing ssid" in result.wifi_warning.lower()
