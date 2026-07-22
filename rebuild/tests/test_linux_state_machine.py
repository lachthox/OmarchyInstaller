from __future__ import annotations

import json
from pathlib import Path
import threading
import asyncio
from contextlib import contextmanager
from types import SimpleNamespace

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
    def run_stage(stage: str, plan: object, *, dry_run: bool) -> tuple[bool, str]:
        return (False, secret) if stage == "network" else (True, "ok")

    backend.run_stage = run_stage  # type: ignore[method-assign]
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
        async with app.run_test(size=Size(80, 24)) as _pilot:
            for _ in range(100):
                if started.is_set():
                    break
                await asyncio.sleep(0.01)
            assert started.is_set()
            assert app._view == "wizard"
            assert "Step 1 of 5" in str(app.query_one("#wiz-progress").render())
            release.set()
            await app.workers.wait_for_complete()
            assert app._snapshot.install_result is None

    try:
        asyncio.run(scenario())
    finally:
        release.set()


def test_linux_tui_apply_action_reaches_production_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    from rebuild.installer.ui import screens

    plan = payload_to_plan(plan_payload())
    ready = screens.LiveRuntimeSnapshot(
        generated_at_utc="2026-07-21T00:00:00Z",
        dependencies_ok=True,
        missing_dependencies=tuple(),
        handoff_sources=("/mnt/ventoy",),
        handoff_result=SimpleNamespace(plan=plan, plan_path="/mnt/ventoy/omarchy/plan.json"),  # type: ignore[arg-type]
        handoff_error="",
        network_result=SimpleNamespace(connected=True, requires_abort=False),  # type: ignore[arg-type]
        network_error="",
        install_result=None,
        install_error="not started",
        boot_policy_result=None,
        boot_policy_error="not run",
        identity_result=SimpleNamespace(disk=SimpleNamespace(path="/dev/vda")),  # type: ignore[arg-type]
    )
    monkeypatch.setattr(screens, "collect_live_runtime_snapshot", lambda **kwargs: ready)
    called: list[tuple[bool, str, str, str]] = []

    async def scenario() -> None:
        app = screens.LiveInstallerApp()
        app._install_worker = lambda *args: called.append(args)  # type: ignore[assignment]
        async with app.run_test(size=Size(100, 32)):
            await app.workers.wait_for_complete()
            assert app._wizard_step() == 2
            app.query_one("#password", screens.Input).value = "shared-secret"
            app.query_one("#password-confirm", screens.Input).value = "shared-secret"
            app.action_wizard_primary()
            assert app._wizard_step() == 3
            app.action_wizard_primary()
            assert called == [
                (False, confirmation_token(plan), "shared-secret", "shared-secret")
            ]
            assert app.query_one("#password", screens.Input).value == ""
            assert app.query_one("#password-confirm", screens.Input).value == ""

    asyncio.run(scenario())


def test_linux_tui_defaults_to_beginner_wizard_at_80x24(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from rebuild.installer.ui import screens

    plan = payload_to_plan(plan_payload())
    ready = screens.LiveRuntimeSnapshot(
        generated_at_utc="2026-07-21T00:00:00Z",
        dependencies_ok=True,
        missing_dependencies=tuple(),
        handoff_sources=("/mnt/ventoy",),
        handoff_result=SimpleNamespace(plan=plan, plan_path="/mnt/ventoy/omarchy/plan.json"),  # type: ignore[arg-type]
        handoff_error="",
        network_result=SimpleNamespace(connected=True, requires_abort=False),  # type: ignore[arg-type]
        network_error="",
        install_result=None,
        install_error="not started",
        boot_policy_result=None,
        boot_policy_error="not run",
        identity_result=SimpleNamespace(disk=SimpleNamespace(path="/dev/vda")),  # type: ignore[arg-type]
    )
    monkeypatch.setattr(screens, "collect_live_runtime_snapshot", lambda **kwargs: ready)

    async def scenario() -> None:
        app = screens.LiveInstallerApp()
        async with app.run_test(size=Size(80, 24)) as pilot:
            await app.workers.wait_for_complete()
            assert app._view == "wizard"
            assert app.query_one("#wizard").display is True
            assert app.query_one("#advanced").display is False
            assert app._wizard_step() == 2
            assert "Create your password" in str(app.query_one("#wiz-title").render())
            assert app.query_one("#password", screens.Input).has_focus
            assert len(app.query("#simulate-install")) == 0

            for key in "beginner-password":
                await pilot.press(key)
            await pilot.press("tab")
            for key in "beginner-password":
                await pilot.press(key)
            await pilot.press("enter")
            assert app._wizard_step() == 3
            assert "Ready to install Omarchy" in str(app.query_one("#wiz-title").render())
            assert app.query_one("#password", screens.Input).display is False

            await pilot.press("a")
            assert app._view == "advanced"
            assert app.query_one("#advanced").display is True

    asyncio.run(scenario())


def test_live_handoff_discovery_retries_transient_usb_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from rebuild.installer.ui import screens

    attempts = 0
    expected = SimpleNamespace(plan_path="/mnt/ventoy/omarchy/plan.json")

    @contextmanager
    def flaky_handoff(_context):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise screens.HandoffDiscoveryError("USB device is still settling")
        yield expected

    monkeypatch.setattr(screens, "enumerate_ventoy_data_partitions", lambda: ("/dev/sdz1",))
    monkeypatch.setattr(screens, "open_validated_handoff", flaky_handoff)
    monkeypatch.setattr(screens.time, "sleep", lambda _seconds: None)

    sources, result, error = screens._discover_live_handoff(SimpleNamespace())  # type: ignore[arg-type]

    assert attempts == 3
    assert sources == ("/dev/sdz1",)
    assert result is expected
    assert error == ""
