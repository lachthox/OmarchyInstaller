"""Responsive Windows Textual application for Python-only preparation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import threading
from typing import Any, Callable

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import DataTable, Footer, Header, Static

from .checks import run_windows_preflight
from .disk_probe import DiskProbeError, DiskProbeSnapshot, collect_disk_probe_snapshot
from .flow import FlowStepResult, WindowsMigrationFlow


EXIT_QUIT = 0


class StageState(StrEnum):
    IDLE = "idle"
    RUNNING = "running"
    SIMULATED = "simulated"
    SUCCEEDED = "succeeded"
    WARNING = "warning"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


def _coerce_report(report: dict[str, Any]) -> tuple[list[dict[str, str]], bool]:
    checks = report.get("checks", [])
    if not isinstance(checks, list):
        checks = []
    normalized: list[dict[str, str]] = []
    for item in checks:
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "name": str(item.get("name", "")),
                "status": str(item.get("status", "")).lower(),
                "value": str(item.get("value", "")),
                "message": str(item.get("message", "")),
            }
        )
    return normalized, bool(report.get("can_proceed", False))


@dataclass(slots=True)
class WindowsTuiConfig:
    apply_changes: bool = False
    target_free_gib: int = 120
    backup_destination: str | None = None
    backup_fallback_destination: str | None = None


class WindowsPreflightApp(App[int]):
    """Keyboard-first Windows preparation UI with worker-backed operations."""

    CSS = """
    Screen { layout: vertical; }
    #body { padding: 0 1; height: 1fr; }
    #title { text-style: bold; height: 1; }
    #summary { height: auto; min-height: 7; padding: 0 1; border: round $primary; }
    #hints { color: $text-muted; height: auto; }
    DataTable:focus { border: heavy $accent; }
    """

    BINDINGS = [
        Binding("r", "refresh", "Refresh"),
        Binding("b", "run_backup_step", "Backup"),
        Binding("p", "run_partition_step", "Partition"),
        Binding("c", "continue_flow", "Continue"),
        Binding("x", "cancel_operation", "Cancel"),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("escape", "quit_flow", "Back"),
        Binding("q", "quit_flow", "Quit"),
    ]

    def __init__(self, config: WindowsTuiConfig | None = None) -> None:
        super().__init__()
        self._config = config or WindowsTuiConfig()
        self._can_continue = False
        self._busy = False
        self._cancel_requested = threading.Event()
        self._checks: list[dict[str, str]] = []
        self._snapshot: DiskProbeSnapshot | None = None
        self._snapshot_summary = "Disk snapshot not collected yet."
        self._notes: list[str] = []
        self._backup_result: FlowStepResult | None = None
        self._partition_result: FlowStepResult | None = None
        self.stage_states: dict[str, StageState] = {
            "preflight": StageState.IDLE,
            "backup": StageState.IDLE,
            "partition": StageState.IDLE,
        }
        self._flow = WindowsMigrationFlow(
            apply_changes=self._config.apply_changes,
            target_free_gib=max(40, int(self._config.target_free_gib)),
            backup_destination=self._config.backup_destination,
            backup_fallback_destination=self._config.backup_fallback_destination,
        )

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="body"):
            yield Static("Omarchy Windows Prep · Python TUI", id="title")
            yield DataTable(id="checks")
            yield Static("", id="summary")
            yield Static(
                "R refresh · B backup · P partition · C continue · X cancel simulation · ↑/↓ or j/k navigate · Esc/Q quit",
                id="hints",
            )
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#checks", DataTable)
        table.cursor_type = "row"
        table.add_columns("Check", "State", "Value", "Details")
        table.focus()
        self.action_refresh()

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy

    def _render_status(self, status: str) -> str:
        return {"pass": "PASS", "warn": "WARN", "fail": "FAIL"}.get(
            status, status.upper() or "UNKNOWN"
        )

    def _render_summary(self) -> None:
        mode = "APPLY" if self._flow.apply_changes else "SIMULATION"
        readiness = "READY" if self._can_continue else "BLOCKED"
        if self._busy:
            readiness = "WORKING"
        recent_notes = " | ".join(self._notes[-2:]) if self._notes else "No recent actions."
        self.query_one("#summary", Static).update(
            "\n".join(
                [
                    f"Overall: {readiness} · Mode: {mode}",
                    f"Preflight: {self.stage_states['preflight'].value}",
                    self._snapshot_summary,
                    f"Backup: {self.stage_states['backup'].value}",
                    f"Partition: {self.stage_states['partition'].value}",
                    f"Recent: {recent_notes}",
                    "Continue only hands off after explicit backup and partition stages.",
                ]
            )
        )

    def _append_note(self, message: str) -> None:
        self._notes.append(message)
        self._notes = self._notes[-8:]

    def _invalidate_dependent_results(self) -> None:
        self._backup_result = None
        self._partition_result = None
        self.stage_states["backup"] = StageState.IDLE
        self.stage_states["partition"] = StageState.IDLE

    @staticmethod
    def _collect_fresh_safety_snapshot() -> tuple[list[dict[str, str]], DiskProbeSnapshot]:
        checks, can_proceed = _coerce_report(run_windows_preflight())
        if not can_proceed:
            raise RuntimeError("fresh Windows preflight is blocked")
        snapshot = collect_disk_probe_snapshot()
        return checks, snapshot

    @work(thread=True, exclusive=True, group="preflight")
    def _refresh_worker(self) -> None:
        try:
            report = run_windows_preflight()
            checks, can_proceed = _coerce_report(report)
            snapshot = collect_disk_probe_snapshot() if can_proceed else None
            self.call_from_thread(self._apply_refresh, checks, can_proceed, snapshot, None)
        except (DiskProbeError, OSError, RuntimeError, ValueError) as exc:
            self.call_from_thread(self._apply_refresh, [], False, None, str(exc))

    def _apply_refresh(
        self,
        checks: list[dict[str, str]],
        can_proceed: bool,
        snapshot: DiskProbeSnapshot | None,
        error: str | None,
    ) -> None:
        table = self.query_one("#checks", DataTable)
        table.clear()
        for check in checks:
            table.add_row(
                check["name"],
                self._render_status(check["status"]),
                check["value"],
                check["message"],
            )
        self._checks = checks
        self._snapshot = snapshot
        self._can_continue = can_proceed and snapshot is not None and error is None
        self.stage_states["preflight"] = (
            StageState.SUCCEEDED if self._can_continue else StageState.BLOCKED
        )
        if snapshot is not None:
            free_gib = round(snapshot.prepared_free_space_range.size_bytes / (1024**3), 1)
            self._snapshot_summary = (
                f"Disk: {snapshot.disk_identity.gpt_disk_guid} · contiguous free: {free_gib} GiB"
            )
        else:
            self._snapshot_summary = f"Disk safety snapshot blocked: {error or 'preflight failed'}"
        self._invalidate_dependent_results()
        self._set_busy(False)
        self._append_note(f"Refresh: {self.stage_states['preflight'].value}")
        self._render_summary()

    def action_refresh(self) -> None:
        if self._busy:
            self.notify("An operation is already running.", severity="warning")
            return
        self._set_busy(True)
        self.stage_states["preflight"] = StageState.RUNNING
        self._can_continue = False
        self._invalidate_dependent_results()
        self._render_summary()
        self._refresh_worker()

    def _run_flow_worker(
        self,
        stage: str,
        operation: Callable[[], FlowStepResult],
    ) -> None:
        try:
            _checks, fresh_snapshot = self._collect_fresh_safety_snapshot()
            if self._snapshot is None or fresh_snapshot != self._snapshot:
                raise RuntimeError("machine state changed; refresh before continuing")
            result = operation()
            if self._cancel_requested.is_set():
                self.call_from_thread(self._apply_flow_result, stage, None, "__cancelled__")
            else:
                self.call_from_thread(self._apply_flow_result, stage, result, None)
        except (DiskProbeError, OSError, RuntimeError, ValueError) as exc:
            self.call_from_thread(self._apply_flow_result, stage, None, str(exc))

    @work(thread=True, exclusive=True, group="backup")
    def _backup_worker(self) -> None:
        self._run_flow_worker("backup", self._flow.run_backup)

    @work(thread=True, exclusive=True, group="partition")
    def _partition_worker(self) -> None:
        self._run_flow_worker("partition", self._flow.run_partition_prep)

    def _apply_flow_result(
        self,
        stage: str,
        result: FlowStepResult | None,
        error: str | None,
    ) -> None:
        if stage == "backup":
            self._backup_result = result
        else:
            self._partition_result = result
        if error == "__cancelled__":
            self.stage_states[stage] = StageState.CANCELLED
            summary = "Simulation cancelled; no changes were applied."
            self.notify(summary, severity="warning")
        elif error or result is None or not result.ok:
            self.stage_states[stage] = StageState.FAILED
            summary = error or (result.summary if result else "operation failed")
            self.notify(summary, severity="error")
        else:
            self.stage_states[stage] = (
                StageState.SUCCEEDED if self._flow.apply_changes else StageState.SIMULATED
            )
            summary = result.summary
            self.notify(summary, severity="information")
        self._set_busy(False)
        self._cancel_requested.clear()
        self._append_note(summary)
        self._render_summary()

    def action_run_backup_step(self) -> None:
        if self._busy:
            self.notify("An operation is already running.", severity="warning")
            return
        if not self._can_continue:
            self.notify("Fresh preflight and disk identity are required.", severity="error")
            return
        self._set_busy(True)
        self._cancel_requested.clear()
        self.stage_states["backup"] = StageState.RUNNING
        self.stage_states["partition"] = StageState.IDLE
        self._partition_result = None
        self._render_summary()
        self._backup_worker()

    def action_run_partition_step(self) -> None:
        if self._busy:
            self.notify("An operation is already running.", severity="warning")
            return
        required_backup_state = (
            StageState.SUCCEEDED if self._flow.apply_changes else StageState.SIMULATED
        )
        if self.stage_states["backup"] != required_backup_state:
            self.notify("Complete the current-mode backup stage first.", severity="warning")
            return
        self._set_busy(True)
        self._cancel_requested.clear()
        self.stage_states["partition"] = StageState.RUNNING
        self._render_summary()
        self._partition_worker()

    def action_continue_flow(self) -> None:
        if self._busy:
            self.notify("Wait for the active operation to finish.", severity="warning")
            return
        required = StageState.SUCCEEDED if self._flow.apply_changes else StageState.SIMULATED
        if self.stage_states["backup"] != required or self.stage_states["partition"] != required:
            self.notify("Run backup and partition stages explicitly before continuing.", severity="warning")
            return
        self._append_note("Windows Python preparation flow complete.")
        self.exit(EXIT_QUIT)

    def action_cancel_operation(self) -> None:
        if not self._busy:
            self.notify("No cancellable operation is active.", severity="information")
            return
        if self._flow.apply_changes:
            self.notify(
                "Cancellation is disabled in apply mode once a platform operation has started.",
                severity="warning",
            )
            return
        self._cancel_requested.set()
        self.notify("Cancellation requested; waiting for the worker to reach a safe boundary.")

    def action_cursor_down(self) -> None:
        self.query_one("#checks", DataTable).action_cursor_down()

    def action_cursor_up(self) -> None:
        self.query_one("#checks", DataTable).action_cursor_up()

    def action_quit_flow(self) -> None:
        self.exit(EXIT_QUIT)


def run_windows_preflight_tui(
    *,
    apply_changes: bool = False,
    target_free_gib: int = 120,
    backup_destination: str | None = None,
    backup_fallback_destination: str | None = None,
) -> int:
    app = WindowsPreflightApp(
        WindowsTuiConfig(
            apply_changes=apply_changes,
            target_free_gib=target_free_gib,
            backup_destination=backup_destination,
            backup_fallback_destination=backup_fallback_destination,
        )
    )
    result = app.run()
    return result if isinstance(result, int) else EXIT_QUIT
