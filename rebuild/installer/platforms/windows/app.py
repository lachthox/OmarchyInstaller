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


EXIT_QUIT = 0
EXIT_LAUNCH_LEGACY = 10


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
    launch_legacy_on_continue: bool = True


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
        Binding("c", "continue_flow", "Continue"),
        Binding("l", "launch_legacy", "Legacy PowerShell"),
        Binding("q", "quit_flow", "Quit"),
    ]

    def __init__(self, config: WindowsTuiConfig | None = None) -> None:
        super().__init__()
        self._config = config or WindowsTuiConfig()
        self._can_continue = False
        self._checks: list[dict[str, str]] = []
        self._snapshot_summary = "Disk snapshot not collected yet."

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="body"):
            yield Static("Omarchy Windows Prep (Python TUI)", id="title")
            yield DataTable(id="checks")
            yield Static("", id="summary")
            yield Static(
                "Keys: [R] refresh checks  [C] continue  [L] launch legacy flow  [Q] quit",
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
        summary.update(
            "\n".join(
                [
                    f"State: {state}",
                    self._snapshot_summary,
                    "Press C to continue into the migrated flow front-door.",
                ]
            )
        )

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

        self._render_summary()

    def action_continue_flow(self) -> None:
        if not self._can_continue:
            self.notify("Preflight is blocked. Resolve FAIL checks first.", severity="error")
            return
        if self._config.launch_legacy_on_continue:
            self.exit(EXIT_LAUNCH_LEGACY)
            return
        self.exit(EXIT_QUIT)

    def action_launch_legacy(self) -> None:
        self.exit(EXIT_LAUNCH_LEGACY)

    def action_quit_flow(self) -> None:
        self.exit(EXIT_QUIT)


def run_windows_preflight_tui(*, launch_legacy_on_continue: bool = True) -> int:
    app = WindowsPreflightApp(
        WindowsTuiConfig(launch_legacy_on_continue=launch_legacy_on_continue)
    )
    result = app.run()
    if isinstance(result, int):
        return result
    return EXIT_QUIT

