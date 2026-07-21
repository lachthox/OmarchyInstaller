from __future__ import annotations

import json
from pathlib import Path
import threading
import asyncio

import pytest
from textual.geometry import Size

from rebuild.installer.ui.live_state import (
    REQUIRED_INSTALL_STAGES,
    InstallRunState,
    LiveInstallStateMachine,
    LiveStateError,
    confirmation_token,
)


WORKSPACE = Path(__file__).resolve().parents[2]


def plan_payload() -> dict:
    return json.loads(
        (WORKSPACE / "rebuild" / "assets" / "templates" / "plan.template.json").read_text()
    )


class RecordingBackend:
    def __init__(self, *, fail_stage: str = "", cancellation: threading.Event | None = None) -> None:
        self.stages: list[str] = []
        self.fail_stage = fail_stage
        self.cancellation = cancellation

    def run_stage(self, stage: str, plan, *, dry_run: bool) -> tuple[bool, str]:
        self.stages.append(stage)
        if stage == "partition_creation" and self.cancellation:
            self.cancellation.set()
        return stage != self.fail_stage, f"{stage} postcondition verified"


def backend_stages() -> list[str]:
    return [stage for stage in REQUIRED_INSTALL_STAGES if stage not in {"destructive_summary", "typed_confirmation"}]


def test_mocked_dry_run_finishes_simulated_in_required_order() -> None:
    backend = RecordingBackend()
    result = LiveInstallStateMachine(backend).run(plan_payload(), dry_run=True)
    assert result.state == InstallRunState.SIMULATED
    assert [record.stage for record in result.stages] == list(REQUIRED_INSTALL_STAGES)
    assert backend.stages == backend_stages()
    assert all(record.status == "simulated" for record in result.stages)


def test_real_mode_requires_disk_bound_confirmation_and_every_postcondition() -> None:
    payload = plan_payload()
    backend = RecordingBackend()
    machine = LiveInstallStateMachine(backend)
    with pytest.raises(LiveStateError, match="Typed confirmation"):
        machine.run(payload, dry_run=False, typed_confirmation="INSTALL")
    result = machine.run(payload, dry_run=False, typed_confirmation=confirmation_token(payload_to_plan(payload)))
    assert result.state == InstallRunState.APPLIED
    assert backend.stages == backend_stages()


def payload_to_plan(payload: dict):
    from rebuild.installer.shared import validate_plan_contract

    return validate_plan_contract(payload)


def test_none_plan_never_succeeds() -> None:
    with pytest.raises(LiveStateError, match="plan_payload=None"):
        LiveInstallStateMachine(RecordingBackend()).run(None, dry_run=True)


def test_failure_writes_redacted_diagnostic(tmp_path: Path) -> None:
    secret = "do-not-log-this"
    path = tmp_path / "diagnostic.json"
    backend = RecordingBackend(fail_stage="network")
    backend.run_stage = lambda stage, plan, dry_run: (  # type: ignore[method-assign]
        False,
        secret,
    ) if stage == "network" else (True, "ok")
    with pytest.raises(LiveStateError, match="redacted"):
        LiveInstallStateMachine(backend).run(
            plan_payload(), dry_run=True, diagnostic_path=path, secrets=(secret,)
        )
    assert secret not in path.read_text()
    assert json.loads(path.read_text())["state"] == "failed"


def test_cancellation_becomes_unsafe_after_partition_creation() -> None:
    cancellation = threading.Event()
    backend = RecordingBackend(cancellation=cancellation)
    payload = plan_payload()
    result = LiveInstallStateMachine(backend).run(
        payload,
        dry_run=False,
        typed_confirmation=confirmation_token(payload_to_plan(payload)),
        cancellation=cancellation,
    )
    assert result.state == InstallRunState.APPLIED
    assert result.cancellation_safe is False
    assert any(record.status == "continued" for record in result.stages)


def test_linux_tui_refresh_runs_in_worker_and_stays_responsive(monkeypatch: pytest.MonkeyPatch) -> None:
    from rebuild.installer.ui import screens

    started = threading.Event()
    release = threading.Event()

    def slow_snapshot(**kwargs):
        started.set()
        release.wait(timeout=5)
        return screens.LiveRuntimeSnapshot(
            generated_at_utc="2026-07-21T00:00:00Z",
            dependencies_ok=False,
            missing_dependencies=("archinstall",),
            handoff_sources=tuple(),
            handoff_result=None,
            handoff_error="blocked",
            network_result=None,
            network_error="blocked",
            install_result=None,
            install_error="not started",
            boot_policy_result=None,
            boot_policy_error="not run",
        )

    monkeypatch.setattr(screens, "collect_live_runtime_snapshot", slow_snapshot)

    async def scenario() -> None:
        app = screens.LiveInstallerApp()
        async with app.run_test(size=Size(80, 24)) as pilot:
            for _ in range(100):
                if started.is_set():
                    break
                await asyncio.sleep(0.01)
            assert started.is_set()
            await pilot.press("n")
            assert app._active_stage_index == 1
            release.set()
            await app.workers.wait_for_complete()
            assert app._snapshot.install_result is None

    try:
        asyncio.run(scenario())
    finally:
        release.set()
