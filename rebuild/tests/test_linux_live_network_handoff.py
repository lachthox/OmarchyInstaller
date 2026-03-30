from __future__ import annotations

from types import SimpleNamespace

import pytest

try:
    from rebuild.installer.platforms.linux_live import network as network_module
    from rebuild.installer.platforms.linux_live.discovery import HandoffDiscoveryResult
    from rebuild.installer.shared import validate_plan_contract
    from rebuild.installer.ui import screens as screens_module
except ModuleNotFoundError:  # pragma: no cover - fallback for package-local test runs
    from installer.platforms.linux_live import network as network_module
    from installer.platforms.linux_live.discovery import HandoffDiscoveryResult
    from installer.shared import validate_plan_contract
    from installer.ui import screens as screens_module


def _plan_payload() -> dict[str, object]:
    return {
        "meta": {
            "schema_version": "0.1.0",
            "producer_version": "0.1.0-dev",
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


class _NetworkClientStub:
    def nmcli_available(self) -> bool:
        return True

    def nmtui_available(self) -> bool:
        return False

    def general_state(self) -> str:
        return "disconnected"

    def active_connection_name(self) -> str:
        return ""

    def ethernet_connected(self) -> bool:
        return False

    def wifi_connected(self) -> bool:
        return False

    def wifi_rescan(self) -> bool:
        return False

    def connect_wifi(self, profile: dict[str, object]) -> tuple[bool, str]:
        return False, f"Authentication failed for {profile.get('ssid')} using passphrase {profile.get('passphrase')}"

    def run_nmtui(self) -> tuple[bool, str]:
        return False, "disabled"


def test_network_steps_mask_wifi_passphrase() -> None:
    result = network_module.resolve_network_connectivity(
        wifi_handoff_profile={
            "ssid": "HomeNet",
            "passphrase": "TOP-SECRET",
            "wifi_security": "wpa2",
            "interface_name": "wlan0",
        },
        retry_attempts=0,
        allow_nmtui=False,
        client=_NetworkClientStub(),
    )

    details = "\n".join(step.detail for step in result.steps)
    assert "TOP-SECRET" not in details
    assert "HomeNet" in details


def test_collect_snapshot_passes_handoff_wifi_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    plan = validate_plan_contract(_plan_payload())
    handoff_result = HandoffDiscoveryResult(
        source_root="/media/ventoy",
        plan_path="/media/ventoy/omarchy/plan.json",
        discovered_relative_path="omarchy/plan.json",
        plan_mtime_utc="2026-03-30T00:00:00Z",
        plan=plan,
        wifi_path="/media/ventoy/omarchy/wifi.json",
        wifi_profile={"ssid": "HomeNet", "passphrase": "TOP-SECRET"},
        wifi_warning="",
    )

    monkeypatch.setattr(screens_module, "validate_live_dependencies", lambda: (True, tuple()))
    monkeypatch.setattr(screens_module, "discover_handoff_sources", lambda: ["/media/ventoy"])
    monkeypatch.setattr(
        screens_module,
        "build_validation_context_from_runtime",
        lambda **_kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(
        screens_module,
        "discover_and_validate_handoff_plan",
        lambda _context, search_roots: handoff_result,
    )

    captured: dict[str, object] = {}

    def _fake_resolve_network_connectivity(**kwargs: object) -> network_module.NetworkResolutionResult:
        captured.update(kwargs)
        return network_module.NetworkResolutionResult(
            connected=True,
            connection_mode="wifi",
            requires_abort=False,
            active_connection_name="HomeNet",
            steps=tuple(),
            hint="",
        )

    monkeypatch.setattr(screens_module, "resolve_network_connectivity", _fake_resolve_network_connectivity)
    monkeypatch.setattr(
        screens_module,
        "execute_install_plan",
        lambda **_kwargs: screens_module.LiveInstallExecutionResult(
            status="dry-run-completed",
            stage_root="/tmp/stage",
            staged_files=tuple(),
            removed_paths=tuple(),
            commands=tuple(),
            target_partition_path="/dev/sda3",
            efi_partition_path="/dev/sda1",
            target_disk_path="/dev/sda",
            mount_root="/mnt",
            encryption_mapper="/dev/mapper/omarchy-cryptroot",
            dry_run=True,
        ),
    )
    monkeypatch.setattr(
        screens_module,
        "resolve_efi_mount_path",
        lambda _path: SimpleNamespace(mount_path="/boot/efi", notes=tuple()),
    )
    monkeypatch.setattr(
        screens_module,
        "summarize_boot_policy",
        lambda *_args, **_kwargs: SimpleNamespace(can_finalize=True, blockers=tuple()),
    )

    snapshot = screens_module.collect_live_runtime_snapshot()

    assert snapshot.handoff_mode == "ventoy-plan"
    assert captured.get("wifi_handoff_profile") == {"ssid": "HomeNet", "passphrase": "TOP-SECRET"}
