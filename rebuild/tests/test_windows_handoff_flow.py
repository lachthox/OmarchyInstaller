from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

try:
    from rebuild.installer.platforms.windows.app import (
        EXIT_QUIT,
        WINDOWS_STAGES,
        WindowsPrepApp,
        WindowsTuiConfig,
    )
    from rebuild.installer.platforms.windows.flow import FlowStepResult
    from rebuild.installer.platforms.windows.handoff import VentoyPayloadResult
    from rebuild.installer.platforms.windows.disk_probe import DiskProbeSnapshot
    from rebuild.installer.shared.models import DiskIdentity, FreeSpaceRange, PartitionIdentity
except ModuleNotFoundError:  # pragma: no cover - fallback for package-local test runs
    from installer.platforms.windows.app import (
        EXIT_QUIT,
        WINDOWS_STAGES,
        WindowsPrepApp,
        WindowsTuiConfig,
    )
    from installer.platforms.windows.flow import FlowStepResult
    from installer.platforms.windows.handoff import VentoyPayloadResult
    from installer.platforms.windows.disk_probe import DiskProbeSnapshot
    from installer.shared.models import DiskIdentity, FreeSpaceRange, PartitionIdentity


def _ok_step(name: str) -> FlowStepResult:
    return FlowStepResult(name=name, ok=True, apply_mode=False, summary=f"{name} ok", payload={"ok": True})


def _snapshot() -> DiskProbeSnapshot:
    disk = DiskIdentity(
        disk_serial="SER-001",
        disk_model="TestDisk",
        disk_size_bytes=512000000000,
        gpt_disk_guid="disk-guid-001",
        partition_style="GPT",
    )
    efi = PartitionIdentity(
        partition_guid="efi-guid-001",
        partuuid="efi-guid-001",
        filesystem="vfat",
        start_sector=2048,
        end_sector=4095,
        size_bytes=1048576,
    )
    windows = PartitionIdentity(
        partition_guid="win-guid-001",
        partuuid="win-guid-001",
        filesystem="ntfs",
        start_sector=4096,
        end_sector=8191,
        size_bytes=2097152,
    )
    free = FreeSpaceRange(
        start_sector=8192,
        end_sector=16384,
        size_bytes=4194304,
    )
    return DiskProbeSnapshot(
        disk_identity=disk,
        efi_identity=efi,
        windows_partition_identity=windows,
        prepared_free_space_range=free,
        partitions=(efi, windows),
    )


def test_stage_handoff_payload_writes_bundle(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    iso_path = tmp_path / "arch.iso"
    iso_path.write_text("iso", encoding="utf-8")
    data_root = tmp_path / "ventoy"

    app = WindowsPrepApp(
        WindowsTuiConfig(
            ventoy_disk_number=3,
            source_iso_path=str(iso_path),
        )
    )
    app._backup_result = _ok_step("backup")

    app_module = WindowsPrepApp.__module__
    monkeypatch.setattr(
        f"{app_module}.validate_ventoy_usb",
        lambda *_args, **_kwargs: SimpleNamespace(data_root=str(data_root), free_bytes=10**10, required_bytes=10**8),
    )
    monkeypatch.setattr(f"{app_module}.collect_disk_probe_snapshot", lambda: _snapshot())

    result = app._stage_handoff_payload()

    assert result.plan_path.endswith("omarchy\\plan.json") or result.plan_path.endswith("omarchy/plan.json")
    assert Path(result.plan_path).exists()
    assert Path(result.iso_path).exists()


def test_action_continue_flow_blocks_when_source_iso_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    app = WindowsPrepApp(WindowsTuiConfig(ventoy_disk_number=2, source_iso_path=None))
    app._can_continue = True
    app._backup_result = _ok_step("backup")
    app._partition_result = _ok_step("partition_prep")
    app._ventoy_validated = True

    stage_calls: list[int] = []
    exit_calls: list[int] = []
    monkeypatch.setattr(app, "_set_stage", lambda idx: stage_calls.append(idx))
    monkeypatch.setattr(app, "exit", lambda code: exit_calls.append(code))

    app.action_continue_flow()

    assert not exit_calls
    assert stage_calls and stage_calls[-1] == WINDOWS_STAGES.index("error_handling")
    assert "Source ISO path is required" in app._last_error


def test_action_continue_flow_fails_closed_on_payload_write_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    iso_path = tmp_path / "arch.iso"
    iso_path.write_text("iso", encoding="utf-8")

    app = WindowsPrepApp(
        WindowsTuiConfig(
            ventoy_disk_number=4,
            source_iso_path=str(iso_path),
        )
    )
    app._can_continue = True
    app._backup_result = _ok_step("backup")
    app._partition_result = _ok_step("partition_prep")
    app._ventoy_validated = True

    stage_calls: list[int] = []
    exit_calls: list[int] = []
    monkeypatch.setattr(app, "_set_stage", lambda idx: stage_calls.append(idx))
    monkeypatch.setattr(app, "exit", lambda code: exit_calls.append(code))
    monkeypatch.setattr(app, "_stage_handoff_payload", lambda: (_ for _ in ()).throw(ValueError("verify failed")))

    app.action_continue_flow()

    assert not exit_calls
    assert stage_calls and stage_calls[-1] == WINDOWS_STAGES.index("error_handling")
    assert "Failed to write Ventoy handoff payload" in app._last_error


def test_action_continue_flow_success_exits_after_payload(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    iso_path = tmp_path / "arch.iso"
    iso_path.write_text("iso", encoding="utf-8")

    app = WindowsPrepApp(
        WindowsTuiConfig(
            ventoy_disk_number=5,
            source_iso_path=str(iso_path),
            launch_legacy_on_continue=False,
        )
    )
    app._can_continue = True
    app._backup_result = _ok_step("backup")
    app._partition_result = _ok_step("partition_prep")
    app._ventoy_validated = True

    payload = VentoyPayloadResult(
        iso_path="X:/arch.iso",
        plan_path="X:/omarchy/plan.json",
        wifi_path=None,
        install_log_path=None,
        backup_info_path=None,
        written_files=("X:/arch.iso", "X:/omarchy/plan.json"),
    )

    exit_calls: list[int] = []
    monkeypatch.setattr(app, "_stage_handoff_payload", lambda: payload)
    monkeypatch.setattr(app, "exit", lambda code: exit_calls.append(code))

    app.action_continue_flow()

    assert exit_calls == [EXIT_QUIT]
    assert app._ventoy_payload_result == payload
