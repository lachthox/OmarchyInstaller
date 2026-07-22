from __future__ import annotations

import asyncio
import json
from pathlib import Path
import threading

import pytest

import rebuild.installer.platforms.windows.app as app_module
from rebuild.installer.platforms.windows.app import StageState, WindowsPreflightApp
from rebuild.installer.platforms.windows.disk_probe import DiskProbeError, DiskProbeSnapshot
from rebuild.installer.platforms.windows.flow import FlowStepResult, WindowsMigrationFlow
from rebuild.installer.shared.validation import validate_plan_contract


REPO_ROOT = Path(__file__).resolve().parents[2]


def ready_report() -> dict[str, object]:
    return {
        "can_proceed": True,
        "checks": [
            {"name": "admin", "status": "pass", "value": "yes", "message": "ready"},
            {"name": "secure-boot", "status": "pass", "value": "on", "message": "ready"},
        ],
    }


def snapshot() -> DiskProbeSnapshot:
    payload = json.loads(
        (REPO_ROOT / "rebuild" / "assets" / "templates" / "plan.template.json").read_text(
            encoding="utf-8"
        )
    )
    plan = validate_plan_contract(payload)
    return DiskProbeSnapshot(
        disk_identity=plan.disk_identity,
        efi_identity=plan.efi_identity,
        windows_partition_identity=plan.windows_partition_identity,
        prepared_free_space_range=plan.prepared_free_space_range,
        partitions=(plan.efi_identity, plan.windows_partition_identity),
    )


def run(coroutine) -> None:
    asyncio.run(coroutine)


def test_small_terminal_navigation_and_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_module, "run_windows_preflight", ready_report)
    monkeypatch.setattr(app_module, "collect_disk_probe_snapshot", snapshot)

    async def scenario() -> None:
        app = WindowsPreflightApp()
        async with app.run_test(size=(80, 24)) as pilot:
            await app.workers.wait_for_complete()
            assert app.stage_states["preflight"] == StageState.SUCCEEDED
            assert app._can_continue is True
            # Guided wizard is the default face; the check table lives in the
            # advanced view, revealed with "a".
            assert app._view == "wizard"
            assert app.query_one("#wizard").display is True
            assert app.query_one("#advanced").display is False
            await pilot.press("a")
            assert app._view == "advanced"
            assert app.query_one("#checks").has_focus
            await pilot.press("j", "k", "tab", "shift+tab")
            assert app.screen.size.width == 80
            assert app.screen.size.height == 24

    run(scenario())


def test_wizard_is_default_and_shows_first_step(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_module, "run_windows_preflight", ready_report)
    monkeypatch.setattr(app_module, "collect_disk_probe_snapshot", snapshot)

    async def scenario() -> None:
        app = WindowsPreflightApp()
        async with app.run_test() as _pilot:
            await app.workers.wait_for_complete()
            assert app._view == "wizard"
            # After a passing preflight the guided flow sits on the first
            # actionable step ("Back up..."), and the title uses plain language.
            assert app._current_step_index() == 1
            title = app.query_one("#wiz-title").render()
            assert "Back up" in str(title)
            progress = str(app.query_one("#wiz-progress").render())
            assert "Step 2 of 5" in progress

    run(scenario())


def test_wizard_enter_key_drives_the_underlying_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_module, "run_windows_preflight", ready_report)
    monkeypatch.setattr(app_module, "collect_disk_probe_snapshot", snapshot)
    # Stub the platform operations (real backup/partition are Windows-only and
    # not the subject of this test): we are verifying that the wizard's Enter
    # key dispatches to the correct stage and advances, not the flow internals.
    monkeypatch.setattr(
        WindowsMigrationFlow,
        "run_backup",
        lambda self: FlowStepResult("backup", True, self.apply_changes, "simulated backup"),
    )
    monkeypatch.setattr(
        WindowsMigrationFlow,
        "run_partition_prep",
        lambda self: FlowStepResult("partition", True, self.apply_changes, "simulated partition"),
    )

    async def scenario() -> None:
        app = WindowsPreflightApp()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            # Enter on step 2 runs the backup stage.
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            assert app.stage_states["backup"] == StageState.SIMULATED
            # The wizard has now advanced to the partition step.
            assert app._current_step_index() == 2
            # Enter again runs partition prep and advances to the USB step.
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            assert app.stage_states["partition"] == StageState.SIMULATED
            assert app._current_step_index() == 3

    run(scenario())


def test_wizard_partition_step_shows_disk_and_allows_resize(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app_module, "run_windows_preflight", ready_report)
    monkeypatch.setattr(app_module, "collect_disk_probe_snapshot", snapshot)
    monkeypatch.setattr(
        WindowsMigrationFlow,
        "run_backup",
        lambda self: FlowStepResult("backup", True, self.apply_changes, "simulated backup"),
    )

    async def scenario() -> None:
        app = WindowsPreflightApp()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            # Advance to the "Make room" step.
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            assert app._current_step_index() == 2
            body = str(app.query_one("#wiz-body").render())
            # Real disk numbers and the chosen Linux size are shown.
            assert "Your disk:" in body
            assert "Already free (unallocated)" in body
            assert "Linux will get:" in body
            # The size chooser adjusts the value and keeps the engine target in
            # sync, staying within bounds.
            baseline = app._linux_gib
            await pilot.press("left")
            assert app._linux_gib <= baseline
            assert app._flow.target_free_gib == app._linux_gib
            assert app._linux_gib >= app_module.MIN_LINUX_GIB or app._linux_gib == app._max_linux_gib()
            lowered = app._linux_gib
            await pilot.press("right")
            assert app._linux_gib >= lowered
            assert app._flow.target_free_gib == app._linux_gib

    run(scenario())


def test_wizard_disk_picker_selects_and_prepares_a_second_disk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from rebuild.installer.platforms.windows.disk_inventory import DiskInfo
    from rebuild.installer.platforms.windows.disk_probe import collect_target_disk_snapshot

    GIB = 1024**3
    win_num = snapshot().disk_identity.runtime_disk_number
    spare_num = win_num + 1
    disks = (
        DiskInfo(
            number=win_num, model="Windows NVMe", serial="W", size_bytes=512 * GIB,
            bus_type="NVMe", media_type="SSD", partition_style="GPT", is_system=True,
            is_boot=True, is_read_only=False, partition_count=4, largest_free_extent_bytes=40 * GIB,
        ),
        DiskInfo(
            number=spare_num, model="Spare SSD", serial="S", size_bytes=1000 * GIB,
            bus_type="SATA", media_type="SSD", partition_style="RAW", is_system=False,
            is_boot=False, is_read_only=False, partition_count=0, largest_free_extent_bytes=0,
        ),
    )

    class FakeDiskProbe:
        def collect_disk_layout(self, disk_number: int) -> dict:
            return {
                "model": "Spare SSD", "serial": "S", "size_bytes": 1000 * GIB,
                "partition_style": "RAW", "gpt_disk_guid": "", "logical_sector_size": 512,
                "partitions": [],
            }

    def fake_target_snapshot(disk_number, *, mode="auto", probe=None):
        return collect_target_disk_snapshot(disk_number, mode=mode, probe=FakeDiskProbe())

    monkeypatch.setattr(app_module, "run_windows_preflight", ready_report)
    monkeypatch.setattr(app_module, "collect_disk_probe_snapshot", snapshot)
    monkeypatch.setattr(app_module, "collect_disk_inventory", lambda: disks)
    monkeypatch.setattr(app_module, "collect_target_disk_snapshot", fake_target_snapshot)
    monkeypatch.setattr(
        WindowsMigrationFlow, "run_backup",
        lambda self: FlowStepResult("backup", True, self.apply_changes, "simulated backup"),
    )

    async def scenario() -> None:
        app = WindowsPreflightApp()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("enter")  # backup -> reach "Make room"
            await app.workers.wait_for_complete()
            assert app._current_step_index() == 2
            # Both disks are offered; the Windows disk is the default target.
            assert len(app._target_choices()) == 2
            assert app._selected_target()["kind"] == "windows"
            body = str(app.query_one("#wiz-body").render())
            assert "Install Linux to:" in body
            # Choose the spare disk and confirm the display switches to it.
            await pilot.press("down")
            assert app._selected_target()["kind"] == "separate"
            assert app._selected_target()["disk_number"] == spare_num
            body = str(app.query_one("#wiz-body").render())
            assert "whole disk" in body
            # Enter now prepares the target disk (no Windows shrink).
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            assert app.stage_states["partition"] == StageState.SIMULATED
            assert app._target_prep is not None
            assert app._target_prep.disk_number == spare_num
            assert app._target_prep.would_erase_existing_data is False
            # The handoff plan will carry a separate-disk target on the spare.
            assert app._flow._linux_install_target is not None
            assert app._flow._linux_install_target["disk_identity"]["runtime_disk_number"] == spare_num
            assert app._flow._prepared_snapshot is not None

    run(scenario())


def test_toggle_between_wizard_and_advanced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_module, "run_windows_preflight", ready_report)
    monkeypatch.setattr(app_module, "collect_disk_probe_snapshot", snapshot)

    async def scenario() -> None:
        app = WindowsPreflightApp()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            assert app._view == "wizard"
            await pilot.press("a")
            assert app._view == "advanced"
            assert app.query_one("#advanced").display is True
            await pilot.press("a")
            assert app._view == "wizard"
            assert app.query_one("#wizard").display is True

    run(scenario())


def test_disk_snapshot_failure_blocks_and_clears_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app_module, "run_windows_preflight", ready_report)

    def fail_snapshot() -> DiskProbeSnapshot:
        raise DiskProbeError("identity unavailable")

    monkeypatch.setattr(app_module, "collect_disk_probe_snapshot", fail_snapshot)

    async def scenario() -> None:
        app = WindowsPreflightApp()
        async with app.run_test() as _pilot:
            await app.workers.wait_for_complete()
            assert app._can_continue is False
            assert app.stage_states["preflight"] == StageState.BLOCKED
            assert "identity unavailable" in app._snapshot_summary

    run(scenario())


def test_long_backup_runs_in_worker_and_ui_remains_responsive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app_module, "run_windows_preflight", ready_report)
    monkeypatch.setattr(app_module, "collect_disk_probe_snapshot", snapshot)
    started = threading.Event()
    release = threading.Event()

    def slow_backup(self: WindowsMigrationFlow) -> FlowStepResult:
        started.set()
        release.wait(timeout=5)
        return FlowStepResult("backup", True, self.apply_changes, "simulated backup")

    monkeypatch.setattr(WindowsMigrationFlow, "run_backup", slow_backup)

    async def scenario() -> None:
        app = WindowsPreflightApp()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("b")
            for _ in range(100):
                if started.is_set():
                    break
                await asyncio.sleep(0.01)
            assert started.is_set()
            assert app._busy is True
            assert app.stage_states["backup"] == StageState.RUNNING
            await pilot.press("j", "k", "r")
            assert app.screen is not None
            release.set()
            await app.workers.wait_for_complete()
            assert app.stage_states["backup"] == StageState.SIMULATED

    try:
        run(scenario())
    finally:
        release.set()


def test_refresh_invalidates_previous_stage_results(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_module, "run_windows_preflight", ready_report)
    monkeypatch.setattr(app_module, "collect_disk_probe_snapshot", snapshot)

    async def scenario() -> None:
        app = WindowsPreflightApp()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            app.stage_states["backup"] = StageState.SIMULATED
            app.stage_states["partition"] = StageState.SIMULATED
            await pilot.press("r")
            await app.workers.wait_for_complete()
            assert app.stage_states["backup"] == StageState.IDLE
            assert app.stage_states["partition"] == StageState.IDLE

    run(scenario())


def test_simulation_cancellation_is_reported_without_fake_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app_module, "run_windows_preflight", ready_report)
    monkeypatch.setattr(app_module, "collect_disk_probe_snapshot", snapshot)
    started = threading.Event()
    release = threading.Event()

    def slow_backup(self: WindowsMigrationFlow) -> FlowStepResult:
        started.set()
        release.wait(timeout=5)
        return FlowStepResult("backup", True, self.apply_changes, "should not be success")

    monkeypatch.setattr(WindowsMigrationFlow, "run_backup", slow_backup)

    async def scenario() -> None:
        app = WindowsPreflightApp()
        async with app.run_test() as pilot:
            await app.workers.wait_for_complete()
            await pilot.press("b")
            for _ in range(100):
                if started.is_set():
                    break
                await asyncio.sleep(0.01)
            await pilot.press("x")
            release.set()
            await app.workers.wait_for_complete()
            assert app.stage_states["backup"] == StageState.CANCELLED
            assert app._backup_result is None

    try:
        run(scenario())
    finally:
        release.set()
