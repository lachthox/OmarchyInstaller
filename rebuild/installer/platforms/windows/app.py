"""Responsive Windows Textual application for Python-only preparation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
import threading
from typing import Any, Callable

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import DataTable, Footer, Header, Static

from .checks import run_windows_preflight
from .build_info import BuildInfo, load_build_info
from .disk_inventory import (
    DiskInfo,
    DiskInventoryError,
    collect_disk_inventory,
    install_target_candidates,
    usb_drive_candidates,
)
from .disk_probe import (
    DiskProbeError,
    DiskProbeSnapshot,
    TargetDiskSnapshot,
    collect_disk_probe_snapshot,
    collect_target_disk_snapshot,
)
from .flow import FlowStepResult, WindowsMigrationFlow
from .handoff import build_usb_erase_confirmation
from .release_provisioning import (
    ProvisionedAssets,
    ProvisioningError,
    provision_release_assets,
)
from .target_disk_prep import TargetDiskPrepError, TargetDiskPrepResult, prepare_target_disk


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
    allow_ventoy_install: bool = True


GIB = 1024**3
# Guided-step size chooser bounds (GiB). The apply path still validates the
# chosen size against Windows' real supported shrink range; these only bound
# the on-screen picker.
LINUX_SIZE_STEP_GIB = 10
MIN_LINUX_GIB = 40
MIN_WINDOWS_RESERVE_GIB = 40


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
        # Linux-size chooser on the "Make room" step (arrows are reliable
        # everywhere; +/- are convenience aliases). No-ops off that step.
        Binding("right", "size_up", "Bigger", show=False),
        Binding("left", "size_down", "Smaller", show=False),
        Binding("plus", "size_up", "Bigger", show=False),
        Binding("equals_sign", "size_up", "Bigger", show=False),
        Binding("minus", "size_down", "Smaller", show=False),
        Binding("underscore", "size_down", "Smaller", show=False),
        # Target-disk chooser on the "Make room" step. No-ops off that step.
        Binding("up", "target_prev", "Prev disk", show=False),
        Binding("down", "target_next", "Next disk", show=False),
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
        # Chosen size (GiB) for the new Linux partition; seeded from config and
        # kept in sync with the flow's shrink target as the user adjusts it.
        self._linux_gib = max(MIN_LINUX_GIB, int((config or self._config).target_free_gib))
        self._can_continue = False
        self._busy = False
        self._cancel_requested = threading.Event()
        self._checks: list[dict[str, str]] = []
        # Multi-disk: all physical disks, and which one Linux is targeted at.
        # index 0 is always the Windows disk (shrink model); >0 are separate
        # internal disks (whole-disk / free-space model).
        self._disks: tuple[DiskInfo, ...] = ()
        self._target_index = 0
        self._usb_index = 0
        self._usb_scanning = False
        self._usb_confirm_pending: int | None = None
        self._build_info: BuildInfo = load_build_info()
        self._provision_state = StageState.IDLE
        self._provision_error = ""
        # Result of preparing a separate target disk (None for the Windows-disk
        # shrink path); consumed when building the handoff plan.
        self._target_prep: TargetDiskPrepResult | None = None
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
        if not all(
            (self._config.plan_path, self._config.iso_path, self._config.release_manifest_path)
        ):
            self._start_provisioning()

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

    def _usb_choices(self) -> tuple[DiskInfo, ...]:
        return usb_drive_candidates(self._disks)

    def _sync_usb_selection(self, *, clear_missing: bool = False) -> None:
        choices = self._usb_choices()
        if not choices:
            self._usb_index = 0
            if clear_missing:
                self._config.usb_disk_number = -1
            return
        configured = next(
            (index for index, disk in enumerate(choices) if disk.number == self._config.usb_disk_number),
            None,
        )
        if configured is not None:
            self._usb_index = configured
        else:
            self._usb_index = max(0, min(self._usb_index, len(choices) - 1))
            self._config.usb_disk_number = choices[self._usb_index].number
        self._usb_confirm_pending = None

    def _selected_usb(self) -> DiskInfo | None:
        choices = self._usb_choices()
        if not choices:
            return None
        self._usb_index = max(0, min(self._usb_index, len(choices) - 1))
        selected = choices[self._usb_index]
        self._config.usb_disk_number = selected.number
        return selected

    def _usb_plan_lines(self) -> list[str]:
        if self._provision_state == StageState.RUNNING:
            release_line = f"Release: downloading and verifying {self._build_info.release_tag}…"
        elif self._provision_state == StageState.FAILED:
            release_line = f"Release: download failed — {self._provision_error}"
        elif all((self._config.plan_path, self._config.iso_path, self._config.release_manifest_path)):
            release_line = f"Release: ready — {Path(self._config.iso_path).name}"
        else:
            release_line = "Release: not ready"

        choices = self._usb_choices()
        lines = [release_line, "", "USB target (THIS DISK WILL BE ERASED):"]
        if self._usb_scanning:
            lines.append("  Scanning for USB drives…")
        elif not choices:
            lines.append("  No safe USB drive detected. Insert one, then press Enter to scan again.")
        else:
            selected = self._selected_usb()
            for disk in choices:
                marker = ">" if selected is not None and disk.number == selected.number else " "
                serial = f", serial {disk.serial}" if disk.serial else ""
                lines.append(
                    f"{marker} Disk {disk.number}: {disk.model} ({disk.size_gib} GB{serial})"
                )
        return lines

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
                if self._provision_state == StageState.RUNNING:
                    return "Downloading and SHA-256-verifying the paired release ISO…"
                if self._provision_state == StageState.FAILED:
                    return "Release download failed. Press Enter to retry."
                if self._usb_scanning:
                    return "Scanning for USB drives…"
                return "Insert a USB stick, then press Enter to detect it."
            if index == 3 and self._usb_confirm_pending == self._config.usb_disk_number:
                return (
                    f"⚠ Disk {self._config.usb_disk_number} will be completely erased. "
                    "Check the model and size above, then press Enter again to confirm."
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
        if index == 2:
            # "Make room" step: show real disk numbers and the size chooser.
            self._clamp_linux_gib()
            plan = "\n".join(self._partition_plan_lines())
            body = f"{step['what']}\n\n{plan}\n\n{mode_note}"
        elif index == 3:
            usb_plan = "\n".join(self._usb_plan_lines())
            body = f"{step['what']}\n\n{usb_plan}\n\n{mode_note}"
        else:
            body = f"{step['what']}\n\n{mode_note}"
        self.query_one("#wiz-body", Static).update(body)
        self.query_one("#wiz-status", Static).update(self._wizard_status_line(index, step))

        action_label = step["action"]
        if index == 0 and self._can_continue:
            action_hint = "[Enter] Continue"
        else:
            action_hint = f"[Enter] {action_label}"
        hints = ""
        if index == 2 and not self._busy:
            target = self._selected_target()
            if len(self._target_choices()) > 1:
                hints += "   [↑/↓] choose disk"
            # The size chooser is meaningless for a whole empty target disk.
            if target is not None and not self._target_is_whole_disk(target):
                hints += "   [←/→] change size"
        elif index == 3 and not self._busy and len(self._usb_choices()) > 1:
            hints += "   [↑/↓] choose USB"
        cancel_hint = "   [X] Cancel" if self._busy and not self._flow.apply_changes else ""
        self.query_one("#wiz-actions", Static).update(
            f"{action_hint}{hints}   [A] Advanced view{cancel_hint}   [Esc] Quit"
        )

    # -- Disk-space plan and Linux-size chooser (the "Make room" step) -----

    @staticmethod
    def _to_gib(value_bytes: int) -> int:
        return int(value_bytes // GIB)

    def _target_choices(self) -> list[dict[str, Any]]:
        """Where Linux can be installed: the Windows disk (shrink), then each
        other internal disk (USB excluded). Index 0 is always the Windows disk.
        """
        choices: list[dict[str, Any]] = []
        if self._snapshot is None:
            return choices
        win_num = self._snapshot.disk_identity.runtime_disk_number
        win_info = next((d for d in self._disks if d.number == win_num), None)
        win_kind = win_info.kind_label if win_info else "system disk"
        choices.append(
            {
                "kind": "windows",
                "disk_number": win_num,
                "label": f"Windows disk — Disk {win_num} ({win_kind})",
                "info": win_info,
            }
        )
        for info in install_target_candidates(self._disks):
            if info.number == win_num:
                continue
            choices.append(
                {
                    "kind": "separate",
                    "disk_number": info.number,
                    "label": f"Disk {info.number} ({info.kind_label}, {info.size_gib} GB)"
                    + (" — empty" if info.is_empty else f", {info.free_gib} GB free"),
                    "info": info,
                }
            )
        return choices

    def _selected_target(self) -> dict[str, Any] | None:
        choices = self._target_choices()
        if not choices:
            return None
        self._target_index = max(0, min(self._target_index, len(choices) - 1))
        return choices[self._target_index]

    def _target_is_whole_disk(self, target: dict[str, Any]) -> bool:
        """A separate empty disk is used whole; size is fixed at the disk size."""
        info: DiskInfo | None = target.get("info")
        return target["kind"] == "separate" and info is not None and info.is_empty

    def _max_linux_gib(self) -> int:
        """Upper bound for the size chooser, adapted to the selected target.

        The real limits are enforced for real at apply time (shrink range on
        the Windows disk, or the target disk's actual free extent)."""
        target = self._selected_target()
        if target is None or self._snapshot is None:
            return MIN_LINUX_GIB
        if target["kind"] == "windows":
            free = self._to_gib(self._snapshot.prepared_free_space_range.size_bytes)
            windows = self._to_gib(self._snapshot.windows_partition_identity.size_bytes)
            return max(MIN_LINUX_GIB, free + max(0, windows - MIN_WINDOWS_RESERVE_GIB))
        info: DiskInfo | None = target.get("info")
        if info is None:
            return MIN_LINUX_GIB
        if info.is_empty:
            return max(MIN_LINUX_GIB, info.size_gib)  # whole disk
        return max(MIN_LINUX_GIB, info.free_gib)  # free space on a data disk

    def _clamp_linux_gib(self) -> None:
        upper = self._max_linux_gib()
        lower = min(MIN_LINUX_GIB, upper)
        self._linux_gib = max(lower, min(self._linux_gib, upper))
        # Keep the engine's shrink target in lock-step with the chosen size.
        self._flow.target_free_gib = self._linux_gib

    def _partition_plan_lines(self) -> list[str]:
        snap = self._snapshot
        target = self._selected_target()
        if snap is None or target is None:
            return ["(Disk details unavailable — go back to step 1 and re-check.)"]

        choices = self._target_choices()
        lines: list[str] = ["Install Linux to:"]
        for i, choice in enumerate(choices):
            marker = ">" if i == self._target_index else " "
            lines.append(f"  {marker} {choice['label']}")
        if len(choices) == 1:
            lines.append("    (no other internal disks detected; USB drives are excluded)")
        lines.append("")

        if target["kind"] == "windows":
            total = self._to_gib(snap.disk_identity.disk_size_bytes)
            windows = self._to_gib(snap.windows_partition_identity.size_bytes)
            free = self._to_gib(snap.prepared_free_space_range.size_bytes)
            linux = self._linux_gib
            shrink = max(0, linux - free)
            lines += [
                f"Your disk: {total} GB total",
                f"  Windows now: {windows} GB      Already free (unallocated): {free} GB",
                "",
                f"Linux will get: {linux} GB",
            ]
            if shrink <= 0:
                lines.append("  -> Windows will NOT be shrunk — you already have enough free space.")
            else:
                lines.append(
                    f"  -> Windows will shrink from {windows} GB to {windows - shrink} GB "
                    f"(frees {shrink} GB more)."
                )
            return lines

        info: DiskInfo | None = target.get("info")
        if info is None:
            return lines + ["(Target disk details unavailable.)"]
        if info.is_empty:
            lines += [
                f"Disk {info.number} is empty — Linux will use the whole disk.",
                f"Linux will get: {info.size_gib} GB (all of Disk {info.number}).",
                "  -> Your Windows disk is not touched at all (no shrink).",
            ]
        else:
            lines += [
                f"Disk {info.number} has data — Linux will use its free space only.",
                f"Linux will get: {self._linux_gib} GB of {info.free_gib} GB free.",
                "  -> Windows and this disk's existing files are left in place.",
            ]
        return lines

    def _adjust_linux_size(self, delta_gib: int) -> None:
        if self._view != "wizard" or self._current_step_index() != 2 or self._busy:
            return
        target = self._selected_target()
        if target is not None and self._target_is_whole_disk(target):
            return  # a whole empty target disk uses all of itself; size is fixed
        self._linux_gib += delta_gib
        self._clamp_linux_gib()
        self._render_wizard()

    def action_size_up(self) -> None:
        self._adjust_linux_size(LINUX_SIZE_STEP_GIB)

    def action_size_down(self) -> None:
        self._adjust_linux_size(-LINUX_SIZE_STEP_GIB)

    def _cycle_target(self, delta: int) -> None:
        if self._view != "wizard" or self._busy:
            return
        if self._current_step_index() == 3:
            usb_choices = self._usb_choices()
            if len(usb_choices) <= 1:
                return
            self._usb_index = (self._usb_index + delta) % len(usb_choices)
            self._config.usb_disk_number = usb_choices[self._usb_index].number
            self._usb_confirm_pending = None
            self._render_wizard()
            return
        if self._current_step_index() != 2:
            return
        target_choices = self._target_choices()
        if len(target_choices) <= 1:
            return
        self._target_index = (self._target_index + delta) % len(target_choices)
        self._clamp_linux_gib()
        self._render_wizard()

    def action_target_prev(self) -> None:
        self._cycle_target(-1)

    def action_target_next(self) -> None:
        self._cycle_target(1)

    def action_wizard_primary(self) -> None:
        """Enter key: run whatever the current guided step needs."""
        index = self._current_step_index()
        if index == 0:
            self.action_refresh()
        elif index == 1:
            self.action_run_backup_step()
        elif index == 2:
            target = self._selected_target()
            if target is not None and target["kind"] == "separate":
                self.action_run_target_disk_step()
            else:
                self.action_run_partition_step()
        elif index == 3:
            self.action_run_ventoy_step()
        else:
            self.action_continue_flow()

    def action_run_target_disk_step(self) -> None:
        """Prepare a separate target disk (no Windows shrink) for the Linux root."""
        if self._busy:
            self.notify("An operation is already running.", severity="warning")
            return
        required_backup = StageState.SUCCEEDED if self._flow.apply_changes else StageState.SIMULATED
        if self.stage_states["backup"] != required_backup:
            self.notify("Complete the current-mode backup stage first.", severity="warning")
            return
        target = self._selected_target()
        if target is None or target["kind"] != "separate":
            self.notify("Select a separate target disk first.", severity="warning")
            return
        info: DiskInfo | None = target.get("info")
        mode = "whole_disk" if (info is not None and info.is_empty) else "free_space"
        self._set_busy(True)
        self._target_prep = None
        self.stage_states["partition"] = StageState.RUNNING
        self.stage_states["handoff"] = StageState.IDLE
        self._handoff_result = None
        self._refresh_views()
        self._target_disk_worker(int(target["disk_number"]), mode, self._linux_gib)

    @work(thread=True, exclusive=True, group="partition")
    def _target_disk_worker(self, disk_number: int, mode: str, requested_gib: int) -> None:
        apply_mode = self._flow.apply_changes
        try:
            snapshot = collect_target_disk_snapshot(disk_number, mode=mode)
            prep = prepare_target_disk(
                snapshot,
                requested_linux_bytes=requested_gib * GIB,
                minimum_linux_bytes=MIN_LINUX_GIB * GIB,
            )
            if not prep.fits:
                failure = FlowStepResult(
                    "partition",
                    False,
                    apply_mode,
                    f"Disk {disk_number} does not have enough free space for Linux "
                    f"({MIN_LINUX_GIB} GB minimum).",
                )
                self.call_from_thread(self._apply_target_result, None, None, failure, failure.summary)
                return
            gib = prep.linux_bytes // GIB
            erase = " (existing data on it will be erased)" if prep.would_erase_existing_data else ""
            mode_tag = "APPLY" if apply_mode else "SIMULATION"
            success = FlowStepResult(
                "partition",
                True,
                apply_mode,
                f"[{mode_tag}] Linux will use {gib} GB on Disk {disk_number}{erase}.",
                payload={"disk_number": disk_number, "mode": mode},
            )
            self.call_from_thread(self._apply_target_result, snapshot, prep, success, None)
        except (DiskProbeError, TargetDiskPrepError, OSError, ValueError) as exc:
            failure = FlowStepResult("partition", False, apply_mode, str(exc))
            self.call_from_thread(self._apply_target_result, None, None, failure, str(exc))

    @staticmethod
    def _linux_install_target_dict(
        snapshot: TargetDiskSnapshot, prep: TargetDiskPrepResult
    ) -> dict[str, Any]:
        # A RAW/empty disk has no GPT GUID yet (it is created at install time);
        # synthesise a stable placeholder so the plan validates. The target is
        # resolved on the live side by serial+size as well as GUID.
        guid = snapshot.gpt_disk_guid or f"00000000-0000-4000-8000-{snapshot.disk_number:012d}"
        return {
            "disk_identity": {
                "gpt_disk_guid": guid,
                "disk_size_bytes": snapshot.disk_size_bytes,
                "logical_sector_size": snapshot.logical_sector_size,
                "disk_model": snapshot.model,
                "disk_serial": snapshot.serial,
                "runtime_disk_number": snapshot.disk_number,
                "partition_style": "GPT",
            },
            "install_range": prep.install_partition_range.model_dump(mode="json"),
            "mode": prep.mode,
            "erases_existing_data": prep.would_erase_existing_data,
        }

    def _apply_target_result(
        self,
        snapshot: TargetDiskSnapshot | None,
        prep: TargetDiskPrepResult | None,
        result: FlowStepResult,
        error: str | None,
    ) -> None:
        if error or not result.ok or snapshot is None or prep is None:
            self.stage_states["partition"] = StageState.FAILED
            self._partition_result = None
            self._target_prep = None
            self._flow._linux_install_target = None
            self.notify(error or result.summary, severity="error")
        else:
            self.stage_states["partition"] = (
                StageState.SUCCEEDED if self._flow.apply_changes else StageState.SIMULATED
            )
            self._partition_result = result
            self._target_prep = prep
            # For a separate-disk install the Windows disk is left as-is, so its
            # "prepared" snapshot is simply the current snapshot; attach the
            # target so the handoff plan carries linux_install_target.
            self._flow._prepared_snapshot = self._snapshot
            self._flow._linux_install_target = self._linux_install_target_dict(snapshot, prep)
            self.notify(result.summary, severity="information")
        self._set_busy(False)
        self._append_note(result.summary)
        self._refresh_views()
        if not error and result.ok:
            self._start_usb_scan()

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

    @staticmethod
    def _collect_disk_inventory_safe() -> tuple[DiskInfo, ...]:
        """Best-effort physical-disk inventory; never blocks preflight on failure."""
        try:
            return collect_disk_inventory()
        except (DiskInventoryError, OSError, ValueError):
            return ()

    def _start_provisioning(self) -> None:
        if self._provision_state == StageState.RUNNING:
            return
        if not self._build_info.can_provision:
            self._provision_state = StageState.FAILED
            self._provision_error = (
                "this build has no release tag or bundled plan template; use a release EXE"
            )
            self._refresh_views()
            return
        self._provision_state = StageState.RUNNING
        self._provision_error = ""
        self.notify(
            f"Downloading and verifying the paired ISO for {self._build_info.release_tag}…",
            severity="information",
        )
        self._refresh_views()
        self._provision_worker()

    @work(thread=True, exclusive=True, group="provisioning")
    def _provision_worker(self) -> None:
        try:
            assets = provision_release_assets(
                tag=self._build_info.release_tag,
                repo=self._build_info.release_repo,
                template_path=self._build_info.template_path,
                producer_version=self._build_info.producer_version,
            )
            self.call_from_thread(self._apply_provisioning, assets, None)
        except (OSError, ProvisioningError, RuntimeError, ValueError) as exc:
            self.call_from_thread(self._apply_provisioning, None, str(exc))

    def _apply_provisioning(
        self,
        assets: ProvisionedAssets | None,
        error: str | None,
    ) -> None:
        if error or assets is None:
            self._provision_state = StageState.FAILED
            self._provision_error = error or "release provisioning failed"
            self.notify(self._provision_error, severity="error")
        else:
            self._config.plan_path = str(assets.plan_path)
            self._config.iso_path = str(assets.iso_path)
            self._config.release_manifest_path = str(assets.release_manifest_path)
            self._provision_state = StageState.SUCCEEDED
            self._provision_error = ""
            self.notify(
                f"Release {assets.tag} is ready: {assets.iso_path.name}",
                severity="information",
            )
        self._refresh_views()

    def _start_usb_scan(self) -> None:
        if self._usb_scanning:
            return
        self._usb_scanning = True
        self._usb_confirm_pending = None
        self._refresh_views()
        self._usb_scan_worker()

    @work(thread=True, exclusive=True, group="usb-scan")
    def _usb_scan_worker(self) -> None:
        try:
            disks = collect_disk_inventory()
            self.call_from_thread(self._apply_usb_scan, disks, None)
        except (DiskInventoryError, OSError, RuntimeError, ValueError) as exc:
            self.call_from_thread(self._apply_usb_scan, (), str(exc))

    def _apply_usb_scan(self, disks: tuple[DiskInfo, ...], error: str | None) -> None:
        self._usb_scanning = False
        if error:
            self.notify(f"USB scan failed: {error}", severity="error")
        else:
            self._disks = disks
            self._sync_usb_selection(clear_missing=True)
            choices = self._usb_choices()
            if len(choices) == 1:
                self.notify(
                    f"USB Disk {choices[0].number} selected automatically.",
                    severity="information",
                )
            elif len(choices) > 1:
                self.notify("Multiple USB drives found; choose one with ↑/↓.", severity="warning")
        self._refresh_views()

    @work(thread=True, exclusive=True, group="preflight")
    def _refresh_worker(self) -> None:
        try:
            report = run_windows_preflight()
            checks, can_proceed = _coerce_report(report)
            snapshot = collect_disk_probe_snapshot() if can_proceed else None
            disks = self._collect_disk_inventory_safe() if can_proceed else ()
            self.call_from_thread(self._apply_refresh, checks, can_proceed, snapshot, None, disks)
        except (DiskProbeError, OSError, RuntimeError, ValueError) as exc:
            self.call_from_thread(self._apply_refresh, [], False, None, str(exc), ())

    def _apply_refresh(
        self,
        checks: list[dict[str, str]],
        can_proceed: bool,
        snapshot: DiskProbeSnapshot | None,
        error: str | None,
        disks: tuple[DiskInfo, ...] = (),
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
        self._disks = disks
        self._target_index = 0  # default back to the Windows disk on every refresh
        self._sync_usb_selection()
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
        def run_handoff() -> FlowStepResult:
            confirmation = self._config.usb_confirmation
            if self._flow.apply_changes and not confirmation:
                confirmation = build_usb_erase_confirmation(self._config.usb_disk_number)
            return self._flow.run_ventoy_handoff(
                plan_path=self._config.plan_path,
                iso_path=self._config.iso_path,
                release_manifest_path=self._config.release_manifest_path,
                usb_disk_number=self._config.usb_disk_number,
                usb_confirmation=confirmation,
                allow_ventoy_install=self._config.allow_ventoy_install,
            )

        self._run_flow_worker(
            "handoff",
            run_handoff,
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
        if stage == "partition" and not error and result is not None and result.ok:
            self._start_usb_scan()

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
        if not all((self._config.plan_path, self._config.iso_path, self._config.release_manifest_path)):
            self.notify("The paired release ISO is not ready yet.", severity="warning")
            self._start_provisioning()
            return
        if self._selected_usb() is None and self._config.usb_disk_number < 0:
            self.notify("Insert a USB drive; scanning again now.", severity="warning")
            self._start_usb_scan()
            return
        if (
            self._flow.apply_changes
            and self._usb_confirm_pending != self._config.usb_disk_number
        ):
            self._usb_confirm_pending = self._config.usb_disk_number
            self.notify(
                f"Confirm the selected USB: press Enter again to erase Disk {self._config.usb_disk_number}.",
                severity="warning",
            )
            self._render_wizard()
            return
        self._set_busy(True)
        self._usb_confirm_pending = None
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
    allow_ventoy_install: bool = True,
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
