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
            assert app.query_one("#checks").has_focus
            await pilot.press("j", "k", "tab", "shift+tab")
            assert app.screen.size.width == 80
            assert app.screen.size.height == 24

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
