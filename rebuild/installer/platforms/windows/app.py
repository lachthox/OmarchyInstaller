"""Windows Python TUI entrypoint for preflight and migration handoff."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import DataTable, Footer, Header, Static

from .checks import run_windows_preflight
from .disk_probe import DiskProbeError, collect_disk_probe_snapshot
from .flow import FlowStepResult, WindowsMigrationFlow


EXIT_QUIT = 0


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
    can_proceed = bool(report.get("can_proceed", False))
    return normalized, can_proceed


@dataclass(slots=True)
class WindowsTuiConfig:
    apply_changes: bool = False
    target_free_gib: int = 120
    backup_destination: str | None = None
    backup_fallback_destination: str | None = None


class WindowsPreflightApp(App[int]):
    """Minimal Textual preflight UI while deeper Windows flow is migrated."""

    CSS = """
    Screen {
      layout: vertical;
    }
    #body {
      padding: 1 2;
      height: 1fr;
    }
    #title {
      margin-bottom: 1;
      text-style: bold;
    }
    #summary {
      margin-top: 1;
      margin-bottom: 1;
    }
    #hints {
      color: $text-muted;
      margin-top: 1;
    }
    """

    BINDINGS = [
        Binding("r", "refresh", "Refresh Checks"),
        Binding("b", "run_backup_step", "Run Backup Step"),
        Binding("p", "run_partition_step", "Run Partition Step"),
        Binding("c", "continue_flow", "Continue"),
        Binding("q", "quit_flow", "Quit"),
    ]

    def __init__(self, config: WindowsTuiConfig | None = None) -> None:
        super().__init__()
        self._config = config or WindowsTuiConfig()
        self._can_continue = False
        self._checks: list[dict[str, str]] = []
        self._snapshot_summary = "Disk snapshot not collected yet."
        self._notes: list[str] = []
        self._backup_result: FlowStepResult | None = None
        self._partition_result: FlowStepResult | None = None
        self._flow = WindowsMigrationFlow(
            apply_changes=self._config.apply_changes,
            target_free_gib=max(40, int(self._config.target_free_gib)),
            backup_destination=self._config.backup_destination,
            backup_fallback_destination=self._config.backup_fallback_destination,
        )

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="body"):
            yield Static("Omarchy Windows Prep (Python TUI)", id="title")
            yield DataTable(id="checks")
            yield Static("", id="summary")
            yield Static(
                "Keys: [R] refresh  [B] backup  [P] partition prep  [C] continue  [Q] quit",
                id="hints",
            )
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#checks", DataTable)
        table.cursor_type = "row"
        table.add_columns("Check", "Status", "Value", "Details")
        self.action_refresh()

    def _render_status(self, status: str) -> str:
        if status == "pass":
            return "PASS"
        if status == "warn":
            return "WARN"
        if status == "fail":
            return "FAIL"
        return status.upper() or "UNKNOWN"

    def _render_summary(self) -> None:
        summary = self.query_one("#summary", Static)
        state = "READY" if self._can_continue else "BLOCKED"
        mode = "APPLY" if self._flow.apply_changes else "DRY-RUN"
        backup_line = (
            self._backup_result.summary
            if self._backup_result
            else "Backup step not executed yet."
        )
        partition_line = (
            self._partition_result.summary
            if self._partition_result
            else "Partition prep step not executed yet."
        )
        recent_notes = " | ".join(self._notes[-2:]) if self._notes else "No recent actions."
        summary.update(
            "\n".join(
                [
                    f"State: {state}",
                    f"Mode: {mode} (target free space: {self._flow.target_free_gib} GiB)",
                    self._snapshot_summary,
                    f"Backup: {backup_line}",
                    f"Partition: {partition_line}",
                    f"Recent: {recent_notes}",
                    "Press C to run Python prep steps and continue.",
                ]
            )
        )

    def _append_note(self, message: str) -> None:
        self._notes.append(message)
        if len(self._notes) > 8:
            self._notes = self._notes[-8:]

    def action_refresh(self) -> None:
        report = run_windows_preflight()
        checks, can_proceed = _coerce_report(report)
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
        self._can_continue = can_proceed

        if can_proceed:
            try:
                snapshot = collect_disk_probe_snapshot()
                free_bytes = snapshot.prepared_free_space_range.size_bytes
                free_gib = round(free_bytes / (1024**3), 1)
                self._snapshot_summary = (
                    f"Disk {snapshot.disk_identity.disk_model} free range: {free_gib} GiB "
                    f"(partition style: {snapshot.disk_identity.partition_style})"
                )
            except (DiskProbeError, ValueError) as exc:
                self._snapshot_summary = f"Disk snapshot warning: {exc}"
        else:
            self._snapshot_summary = "Resolve FAIL checks before proceeding."

        self._append_note(f"Preflight refresh: {'ready' if can_proceed else 'blocked'}")
        self._render_summary()

    def action_run_backup_step(self) -> None:
        if not self._can_continue:
            self.notify("Preflight is blocked. Resolve FAIL checks first.", severity="error")
            return
        self.notify("Running Python backup step...")
        result = self._flow.run_backup()
        self._backup_result = result
        if result.ok:
            self.notify("Backup step completed.", severity="information")
        else:
            self.notify(result.summary, severity="error")
        self._append_note(result.summary)
        self._render_summary()

    def action_run_partition_step(self) -> None:
        if not self._can_continue:
            self.notify("Preflight is blocked. Resolve FAIL checks first.", severity="error")
            return
        if not self._backup_result or not self._backup_result.ok:
            self.notify("Run backup step first.", severity="warning")
            return
        self.notify("Running Python partition-prep step...")
        result = self._flow.run_partition_prep()
        self._partition_result = result
        if result.ok:
            self.notify("Partition prep step completed.", severity="information")
        else:
            self.notify(result.summary, severity="error")
        self._append_note(result.summary)
        self._render_summary()

    def action_continue_flow(self) -> None:
        if not self._can_continue:
            self.notify("Preflight is blocked. Resolve FAIL checks first.", severity="error")
            return
        if not self._backup_result or not self._backup_result.ok:
            self.action_run_backup_step()
            if not self._backup_result or not self._backup_result.ok:
                return
        if not self._partition_result or not self._partition_result.ok:
            self.action_run_partition_step()
            if not self._partition_result or not self._partition_result.ok:
                return
        self._append_note("Python flow completed.")
        self.exit(EXIT_QUIT)

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
    if isinstance(result, int):
        return result
    return EXIT_QUIT
