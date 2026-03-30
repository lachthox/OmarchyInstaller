"""Windows Python TUI entrypoint for end-to-end prep flow."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
from typing import Any

from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Footer, Header, Static

from .checks import run_windows_preflight
from .disk_probe import DiskProbeError, collect_disk_probe_snapshot
from .flow import FlowStepResult, WindowsMigrationFlow
from .handoff import VentoyError, find_ventoy_cli_path, validate_ventoy_usb


EXIT_QUIT = 0
EXIT_LAUNCH_LEGACY = 10
GIB = 1024**3
WINDOWS_STAGES: tuple[str, ...] = (
    "settings",
    "welcome",
    "compatibility",
    "backup",
    "partition_prep",
    "ventoy_usb",
    "secure_boot",
    "network",
    "summary",
    "confirm",
    "error_handling",
)

CHECK_LABELS = {
    "admin": "Admin",
    "windows_version": "Windows",
    "boot_mode": "Boot Mode",
    "partition_style": "Partition Style",
    "secure_boot": "Secure Boot",
    "bitlocker": "BitLocker",
    "fast_startup": "Fast Startup",
    "winre": "WinRE",
}


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


def _status_label(status: str) -> str:
    return {"pass": "PASS", "warn": "WARN", "fail": "FAIL"}.get(status, status.upper() or "UNKNOWN")


@dataclass(slots=True)
class WindowsTuiConfig:
    launch_legacy_on_continue: bool = False
    apply_changes: bool = False
    target_free_gib: int = 120
    backup_destination: str | None = None
    backup_fallback_destination: str | None = None
    ventoy_disk_number: int | None = None
    source_iso_path: str | None = None
    yolo_mode: bool = False
    yolo_approved_failures: tuple[str, ...] = ()


class WindowsPrepApp(App[int]):
    """Interactive Windows prep TUI across all Windows contract stages."""

    CSS = """
    Screen { layout: vertical; background: #0f172a; color: #e2e8f0; }
    #body { padding: 1 2; height: 1fr; }
    #title { margin-bottom: 1; text-style: bold; color: #f8fafc; }
    #stages { margin-bottom: 1; color: #cbd5e1; }
    #content { height: 1fr; border: round #334155; padding: 1 2; background: #111827; }
    #status { color: #93c5fd; margin-top: 1; }
    #hints { color: #94a3b8; margin-top: 1; }
    """

    BINDINGS = [
        Binding("enter,space", "do_next_step", "Next Step"),
        Binding("r", "refresh_runtime", "Refresh"),
        Binding("d", "toggle_details", "Details"),
        Binding("t", "toggle_yolo_mode", "Toggle YOLO"),
        Binding("c", "do_next_step", "Next Step"),
        Binding("q", "quit_flow", "Quit"),
    ]

    def __init__(self, config: WindowsTuiConfig | None = None) -> None:
        super().__init__()
        self._config = config or WindowsTuiConfig()
        self._stage_idx = 0
        self._checks: list[dict[str, str]] = []
        self._can_continue = False
        self._snapshot_summary = "Disk snapshot not collected yet."
        self._notes: list[str] = []
        self._last_error = ""
        self._status_message = "Ready."
        self._show_details = False
        self._simple_step_idx = 0
        self._yolo_mode = bool(self._config.yolo_mode)
        self._yolo_approved_failures = {
            str(name).strip().lower()
            for name in self._config.yolo_approved_failures
            if str(name).strip()
        }
        self._backup_result: FlowStepResult | None = None
        self._partition_result: FlowStepResult | None = None
        self._compat_prompt_active = False
        self._compat_prompt_index = 0
        self._compat_prompt_failures: list[dict[str, str]] = []
        self._compat_prompt_message = ""
        self._ventoy_cli_path = ""
        self._ventoy_summary = "Ventoy USB not validated yet."
        self._ventoy_validated = False
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
            yield Static("", id="stages")
            yield Static("", id="content")
            yield Static("", id="status")
            yield Static(
                "Keys: [Enter] next  [R] refresh  [D] details  [Q] quit",
                id="hints",
            )
        if self._show_details:
            yield Footer()

    def on_mount(self) -> None:
        self.action_refresh_runtime()

    def _check_map(self) -> dict[str, dict[str, str]]:
        return {check["name"]: check for check in self._checks}

    def _append_note(self, text: str) -> None:
        self._notes.append(text)
        if len(self._notes) > 8:
            self._notes = self._notes[-8:]

    def _mode(self) -> str:
        return "APPLY" if self._flow.apply_changes else "DRY-RUN"

    def _flow_readiness(self) -> tuple[bool, list[str]]:
        blockers: list[str] = []
        if not self._compatibility_allows_progress():
            blockers.append("Resolve FAIL checks in compatibility.")
        if not self._backup_result or not self._backup_result.ok:
            blockers.append("Backup step has not completed successfully.")
        if not self._partition_result or not self._partition_result.ok:
            blockers.append("Partition prep has not completed successfully.")
        if self._config.ventoy_disk_number is not None and not self._ventoy_validated:
            blockers.append("Configured Ventoy USB has not been validated.")
        return len(blockers) == 0, blockers

    def _unapproved_failures(self) -> list[dict[str, str]]:
        failures = [check for check in self._checks if check.get("status") == "fail"]
        if not self._yolo_mode:
            return failures
        return [
            check
            for check in failures
            if check.get("name", "").strip().lower() not in self._yolo_approved_failures
        ]

    def _compatibility_allows_progress(self) -> bool:
        if self._can_continue:
            return True
        return self._yolo_mode and len(self._unapproved_failures()) == 0

    def _stage_health(self, stage: str) -> str:
        if stage == "compatibility":
            return "ok" if self._can_continue else "blocked"
        if stage == "backup":
            return "ok" if self._backup_result and self._backup_result.ok else "pending"
        if stage == "partition_prep":
            return "ok" if self._partition_result and self._partition_result.ok else "pending"
        if stage == "ventoy_usb":
            if self._config.ventoy_disk_number is None:
                return "optional"
            return "ok" if self._ventoy_validated else "pending"
        if stage in {"summary", "confirm"}:
            return "ok" if self._flow_readiness()[0] else "blocked"
        if stage == "error_handling":
            return "warn" if self._last_error or any(c["status"] == "fail" for c in self._checks) else "ok"
        return "ok"

    def _render_stage_bar(self) -> str:
        yolo_label = " YOLO:ON" if self._yolo_mode else " YOLO:OFF"
        if not self._show_details:
            step = WINDOWS_STAGES[self._simple_step_idx]
            visible_steps = [item for item in WINDOWS_STAGES if item not in {"error_handling", "network", "secure_boot"}]
            pos = visible_steps.index(step) + 1 if step in visible_steps else 1
            return (
                f"Simple mode: one step at a time. Step {pos}/{len(visible_steps)}: {step}. "
                f"Press [D] for advanced details.{yolo_label}"
            )
        parts: list[str] = []
        for i, stage in enumerate(WINDOWS_STAGES, start=1):
            active = "*" if i - 1 == self._stage_idx else " "
            parts.append(f"{active}{i % 10}:{stage}[{self._stage_health(stage)}]")
        return "  ".join(parts) + yolo_label

    def _checks_table(self) -> str:
        if not self._checks:
            return "No checks collected yet."
        lines = ["Check              Status  Value    Details", "-" * 78]
        for check in self._checks:
            label = CHECK_LABELS.get(check["name"], check["name"])
            lines.append(f"{label:<18} {_status_label(check['status']):<6} {check['value']:<8} {check['message']}")
        return "\n".join(lines)

    def _simple_content(self) -> str:
        step = WINDOWS_STAGES[self._simple_step_idx]
        ready, blockers = self._flow_readiness()
        mode_line = f"Mode: {self._mode()}"

        if step == "settings":
            yolo_line = (
                f"YOLO is ON ({len(self._yolo_approved_failures)} fail checks approved)."
                if self._yolo_mode
                else "YOLO is OFF."
            )
            return "\n".join(
                [
                    "Settings",
                    mode_line,
                    yolo_line,
                    "",
                    "Use [T] on this screen to toggle YOLO mode.",
                    "Press [Enter] to continue to compatibility checks.",
                ]
            )

        if step == "welcome":
            return "\n".join(
                [
                    "Welcome",
                    mode_line,
                    "",
                    "This wizard will guide you one step at a time:",
                    "1. Compatibility checks",
                    "2. Backup boot data",
                    "3. Prepare free space",
                    "4. Validate Ventoy USB (optional)",
                    "5. Confirm and continue",
                    "",
                    "Press [Enter] to continue.",
                ]
            )

        if step == "compatibility":
            failures = self._unapproved_failures()
            if self._compat_prompt_active and self._compat_prompt_failures:
                idx = min(self._compat_prompt_index, len(self._compat_prompt_failures) - 1)
                failure = self._compat_prompt_failures[idx]
                label = CHECK_LABELS.get(failure.get("name", ""), failure.get("name", "unknown"))
                return "\n".join(
                    [
                        "Compatibility",
                        f"Failing check {idx + 1}/{len(self._compat_prompt_failures)}",
                        "",
                        f"{label}",
                        failure.get("message", ""),
                        "",
                        (self._compat_prompt_message or "Attempt auto-fix for this check? [Y/N]"),
                    ]
                )
            if not failures:
                state = "Ready"
                details = "All required compatibility checks are passing."
            else:
                state = "Needs attention"
                details = "\n".join(
                    f"- {CHECK_LABELS.get(c['name'], c['name'])}: {c['message']}"
                    for c in failures[:5]
                )
            return "\n".join(
                [
                    "Compatibility",
                    mode_line,
                    f"State: {state}",
                    "",
                    details,
                    "",
                    "Press [Enter] to review each failure and choose auto-fix [Y/N].",
                ]
            )

        if step == "backup":
            status = self._backup_result.summary if self._backup_result else "Not run yet."
            return "\n".join(
                [
                    "Backup",
                    mode_line,
                    f"Status: {status}",
                    "",
                    "Press [Enter] to run backup step.",
                ]
            )

        if step == "partition_prep":
            status = self._partition_result.summary if self._partition_result else "Not run yet."
            return "\n".join(
                [
                    "Partition Prep",
                    mode_line,
                    f"Status: {status}",
                    "",
                    "Press [Enter] to prepare free space.",
                ]
            )

        if step == "ventoy_usb":
            if self._config.ventoy_disk_number is None:
                return "\n".join(
                    [
                        "Ventoy USB",
                        "Not required for this run.",
                        "",
                        "Press [Enter] to continue.",
                    ]
                )
            return "\n".join(
                [
                    "Ventoy USB",
                    f"Disk: {self._config.ventoy_disk_number}",
                    f"Status: {self._ventoy_summary}",
                    "",
                    "Press [Enter] to validate Ventoy USB.",
                ]
            )

        if step == "summary":
            blocker_lines = "\n".join(f"- {item}" for item in blockers) if blockers else "- none"
            return "\n".join(
                [
                    "Summary",
                    mode_line,
                    f"Ready to continue: {'Yes' if ready else 'No'}",
                    "",
                    "Blockers:",
                    blocker_lines,
                    "",
                    "Press [Enter] to continue to confirmation.",
                ]
            )

        if step == "confirm":
            return "\n".join(
                [
                    "Confirm",
                    f"Ready to continue: {'Yes' if ready else 'No'}",
                    "",
                    "Press [Enter] to complete Windows prep flow.",
                ]
            )

        return "Guided step unavailable."

    def _detailed_content(self) -> str:
        stage = WINDOWS_STAGES[self._stage_idx]
        checks = self._check_map()
        mode_line = f"Mode: {self._mode()} (target free space: {self._flow.target_free_gib} GiB)"
        backup = self._backup_result.summary if self._backup_result else "Backup step not executed yet."
        partition = self._partition_result.summary if self._partition_result else "Partition prep step not executed yet."
        recent = " | ".join(self._notes[-3:]) if self._notes else "No actions yet."
        ready, blockers = self._flow_readiness()
        if stage == "welcome":
            yolo_line = (
                f"YOLO: enabled ({len(self._yolo_approved_failures)} approved FAIL checks)."
                if self._yolo_mode
                else "YOLO: disabled."
            )
            return f"Welcome\n{mode_line}\n{yolo_line}\n\nPath: compatibility -> backup -> partition -> summary -> confirm\nRecent: {recent}"
        if stage == "settings":
            yolo_line = (
                f"YOLO: enabled ({len(self._yolo_approved_failures)} approved FAIL checks)."
                if self._yolo_mode
                else "YOLO: disabled."
            )
            return (
                f"Settings\n{mode_line}\n{yolo_line}\n\n"
                "Toggle YOLO in this settings screen with [T]."
            )
        if stage == "compatibility":
            compat_state = "READY" if self._compatibility_allows_progress() else "BLOCKED"
            yolo_suffix = " (YOLO override active)" if self._yolo_mode and not self._can_continue else ""
            yolo_line = (
                f"YOLO approvals: {', '.join(sorted(self._yolo_approved_failures)) or 'none'}"
                if self._yolo_mode
                else "YOLO approvals: n/a"
            )
            return f"Compatibility Checks\n{mode_line}\n{self._snapshot_summary}\n\n{self._checks_table()}\n\nState: {compat_state}{yolo_suffix}\n{yolo_line}"
        if stage == "backup":
            return f"Backup Stage\n{mode_line}\nPrimary: {self._flow._resolve_backup_destination()}\nFallback: {self._config.backup_fallback_destination or 'none'}\n\nResult: {backup}\n\nPress B to run."
        if stage == "partition_prep":
            return f"Partition Prep Stage\n{mode_line}\n{self._snapshot_summary}\n\nResult: {partition}\n\nPress S to run."
        if stage == "ventoy_usb":
            disk = str(self._config.ventoy_disk_number) if self._config.ventoy_disk_number is not None else "not configured"
            iso = self._config.source_iso_path or "not configured"
            return f"Ventoy USB Stage\nVentoy CLI: {self._ventoy_cli_path or 'not found'}\nDisk Number: {disk}\nISO Path: {iso}\n\nValidation: {self._ventoy_summary}\n\nPress V to validate."
        if stage == "secure_boot":
            return (
                "Secure Boot / Safety\n"
                f"Secure Boot: {_status_label(checks.get('secure_boot', {}).get('status', 'unknown'))}\n"
                f"BitLocker: {_status_label(checks.get('bitlocker', {}).get('status', 'unknown'))}\n"
                f"Fast Startup: {_status_label(checks.get('fast_startup', {}).get('status', 'unknown'))}\n"
                f"WinRE: {_status_label(checks.get('winre', {}).get('status', 'unknown'))}\n\n"
                f"{checks.get('secure_boot', {}).get('message', 'Run compatibility checks first.')}"
            )
        if stage == "network":
            return "Network Handoff\nWindows-side Wi-Fi handoff is optional in this flow.\nNo blocking action in this stage."
        if stage == "summary":
            bl = "\n".join(f"- {b}" for b in blockers) if blockers else "- none"
            return f"Summary\n{mode_line}\nCompatibility: {'READY' if self._can_continue else 'BLOCKED'}\nBackup: {backup}\nPartition: {partition}\nVentoy: {self._ventoy_summary}\n\nReady: {ready}\nBlockers:\n{bl}"
        if stage == "confirm":
            target = "legacy PowerShell flow" if self._config.launch_legacy_on_continue else "Python-only completion"
            return f"Confirm\nContinue target: {target}\nReady: {ready}\n\nPress C to continue."
        fails = [f"- {CHECK_LABELS.get(c['name'], c['name'])}: {c['message']}" for c in self._checks if c["status"] == "fail"]
        warns = [f"- {CHECK_LABELS.get(c['name'], c['name'])}: {c['message']}" for c in self._checks if c["status"] == "warn"]
        return f"Error Handling\nLast Error: {self._last_error or 'none'}\nFailures:\n{'\n'.join(fails) if fails else '- none'}\nWarnings:\n{'\n'.join(warns) if warns else '- none'}"

    def _content(self) -> str:
        if self._show_details:
            return self._detailed_content()
        return self._simple_content()

    def _render(self) -> None:
        self.query_one("#stages", Static).update(self._render_stage_bar())
        self.query_one("#content", Static).update(self._content())
        self.query_one("#status", Static).update(f"Status: {self._status_message}")

    def _set_status(self, message: str) -> None:
        self._status_message = message

    def _set_stage(self, idx: int) -> None:
        self._stage_idx = max(0, min(idx, len(WINDOWS_STAGES) - 1))
        self._set_status(f"Stage: {WINDOWS_STAGES[self._stage_idx]}.")
        self._render()

    def action_refresh_runtime(self) -> None:
        self._checks, self._can_continue = _coerce_report(run_windows_preflight())
        cli = find_ventoy_cli_path()
        self._ventoy_cli_path = str(cli) if cli else ""
        if self._can_continue:
            try:
                snapshot = collect_disk_probe_snapshot()
                free_gib = round(snapshot.prepared_free_space_range.size_bytes / GIB, 1)
                self._snapshot_summary = (
                    f"Disk {snapshot.disk_identity.disk_model} free range: {free_gib} GiB "
                    f"(partition style: {snapshot.disk_identity.partition_style})"
                )
            except (DiskProbeError, ValueError) as exc:
                self._snapshot_summary = f"Disk snapshot warning: {exc}"
        else:
            self._snapshot_summary = "Resolve FAIL checks before proceeding."
        self._last_error = ""
        self._append_note(f"Preflight refresh: {'ready' if self._can_continue else 'blocked'}")
        self._set_status("Preflight refreshed.")
        self._render()
        if not self._unapproved_failures():
            self._compat_prompt_active = False
            self._compat_prompt_index = 0
            self._compat_prompt_failures = []
            self._compat_prompt_message = ""

    def _start_compat_prompt(self) -> None:
        self._compat_prompt_failures = self._unapproved_failures()
        self._compat_prompt_index = 0
        self._compat_prompt_active = bool(self._compat_prompt_failures)
        self._compat_prompt_message = "Attempt auto-fix for this check? [Y/N]"

    def _attempt_fix_for_failure(self, name: str) -> tuple[bool, str]:
        key = name.strip().lower()
        if key == "fast_startup":
            subprocess.run(
                ["powershell.exe", "-NoProfile", "-Command", "powercfg /h off; Set-ItemProperty -Path 'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Session Manager\\Power' -Name HiberbootEnabled -Type DWord -Value 0 -ErrorAction SilentlyContinue"],
                capture_output=True,
                text=True,
                check=False,
            )
            return True, "Attempted to disable Fast Startup."
        if key == "winre":
            completed = subprocess.run(
                ["reagentc.exe", "/enable"],
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode == 0:
                return True, "Attempted to enable Windows RE."
            detail = completed.stderr.strip() or completed.stdout.strip() or "Unknown reagentc error."
            return False, f"Could not enable WinRE automatically: {detail}"
        if key == "admin":
            return False, "Cannot auto-fix admin from inside app. Relaunch as Administrator."
        if key == "bitlocker":
            system_drive = (os.environ.get("SystemDrive", "C:") or "C:").strip()
            completed = subprocess.run(
                ["manage-bde.exe", "-off", system_drive],
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode == 0:
                return (
                    True,
                    "Attempted BitLocker decryption start. Progress may take time; flow remains blocked until fully decrypted.",
                )
            detail = completed.stderr.strip() or completed.stdout.strip() or "Unknown manage-bde error."
            return False, f"Could not start BitLocker decryption: {detail}"
        if key == "secure_boot":
            return False, "Secure Boot must be changed in BIOS/UEFI firmware."
        if key == "boot_mode":
            return False, "Boot mode must be changed in BIOS/UEFI firmware."
        if key == "partition_style":
            return False, "Partition style conversion is destructive; manual operation required."
        if key == "windows_version":
            return False, "Windows version upgrade must be done manually."
        return False, "No automatic fix is available for this check."

    def _handle_compat_prompt_response(self, do_fix: bool) -> None:
        if not self._compat_prompt_active or not self._compat_prompt_failures:
            return
        idx = min(self._compat_prompt_index, len(self._compat_prompt_failures) - 1)
        failure = self._compat_prompt_failures[idx]
        label = CHECK_LABELS.get(failure.get("name", ""), failure.get("name", "unknown"))

        if do_fix:
            ok, message = self._attempt_fix_for_failure(failure.get("name", ""))
            self._append_note(f"{label}: {message}")
            self._compat_prompt_message = f"{label}: {message}"
        else:
            self._append_note(f"{label}: auto-fix skipped by user.")
            self._compat_prompt_message = f"{label}: skipped."

        # Move to the next item in this review pass before refreshing list state.
        self._compat_prompt_index += 1
        self.action_refresh_runtime()
        remaining = self._unapproved_failures()
        self._compat_prompt_failures = remaining
        if not remaining:
            self._compat_prompt_active = False
            self._compat_prompt_index = 0
            self._compat_prompt_message = "All compatibility failures cleared."
            self._set_status("Compatibility failures cleared.")
            self._render()
            return

        if self._compat_prompt_index >= len(remaining):
            self._compat_prompt_active = False
            self._compat_prompt_index = 0
            self._compat_prompt_message = "Compatibility review pass complete."
            self._set_status("Some failures still remain. Press [Enter] to review again.")
            self._render()
            return

        self._compat_prompt_message = "Attempt auto-fix for this check? [Y/N]"
        self._set_status("Choose [Y] or [N] for each failing check.")
        self._render()

    def action_toggle_apply_mode(self) -> None:
        self._flow.apply_changes = not self._flow.apply_changes
        self._append_note(f"Mode switched to {self._mode()}")
        self._set_status(f"Mode switched to {self._mode()}.")
        self._render()

    def action_toggle_yolo_mode(self) -> None:
        """Toggle YOLO mode."""
        if not self._show_details and WINDOWS_STAGES[self._simple_step_idx] != "settings":
            self._set_status("Open the Settings step to change YOLO mode.")
            self._render()
            return
        if self._yolo_mode:
            self._yolo_mode = False
            self._yolo_approved_failures.clear()
            self._append_note("YOLO disabled.")
            self._set_status("YOLO mode disabled.")
            self._render()
            return

        if not self._checks:
            self._checks, self._can_continue = _coerce_report(run_windows_preflight())
        fail_names = {
            check.get("name", "").strip().lower()
            for check in self._checks
            if check.get("status") == "fail" and check.get("name", "").strip()
        }
        self._yolo_mode = True
        self._yolo_approved_failures.update(fail_names)
        self._append_note(f"YOLO enabled ({len(fail_names)} fail checks approved).")
        self._set_status(f"YOLO mode enabled. Approved {len(fail_names)} fail checks.")
        self._render()

    def action_run_backup(self) -> None:
        if not self._compatibility_allows_progress():
            message = "Blocked: resolve FAIL checks in compatibility first."
            self._set_status(message)
            self.notify(message, severity="error")
            return
        self._backup_result = self._flow.run_backup()
        self._last_error = "" if self._backup_result.ok else self._backup_result.summary
        self._append_note(self._backup_result.summary)
        self._set_status(self._backup_result.summary)
        self._render()

    def action_run_partition(self) -> None:
        if not self._compatibility_allows_progress():
            message = "Blocked: resolve FAIL checks in compatibility first."
            self._set_status(message)
            self.notify(message, severity="error")
            return
        if not self._backup_result or not self._backup_result.ok:
            message = "Blocked: run backup first."
            self._set_status(message)
            self.notify(message, severity="warning")
            return
        self._partition_result = self._flow.run_partition_prep()
        self._last_error = "" if self._partition_result.ok else self._partition_result.summary
        self._append_note(self._partition_result.summary)
        self._set_status(self._partition_result.summary)
        self._render()

    def action_validate_ventoy(self) -> None:
        if self._config.ventoy_disk_number is None:
            message = "Ventoy skipped: no disk number configured."
            self._set_status(message)
            self.notify(message, severity="warning")
            return
        payload_paths: list[str] = []
        if self._config.source_iso_path:
            source = Path(self._config.source_iso_path)
            if source.exists() and source.is_file():
                payload_paths.append(str(source))
        try:
            validation = validate_ventoy_usb(self._config.ventoy_disk_number, payload_paths=payload_paths)
            free_gib = round(validation.free_bytes / GIB, 2)
            need_gib = round(validation.required_bytes / GIB, 2)
            self._ventoy_summary = f"Validated {validation.data_root}; free {free_gib} GiB, required {need_gib} GiB"
            self._ventoy_validated = True
            self._last_error = ""
            self._set_status("Ventoy validation passed.")
        except VentoyError as exc:
            self._ventoy_summary = f"Validation failed: {exc}"
            self._ventoy_validated = False
            self._last_error = str(exc)
            self._set_status(self._ventoy_summary)
        self._append_note(self._ventoy_summary)
        self._render()

    def action_continue_flow(self) -> None:
        if not self._backup_result or not self._backup_result.ok:
            self.action_run_backup()
        if not self._partition_result or not self._partition_result.ok:
            self.action_run_partition()
        if self._config.ventoy_disk_number is not None and not self._ventoy_validated:
            self.action_validate_ventoy()
        ready, blockers = self._flow_readiness()
        if not ready:
            self._last_error = blockers[0]
            self._set_status(self._last_error)
            self._set_stage(9)
            return
        if self._config.launch_legacy_on_continue:
            self._set_status("Continuing to legacy PowerShell flow.")
            self.exit(EXIT_LAUNCH_LEGACY)
            return
        self._set_status("Windows Python prep flow completed.")
        self.exit(EXIT_QUIT)

    def action_do_next_step(self) -> None:
        if not self._show_details:
            step = WINDOWS_STAGES[self._simple_step_idx]
            if step == "settings":
                self._simple_step_idx = WINDOWS_STAGES.index("welcome")
            elif step == "welcome":
                self._simple_step_idx = WINDOWS_STAGES.index("compatibility")
            elif step == "compatibility":
                if not self._compatibility_allows_progress():
                    self._start_compat_prompt()
                    if self._compat_prompt_active:
                        self._set_status("Compatibility checks are blocking progress. Choose [Y] or [N].")
                    else:
                        self._set_status("Compatibility checks are blocking progress. Press [R].")
                    self._render()
                    return
                self._simple_step_idx = WINDOWS_STAGES.index("backup")
            elif step == "backup":
                self.action_run_backup()
                if not self._backup_result or not self._backup_result.ok:
                    return
                self._simple_step_idx = WINDOWS_STAGES.index("partition_prep")
            elif step == "partition_prep":
                self.action_run_partition()
                if not self._partition_result or not self._partition_result.ok:
                    return
                if self._config.ventoy_disk_number is None:
                    self._simple_step_idx = WINDOWS_STAGES.index("summary")
                else:
                    self._simple_step_idx = WINDOWS_STAGES.index("ventoy_usb")
            elif step == "ventoy_usb":
                if self._config.ventoy_disk_number is not None and not self._ventoy_validated:
                    self.action_validate_ventoy()
                    if not self._ventoy_validated:
                        return
                self._simple_step_idx = WINDOWS_STAGES.index("summary")
            elif step == "summary":
                self._simple_step_idx = WINDOWS_STAGES.index("confirm")
            elif step == "confirm":
                self.action_continue_flow()
                return
            self._set_status(f"Step: {WINDOWS_STAGES[self._simple_step_idx]}.")
            self._render()
            return

        if not self._compatibility_allows_progress():
            self._set_stage(1)
            self._set_status("Compatibility checks are blocking progress. Fix the listed items, then press [R].")
            self._render()
            return
        if not self._backup_result or not self._backup_result.ok:
            self.action_run_backup()
            return
        if not self._partition_result or not self._partition_result.ok:
            self.action_run_partition()
            return
        if self._config.ventoy_disk_number is not None and not self._ventoy_validated:
            self.action_validate_ventoy()
            return
        self.action_continue_flow()

    def action_toggle_details(self) -> None:
        self._show_details = not self._show_details
        if self._show_details and not self._checks:
            self.action_refresh_runtime()
            self._set_status("Detailed view enabled. Checks refreshed.")
        else:
            self._set_status("Detailed view enabled." if self._show_details else "Simple view enabled.")
        if not self._show_details:
            self._stage_idx = WINDOWS_STAGES.index("welcome")
            if self._simple_step_idx >= len(WINDOWS_STAGES):
                self._simple_step_idx = WINDOWS_STAGES.index("settings")
        self._render()

    def on_key(self, event: events.Key) -> None:
        if not (not self._show_details and WINDOWS_STAGES[self._simple_step_idx] == "compatibility" and self._compat_prompt_active):
            return
        if event.key.lower() in {"y"}:
            self._handle_compat_prompt_response(True)
            event.stop()
            return
        if event.key.lower() in {"n"}:
            self._handle_compat_prompt_response(False)
            event.stop()

    def action_next_stage(self) -> None: self._set_stage((self._stage_idx + 1) % len(WINDOWS_STAGES))
    def action_prev_stage(self) -> None: self._set_stage((self._stage_idx - 1) % len(WINDOWS_STAGES))
    def action_goto_1(self) -> None: self._set_stage(0)
    def action_goto_2(self) -> None: self._set_stage(1)
    def action_goto_3(self) -> None: self._set_stage(2)
    def action_goto_4(self) -> None: self._set_stage(3)
    def action_goto_5(self) -> None: self._set_stage(4)
    def action_goto_6(self) -> None: self._set_stage(5)
    def action_goto_7(self) -> None: self._set_stage(6)
    def action_goto_8(self) -> None: self._set_stage(7)
    def action_goto_9(self) -> None: self._set_stage(8)
    def action_goto_10(self) -> None: self._set_stage(9)
    def action_launch_legacy(self) -> None: self.exit(EXIT_LAUNCH_LEGACY)
    def action_quit_flow(self) -> None: self.exit(EXIT_QUIT)


def run_windows_preflight_tui(
    *,
    launch_legacy_on_continue: bool = False,
    apply_changes: bool = False,
    target_free_gib: int = 120,
    backup_destination: str | None = None,
    backup_fallback_destination: str | None = None,
    ventoy_disk_number: int | None = None,
    source_iso_path: str | None = None,
    yolo_mode: bool = False,
    yolo_approved_failures: tuple[str, ...] = (),
) -> int:
    app = WindowsPrepApp(
        WindowsTuiConfig(
            launch_legacy_on_continue=launch_legacy_on_continue,
            apply_changes=apply_changes,
            target_free_gib=target_free_gib,
            backup_destination=backup_destination,
            backup_fallback_destination=backup_fallback_destination,
            ventoy_disk_number=ventoy_disk_number,
            source_iso_path=source_iso_path,
            yolo_mode=yolo_mode,
            yolo_approved_failures=yolo_approved_failures,
        )
    )
    result = app.run()
    return result if isinstance(result, int) else EXIT_QUIT
