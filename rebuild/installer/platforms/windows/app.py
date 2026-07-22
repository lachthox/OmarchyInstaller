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
    plan_path: str = ""
    iso_path: str = ""
    release_manifest_path: str = ""
    usb_disk_number: int = -1
    usb_confirmation: str = ""
    allow_ventoy_install: bool = False


# Plain-language guided steps. Each maps onto a stage of the underlying
# WindowsMigrationFlow; the wizard never bypasses that engine, it just narrates
# it. `stage` is the stage_states key the step waits on (None = final step).
WIZARD_STEPS: tuple[dict[str, str | None], ...] = (
    {
        "key": "check",
        "stage": "preflight",
        "title": "Check your PC",
        "what": (
            "First we make sure your computer is ready for a safe dual-boot "
            "setup. This only reads information — nothing on your disk is "
            "changed yet."
        ),
        "action": "Re-check",
    },
    {
        "key": "backup",
        "stage": "backup",
        "title": "Back up your Windows boot files",
        "what": (
            "We save a copy of the files Windows needs to start up, so things "
            "can be put back if anything goes wrong. Your personal files "
            "(documents, photos, apps) are not touched."
        ),
        "action": "Start backup",
    },
    {
        "key": "partition",
        "stage": "partition",
        "title": "Make room for Linux",
        "what": (
            "We shrink Windows to free up empty space for Linux. Windows and "
            "your files stay exactly where they are — they just take up less of "
            "the disk. Linux goes in the freed space."
        ),
        "action": "Make room",
    },
    {
        "key": "usb",
        "stage": "handoff",
        "title": "Prepare your USB stick",
        "what": (
            "We copy the Linux installer onto your USB stick so you can start "
            "your PC from it. WARNING: everything currently on that USB stick "
            "will be erased. Make sure it holds nothing you want to keep."
        ),
        "action": "Prepare USB",
    },
    {
        "key": "finish",
        "stage": None,
        "title": "You're ready to install",
        "what": (
            "Preparation is done. Next, restart your PC and choose the USB "
            "stick in the boot menu to finish installing Linux. Keep your "
            "backup safe until you've confirmed everything boots."
        ),
        "action": "Finish",
    },
)


class WindowsPreflightApp(App[int]):
    """Guided Windows preparation UI with an advanced power-user view.

    The default face is a step-by-step wizard in plain language; pressing
    ``A`` reveals the original expert console (check table + stage hotkeys).
    Both views drive the exact same worker-backed WindowsMigrationFlow.
    """

    CSS = """
    Screen { layout: vertical; }
    #body { padding: 0 1; height: 1fr; }
    #title { text-style: bold; height: 1; }

    /* Guided wizard view */
    #wizard { height: auto; border: round $success; padding: 1 2; }
    #wiz-progress { color: $text-muted; height: 1; }
    #wiz-title { text-style: bold; height: auto; padding: 1 0 0 0; }
    #wiz-body { height: auto; padding: 1 0; }
    #wiz-status { height: auto; }
    #wiz-actions { color: $accent; text-style: bold; height: auto; padding: 1 0 0 0; }

    /* Advanced console view */
    #advanced { height: 1fr; }
    #summary { height: auto; min-height: 7; padding: 0 1; border: round $primary; }
    #hints { color: $text-muted; height: auto; }
    DataTable:focus { border: heavy $accent; }
    """

    BINDINGS = [
        Binding("enter", "wizard_primary", "Next step"),
        Binding("a", "toggle_view", "Advanced"),
        Binding("r", "refresh", "Refresh", show=False),
        Binding("b", "run_backup_step", "Backup", show=False),
        Binding("p", "run_partition_step", "Partition", show=False),
        Binding("v", "run_ventoy_step", "Ventoy/Handoff", show=False),
        Binding("c", "continue_flow", "Continue", show=False),
        Binding("x", "cancel_operation", "Cancel", show=False),
        Binding("j", "cursor_down", "Down", show=False),
        Binding("k", "cursor_up", "Up", show=False),
        Binding("escape", "quit_flow", "Quit"),
        Binding("q", "quit_flow", "Quit", show=False),
    ]

    def __init__(self, config: WindowsTuiConfig | None = None) -> None:
        super().__init__()
        self._config = config or WindowsTuiConfig()
        self._view = "wizard"  # "wizard" (default) | "advanced"
        self._can_continue = False
        self._busy = False
        self._cancel_requested = threading.Event()
        self._checks: list[dict[str, str]] = []
        self._snapshot: DiskProbeSnapshot | None = None
        self._snapshot_summary = "Disk snapshot not collected yet."
        self._notes: list[str] = []
        self._backup_result: FlowStepResult | None = None
        self._partition_result: FlowStepResult | None = None
        self._handoff_result: FlowStepResult | None = None
        self._handoff_key = ""
        self.stage_states: dict[str, StageState] = {
            "preflight": StageState.IDLE,
            "backup": StageState.IDLE,
            "partition": StageState.IDLE,
            "handoff": StageState.IDLE,
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
            yield Static("Omarchy Installer", id="title")
            with Vertical(id="wizard"):
                yield Static("", id="wiz-progress")
                yield Static("", id="wiz-title")
                yield Static("", id="wiz-body")
                yield Static("", id="wiz-status")
                yield Static("", id="wiz-actions")
            with Vertical(id="advanced"):
                yield DataTable(id="checks")
                yield Static("", id="summary")
                yield Static(
                    "R refresh · B backup · P partition · V Ventoy/handoff · C finish · X cancel · ↑/↓ or j/k navigate · A guided · Esc/Q quit",
                    id="hints",
                )
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#checks", DataTable)
        table.cursor_type = "row"
        table.add_columns("Check", "State", "Value", "Details")
        self._apply_view()
        self.action_refresh()

    # -- View management ---------------------------------------------------

    def _apply_view(self) -> None:
        """Show exactly one of the two views and route focus accordingly."""
        wizard_visible = self._view == "wizard"
        wizard = self.query_one("#wizard", Vertical)
        wizard.display = wizard_visible
        self.query_one("#advanced").display = not wizard_visible
        if wizard_visible:
            # App-level bindings drive the wizard; give the container focus so
            # keystrokes have a stable home while the check table is hidden.
            wizard.can_focus = True
            wizard.focus(scroll_visible=False)
        else:
            self.query_one("#checks", DataTable).focus()

    def action_toggle_view(self) -> None:
        self._view = "advanced" if self._view == "wizard" else "wizard"
        self._apply_view()
        self._refresh_views()

    def _refresh_views(self) -> None:
        self._render_summary()
        self._render_wizard()

    # -- Guided wizard rendering ------------------------------------------

    def _stage_done(self, stage: str) -> bool:
        required = StageState.SUCCEEDED if self._flow.apply_changes else StageState.SIMULATED
        return self.stage_states.get(stage) == required

    def _current_step_index(self) -> int:
        if not self._can_continue:
            return 0
        if not self._stage_done("backup"):
            return 1
        if not self._stage_done("partition"):
            return 2
        if not self._stage_done("handoff"):
            return 3
        return 4

    def _usb_inputs_ready(self) -> bool:
        cfg = self._config
        return (
            bool(cfg.plan_path)
            and bool(cfg.iso_path)
            and bool(cfg.release_manifest_path)
            and cfg.usb_disk_number >= 0
        )

    def _wizard_status_line(self, index: int, step: dict[str, str | None]) -> str:
        stage = step["stage"]
        if self._busy and stage is not None and self.stage_states.get(stage) == StageState.RUNNING:
            return "⏳ Working… please wait. You can keep using the screen."
        if index == 0:
            if self._busy:
                return "⏳ Checking your PC…"
            if self._can_continue:
                return "✔ Your PC is ready."
            return f"✖ Not ready yet: {self._snapshot_summary}  ·  Press Enter to check again."
        if stage is not None:
            state = self.stage_states.get(stage)
            if state in (StageState.SUCCEEDED, StageState.SIMULATED):
                return "✔ Done."
            if state == StageState.FAILED:
                recent = self._notes[-1] if self._notes else "it didn't work"
                return f"✖ Didn't finish: {recent}  ·  Press Enter to try again."
            if state == StageState.CANCELLED:
                return "■ Cancelled — no changes were made. Press Enter to run it again."
            if index == 3 and not self._usb_inputs_ready():
                return (
                    "This step needs the Linux ISO and a chosen USB stick. Those "
                    "normally come from the release bundle — if the button does "
                    "nothing, open Advanced (A) or relaunch with the ISO/USB set."
                )
            return "Press Enter to start this step."
        return "All steps are complete. Press Enter to finish."

    def _render_wizard(self) -> None:
        index = self._current_step_index()
        step = WIZARD_STEPS[index]
        total = len(WIZARD_STEPS)

        dots = " ".join(
            "●" if i < index else ("◉" if i == index else "○") for i in range(total)
        )
        self.query_one("#wiz-progress", Static).update(f"Step {index + 1} of {total}   {dots}")

        if self._flow.apply_changes:
            mode_note = "APPLY mode — real changes will be made to your disk."
        else:
            mode_note = "Practice run (SIMULATION) — no real changes are made."
        self.query_one("#wiz-title", Static).update(f"{step['title']}")
        self.query_one("#wiz-body", Static).update(f"{step['what']}\n\n{mode_note}")
        self.query_one("#wiz-status", Static).update(self._wizard_status_line(index, step))

        action_label = step["action"]
        if index == 0 and self._can_continue:
            action_hint = "[Enter] Continue"
        else:
            action_hint = f"[Enter] {action_label}"
        cancel_hint = "   [X] Cancel" if self._busy and not self._flow.apply_changes else ""
        self.query_one("#wiz-actions", Static).update(
            f"{action_hint}   [A] Advanced view{cancel_hint}   [Esc] Quit"
        )

    def action_wizard_primary(self) -> None:
        """Enter key: run whatever the current guided step needs."""
        index = self._current_step_index()
        if index == 0:
            self.action_refresh()
        elif index == 1:
            self.action_run_backup_step()
        elif index == 2:
            self.action_run_partition_step()
        elif index == 3:
            self.action_run_ventoy_step()
        else:
            self.action_continue_flow()

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
                    f"Ventoy/handoff: {self.stage_states['handoff'].value}",
                    f"One-time live key: {self._handoff_key or 'not generated'}",
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
        self._handoff_result = None
        self._handoff_key = ""
        self.stage_states["backup"] = StageState.IDLE
        self.stage_states["partition"] = StageState.IDLE
        self.stage_states["handoff"] = StageState.IDLE

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
        self._refresh_views()

    def action_refresh(self) -> None:
        if self._busy:
            self.notify("An operation is already running.", severity="warning")
            return
        self._set_busy(True)
        self.stage_states["preflight"] = StageState.RUNNING
        self._can_continue = False
        self._invalidate_dependent_results()
        self._refresh_views()
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

    @work(thread=True, exclusive=True, group="handoff")
    def _handoff_worker(self) -> None:
        self._run_flow_worker(
            "handoff",
            lambda: self._flow.run_ventoy_handoff(
                plan_path=self._config.plan_path,
                iso_path=self._config.iso_path,
                release_manifest_path=self._config.release_manifest_path,
                usb_disk_number=self._config.usb_disk_number,
                usb_confirmation=self._config.usb_confirmation,
                allow_ventoy_install=self._config.allow_ventoy_install,
            ),
        )

    def _apply_flow_result(
        self,
        stage: str,
        result: FlowStepResult | None,
        error: str | None,
    ) -> None:
        if stage == "backup":
            self._backup_result = result
        elif stage == "partition":
            self._partition_result = result
        else:
            self._handoff_result = result
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
            if stage == "partition" and self._flow.prepared_snapshot is not None:
                self._snapshot = self._flow.prepared_snapshot
            if stage == "handoff" and result.payload:
                self._handoff_key = str(result.payload.get("integrity_key_hex", ""))
            self.notify(summary, severity="information")
        self._set_busy(False)
        self._cancel_requested.clear()
        self._append_note(summary)
        self._refresh_views()

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
        self._refresh_views()
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
        self.stage_states["handoff"] = StageState.IDLE
        self._handoff_result = None
        self._refresh_views()
        self._partition_worker()

    def action_run_ventoy_step(self) -> None:
        if self._busy:
            self.notify("An operation is already running.", severity="warning")
            return
        required = StageState.SUCCEEDED if self._flow.apply_changes else StageState.SIMULATED
        if self.stage_states["partition"] != required:
            self.notify("Complete the current-mode partition stage first.", severity="warning")
            return
        if not all(
            (self._config.plan_path, self._config.iso_path, self._config.release_manifest_path)
        ) or self._config.usb_disk_number < 0:
            self.notify("Plan, ISO, release manifest, and USB disk number are required.", severity="error")
            return
        self._set_busy(True)
        self.stage_states["handoff"] = StageState.RUNNING
        self._refresh_views()
        self._handoff_worker()

    def action_continue_flow(self) -> None:
        if self._busy:
            self.notify("Wait for the active operation to finish.", severity="warning")
            return
        required = StageState.SUCCEEDED if self._flow.apply_changes else StageState.SIMULATED
        if any(self.stage_states[name] != required for name in ("backup", "partition", "handoff")):
            self.notify("Run backup, partition, and Ventoy/handoff stages before finishing.", severity="warning")
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
    plan_path: str = "",
    iso_path: str = "",
    release_manifest_path: str = "",
    usb_disk_number: int = -1,
    usb_confirmation: str = "",
    allow_ventoy_install: bool = False,
) -> int:
    app = WindowsPreflightApp(
        WindowsTuiConfig(
            apply_changes=apply_changes,
            target_free_gib=target_free_gib,
            backup_destination=backup_destination,
            backup_fallback_destination=backup_fallback_destination,
            plan_path=plan_path,
            iso_path=iso_path,
            release_manifest_path=release_manifest_path,
            usb_disk_number=usb_disk_number,
            usb_confirmation=usb_confirmation,
            allow_ventoy_install=allow_ventoy_install,
        )
    )
    result = app.run()
    return result if isinstance(result, int) else EXIT_QUIT
