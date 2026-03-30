"""Interactive Textual runtime for the Linux live installer flow."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
import os
from pathlib import Path
import shutil
import subprocess

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual import events
from textual.widgets import Header, Static

from ..platforms.linux_live.boot_policy import (
    BootPolicyError,
    BootPolicySummary,
    LIMINE_FALLBACK_PATH,
    LIMINE_PRIMARY_PATH,
    WINDOWS_EFI_PATH,
    resolve_efi_mount_path,
    summarize_boot_policy,
)
from ..platforms.linux_live.discovery import (
    HandoffDiscoveryError,
    HandoffDiscoveryResult,
    build_validation_context_from_runtime,
    discover_and_validate_handoff_plan,
    discover_handoff_sources,
)
from ..platforms.linux_live.install import LiveInstallError, LiveInstallExecutionResult, execute_install_plan
from ..platforms.linux_live.network import NetworkResolutionResult, resolve_network_connectivity


LIVE_BOOTSTRAP_SCREEN_CONTRACT: tuple[str, ...] = (
    "welcome",
    "network",
    "partitioning",
    "destructive_confirm",
    "install",
    "finalize",
    "omarchy",
    "errors",
)

LIVE_STAGE_LABELS: dict[str, str] = {
    "welcome": "Welcome",
    "network": "Network",
    "partitioning": "Partition",
    "destructive_confirm": "Confirm",
    "install": "Install",
    "finalize": "Finalize",
    "omarchy": "Omarchy",
    "errors": "Issues",
}

REQUIRED_LIVE_BINARIES: tuple[str, ...] = (
    "python3",
    "nmcli",
    "archinstall",
    "sgdisk",
)

INSTALL_FIELD_ORDER: tuple[str, ...] = (
    "hostname",
    "username",
    "timezone",
    "locale",
    "keyboard_layout",
    "user_password",
    "user_password_confirm",
    "encryption_passphrase",
    "encryption_passphrase_confirm",
)

INSTALL_FIELD_LABELS: dict[str, str] = {
    "hostname": "Hostname",
    "username": "Username",
    "timezone": "Timezone",
    "locale": "Locale",
    "keyboard_layout": "Keyboard Layout",
    "user_password": "User Password",
    "user_password_confirm": "Confirm User Password",
    "encryption_passphrase": "Disk Encryption Password",
    "encryption_passphrase_confirm": "Confirm Disk Encryption Password",
}

HIDDEN_INSTALL_FIELDS = {
    "user_password",
    "user_password_confirm",
    "encryption_passphrase",
    "encryption_passphrase_confirm",
}


@dataclass(frozen=True, slots=True)
class LiveRuntimeSnapshot:
    generated_at_utc: str
    dependencies_ok: bool
    missing_dependencies: tuple[str, ...]
    handoff_mode: str
    handoff_sources: tuple[str, ...]
    handoff_result: HandoffDiscoveryResult | None
    handoff_note: str
    network_result: NetworkResolutionResult | None
    network_error: str
    install_result: LiveInstallExecutionResult | None
    install_error: str
    boot_policy_result: BootPolicySummary | None
    boot_policy_error: str
    partition_warnings: tuple[str, ...]


def bootstrap_screen_ids() -> list[str]:
    """Return the ordered Arch live bootstrap screen identifiers."""
    if len(set(LIVE_BOOTSTRAP_SCREEN_CONTRACT)) != len(LIVE_BOOTSTRAP_SCREEN_CONTRACT):
        raise ValueError("Bootstrap screen contract contains duplicate identifiers.")
    return list(LIVE_BOOTSTRAP_SCREEN_CONTRACT)


def windows_prep_screen_ids() -> list[str]:
    """Return the ordered Windows prep screen identifiers."""
    from ..platforms.windows.app import WINDOWS_STAGES

    if len(set(WINDOWS_STAGES)) != len(WINDOWS_STAGES):
        raise ValueError("Windows prep screen contract contains duplicate identifiers.")
    return list(WINDOWS_STAGES)


def validate_live_dependencies() -> tuple[bool, tuple[str, ...]]:
    """Validate required runtime binaries for live installer entry."""
    missing = tuple(binary for binary in REQUIRED_LIVE_BINARIES if shutil.which(binary) is None)
    return (len(missing) == 0, missing)


def _now_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _partition_warnings_for_standalone(handoff_note: str) -> tuple[str, ...]:
    warnings = [
        "NO validated handoff config found. Running in standalone/manual mode.",
        "NO CONFIG MODE will use AUTOMATIC WHOLE-DISK install behavior.",
        "THIS CAN DELETE YOUR EXISTING OS AND ALL DATA ON THE TARGET DISK.",
        "Wrong target disk choice can permanently destroy data.",
        "Confirm backup and recovery path before continuing.",
    ]
    if handoff_note.strip():
        warnings.append(f"Discovery note: {handoff_note.strip()}")
    return tuple(warnings)


def _default_hostname() -> str:
    for path in (Path("/sys/class/dmi/id/product_name"), Path("/sys/class/dmi/id/board_name")):
        try:
            value = path.read_text(encoding="utf-8", errors="ignore").strip().lower()
        except OSError:
            value = ""
        value = "-".join(part for part in "".join(ch if ch.isalnum() else "-" for ch in value).split("-") if part)
        if value:
            return f"omarchy-{value[:18]}"
    try:
        machine_id = Path("/etc/machine-id").read_text(encoding="utf-8", errors="ignore").strip()[:4]
    except OSError:
        machine_id = "host"
    return f"omarchy-{machine_id or 'host'}"


def _default_username() -> str:
    for key in ("SUDO_USER", "USER"):
        value = str(os.environ.get(key, "")).strip().lower()
        if value and value != "root":
            cleaned = "".join(ch for ch in value if ch.isalnum() or ch in {"_", "-"})
            if cleaned:
                return cleaned
    return "omarchy"


def _default_timezone() -> str:
    try:
        output = subprocess.run(
            ["timedatectl", "show", "-p", "Timezone", "--value"],
            capture_output=True,
            text=True,
            check=False,
        )
        value = output.stdout.strip()
        if value and value != "n/a":
            return value
    except OSError:
        pass
    try:
        value = Path("/etc/timezone").read_text(encoding="utf-8", errors="ignore").strip()
    except OSError:
        value = ""
    return value or "UTC"


def collect_live_runtime_snapshot(
    *,
    live_runtime_version: str = "0.1.0-dev",
    max_plan_age_hours: int | None = 72,
    efi_mount: str = "/boot/efi",
) -> LiveRuntimeSnapshot:
    """Collect live runtime state for guided flow rendering."""
    dependencies_ok, missing_dependencies = validate_live_dependencies()

    handoff_sources = tuple(discover_handoff_sources())
    handoff_result: HandoffDiscoveryResult | None = None
    handoff_note = ""
    handoff_mode = "standalone"
    if handoff_sources:
        context = build_validation_context_from_runtime(
            live_runtime_version=live_runtime_version,
            max_plan_age_hours=max_plan_age_hours,
        )
        try:
            handoff_result = discover_and_validate_handoff_plan(
                context,
                search_roots=handoff_sources,
            )
            handoff_mode = "ventoy-plan"
            handoff_note = "Validated handoff plan found."
        except (HandoffDiscoveryError, ValueError) as exc:
            handoff_note = str(exc)
    else:
        handoff_note = "No handoff source containing omarchy/plan.json was discovered."

    network_result: NetworkResolutionResult | None = None
    network_error = ""
    try:
        network_result = resolve_network_connectivity(
            retry_attempts=0,
            allow_nmtui=False,
        )
        if network_result.requires_abort or not network_result.connected:
            network_error = network_result.hint or "Network fallback strategy did not reach a connected state."
    except Exception as exc:  # pragma: no cover
        network_error = str(exc)

    install_result: LiveInstallExecutionResult | None = None
    install_error = ""
    try:
        install_result = execute_install_plan(
            plan_payload=handoff_result.plan if handoff_result is not None else None,
            dry_run=True,
            cleanup_after_success=True,
        )
    except (LiveInstallError, OSError, ValueError) as exc:
        install_error = str(exc)

    boot_policy_result: BootPolicySummary | None = None
    boot_policy_error = ""
    try:
        efi_resolution = resolve_efi_mount_path(efi_mount)
        boot_policy_result = summarize_boot_policy(
            "limine",
            efi_mount=efi_resolution.mount_path,
        )
        if efi_resolution.notes:
            boot_policy_error = " | ".join(efi_resolution.notes)
        if not boot_policy_result.can_finalize:
            blocker_text = "; ".join(boot_policy_result.blockers)
            boot_policy_error = f"{boot_policy_error} | {blocker_text}".strip(" |")
    except (BootPolicyError, OSError, ValueError) as exc:
        boot_policy_error = str(exc)

    partition_warnings: tuple[str, ...] = tuple()
    if handoff_mode == "standalone":
        partition_warnings = _partition_warnings_for_standalone(handoff_note)

    return LiveRuntimeSnapshot(
        generated_at_utc=_now_utc(),
        dependencies_ok=dependencies_ok,
        missing_dependencies=missing_dependencies,
        handoff_mode=handoff_mode,
        handoff_sources=handoff_sources,
        handoff_result=handoff_result,
        handoff_note=handoff_note,
        network_result=network_result,
        network_error=network_error,
        install_result=install_result,
        install_error=install_error,
        boot_policy_result=boot_policy_result,
        boot_policy_error=boot_policy_error,
        partition_warnings=partition_warnings,
    )


def _shorten(value: str, *, max_len: int = 110) -> str:
    text = value.strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def _network_ready(snapshot: LiveRuntimeSnapshot) -> bool:
    result = snapshot.network_result
    return bool(result and result.connected and not result.requires_abort and not snapshot.network_error)


def _partition_ready(snapshot: LiveRuntimeSnapshot) -> bool:
    return bool(snapshot.handoff_mode == "ventoy-plan" and snapshot.handoff_result is not None)


def _status_marker(stage_id: str, snapshot: LiveRuntimeSnapshot) -> str:
    if stage_id == "welcome":
        return "ok" if snapshot.dependencies_ok else "blocked"
    if stage_id == "network":
        return "ok" if _network_ready(snapshot) else "blocked"
    if stage_id == "partitioning":
        return "ok" if _partition_ready(snapshot) else "warn"
    if stage_id == "destructive_confirm":
        return "warn" if snapshot.handoff_mode == "standalone" else "ok"
    if stage_id == "install":
        return "ok" if snapshot.install_result and not snapshot.install_error else "blocked"
    if stage_id == "finalize":
        return "ok" if snapshot.boot_policy_result and snapshot.boot_policy_result.can_finalize else "warn"
    if stage_id == "omarchy":
        return "warn" if snapshot.boot_policy_error else "ok"
    error_present = any(
        (
            not snapshot.dependencies_ok,
            bool(snapshot.network_error),
            bool(snapshot.install_error),
            bool(snapshot.boot_policy_error),
        )
    )
    return "warn" if error_present else "ok"


def _status_tag(marker: str) -> str:
    if marker == "ok":
        return "OK"
    if marker == "blocked":
        return "BLOCKED"
    return "WARN"


def _next_stage(stage_id: str, snapshot: LiveRuntimeSnapshot) -> str:
    if stage_id == "welcome":
        return "network"
    if stage_id == "network":
        return "partitioning"
    if stage_id == "partitioning":
        return "destructive_confirm" if snapshot.handoff_mode == "standalone" else "install"
    if stage_id == "destructive_confirm":
        return "install"
    if stage_id == "install":
        return "finalize"
    if stage_id == "finalize":
        return "omarchy"
    if stage_id == "omarchy":
        return "errors"
    if stage_id == "errors":
        return "welcome"
    return "welcome"


def format_stage_content(
    stage_id: str,
    snapshot: LiveRuntimeSnapshot,
    *,
    partition_confirm_armed: bool = False,
    partition_confirm_text: str = "",
    partition_confirmed: bool = False,
    destructive_confirm_armed: bool = False,
    destructive_confirmed: bool = False,
    install_input_active: bool = False,
    install_input_field: str = "",
    install_input_buffer: str = "",
    install_inputs: dict[str, str] | None = None,
) -> str:
    """Render stage-specific body content from collected runtime state."""
    if stage_id == "welcome":
        mode_line = "Plan mode (validated handoff)" if snapshot.handoff_mode == "ventoy-plan" else "No-config mode (automatic whole-disk install path)"
        partition_line = "Ready from handoff plan" if _partition_ready(snapshot) else "Automatic whole-disk mode with destructive warnings"
        return "\n".join(
            [
                "Guided Setup",
                f"Generated: {snapshot.generated_at_utc}",
                f"Flow Mode: {mode_line}",
                "",
                "1. Network checks",
                "2. Partition plan review",
                "3. Final destructive confirmation",
                "4. Install orchestration",
                "5. Finalize boot policy",
                "6. Omarchy handoff",
                "",
                f"Network: {'Ready' if _network_ready(snapshot) else 'Needs attention'}",
                f"Partitioning: {partition_line}",
                f"Install Probe: {'Ready' if snapshot.install_result and not snapshot.install_error else 'Needs attention'}",
                "",
                "Press [Enter] to move to the next guided step.",
            ]
        )

    if stage_id == "network":
        if snapshot.network_result is None:
            return "\n".join(
                [
                    "Network",
                    "State: BLOCKED",
                    f"Error: {snapshot.network_error or 'network probe did not execute'}",
                ]
            )
        steps = "\n".join(
            f"- {step.step}: {step.status} ({_shorten(step.detail)})"
            for step in snapshot.network_result.steps[:8]
        ) or "- none"
        return "\n".join(
            [
                "Network",
                f"Connected: {snapshot.network_result.connected}",
                f"Mode: {snapshot.network_result.connection_mode}",
                f"Active Connection: {snapshot.network_result.active_connection_name or 'N/A'}",
                f"Requires Abort: {snapshot.network_result.requires_abort}",
                f"Hint: {snapshot.network_result.hint or 'none'}",
                f"Error: {snapshot.network_error or 'none'}",
                "",
                "Recent Checks:",
                steps,
            ]
        )

    if stage_id == "partitioning":
        if snapshot.handoff_mode == "ventoy-plan" and snapshot.handoff_result:
            plan = snapshot.handoff_result
            return "\n".join(
                [
                    "Partition Plan",
                    "Validated handoff plan detected.",
                    f"Plan Path: {plan.plan_path}",
                    f"Source Root: {plan.source_root}",
                    "",
                    "Partitioning may proceed using validated metadata from Windows prep.",
                    'No manual "Proceed" confirmation is required in config mode.',
                ]
            )
        warning_lines = "\n".join(f"WARNING {idx}. {item}" for idx, item in enumerate(snapshot.partition_warnings, start=1))
        if partition_confirmed:
            confirm_lines = 'Risk confirmation accepted: "Proceed".'
        elif partition_confirm_armed:
            confirm_lines = (
                "WARNING YOU COULD DELETE YOUR EXISTING OS PROCEED WITH CAUTION\n"
                'Type "Proceed" then press [Enter] to continue.\n'
                f"Input: {partition_confirm_text}"
            )
        else:
            confirm_lines = (
                "WARNING YOU COULD DELETE YOUR EXISTING OS PROCEED WITH CAUTION\n"
                "Press [Enter] again to start confirmation."
            )
        return "\n".join(
            [
                "Partition Plan",
                "HIGH-RISK NO-CONFIG MODE",
                "",
                warning_lines or "WARNING. No validated partition plan was found.",
                "",
                "If you continue in NO CONFIG mode, installer path is automatic whole-disk target.",
                "",
                confirm_lines,
            ]
        )

    if stage_id == "install":
        install_inputs = install_inputs or {}
        if install_input_active:
            label = INSTALL_FIELD_LABELS.get(install_input_field, install_input_field)
            current_value = install_input_buffer
            if install_input_field in HIDDEN_INSTALL_FIELDS:
                current_value = "*" * len(install_input_buffer)
            return "\n".join(
                [
                    "Install Details",
                    f"Enter {label}",
                    "",
                    f"Value: {current_value}",
                    "",
                    "Type the value, then press [Enter].",
                ]
            )
        summary_lines = [
            f"Hostname: {install_inputs.get('hostname', '') or 'not set'}",
            f"Username: {install_inputs.get('username', '') or 'not set'}",
            f"Timezone: {install_inputs.get('timezone', '') or 'not set'}",
            f"Locale: {install_inputs.get('locale', '') or 'not set'}",
            f"Keyboard Layout: {install_inputs.get('keyboard_layout', '') or 'not set'}",
            f"User Password: {'set' if install_inputs.get('user_password') else 'not set'}",
            f"Disk Encryption Password: {'set' if install_inputs.get('encryption_passphrase') else 'not set'}",
        ]
        if snapshot.install_result is None:
            return "\n".join(
                [
                    "Install",
                    "Ready to execute full install.",
                    *summary_lines,
                    "",
                    f"Last Error: {snapshot.install_error or 'none'}",
                    "",
                    "Press [Enter] to enter or review install details.",
                ]
            )
        command_count = len(snapshot.install_result.commands)
        command_line = "No shell commands queued yet." if command_count == 0 else f"{command_count} command(s) prepared."
        mode_line = (
            "Automatic whole-disk path armed for standalone install."
            if snapshot.handoff_mode == "standalone"
            else "Validated handoff plan path armed."
        )
        return "\n".join(
            [
                "Install",
                "Automatic install action: PASS" if not snapshot.install_result.dry_run else "Install plan staged",
                mode_line,
                f"Status: {snapshot.install_result.status}",
                f"Target Disk: {snapshot.install_result.target_disk_path or 'unknown'}",
                f"EFI Partition: {snapshot.install_result.efi_partition_path or 'unknown'}",
                f"Linux Partition: {snapshot.install_result.target_partition_path or 'unknown'}",
                f"Command plan: {command_line}",
                "",
                *summary_lines,
                "",
                "Press [Enter] to execute install." if snapshot.install_result.dry_run else "Press [Enter] to continue to finalize checks.",
            ]
        )

    if stage_id == "destructive_confirm":
        if snapshot.handoff_mode == "ventoy-plan":
            return "\n".join(
                [
                    "Final Confirmation",
                    "Validated handoff config mode.",
                    "This install will use the Windows-prepared plan metadata.",
                    "",
                    "Press [Enter] to continue to install.",
                ]
            )
        if destructive_confirmed:
            confirm_line = "Final destructive confirmation accepted. Continuing to Omarchy install."
        elif destructive_confirm_armed:
            confirm_line = "AUTOMATIC WHOLE-DISK INSTALL IS ARMED. Press [Y] to continue or [Q] to quit."
        else:
            confirm_line = "Press [Enter] to arm the final destructive confirmation."
        return "\n".join(
            [
                "Final Confirmation",
                "NO-CONFIG MODE WILL APPLY AUTOMATIC WHOLE-DISK PARTITIONING.",
                "Windows partitions, data, and recovery layout on the selected target can be overwritten.",
                "This is the last stop before Omarchy install proceeds.",
                "",
                confirm_line,
            ]
        )

    if stage_id == "finalize":
        if snapshot.boot_policy_result is None:
            return "\n".join(
                [
                    "Finalize",
                    "Boot policy / EFI check: BLOCKED",
                    f"Error: {snapshot.boot_policy_error or 'boot policy probe did not execute'}",
                ]
            )
        blockers = "\n".join(f"- {item}" for item in snapshot.boot_policy_result.blockers) or "- none"
        warnings = "\n".join(f"- {item}" for item in snapshot.boot_policy_result.warnings) or "- none"
        efi_root = Path(snapshot.boot_policy_result.efi_mount)
        windows_target = efi_root / WINDOWS_EFI_PATH
        limine_primary = efi_root / LIMINE_PRIMARY_PATH
        limine_fallback = efi_root / LIMINE_FALLBACK_PATH
        return "\n".join(
            [
                "Finalize",
                "Boot policy / EFI check: ATTEMPTED",
                f"Can Finalize: {snapshot.boot_policy_result.can_finalize}",
                f"EFI Mount: {snapshot.boot_policy_result.efi_mount}",
                f"Windows EFI target: {windows_target}",
                f"Limine EFI targets: {limine_primary} | {limine_fallback}",
                "",
                "Blockers:",
                blockers,
                "Warnings:",
                warnings,
            ]
        )

    if stage_id == "omarchy":
        blockers = tuple(snapshot.boot_policy_result.blockers) if snapshot.boot_policy_result else tuple()
        blocker_line = "none" if not blockers else "; ".join(blockers)
        return "\n".join(
            [
                "Omarchy",
                "Installer flow reached Omarchy handoff stage.",
                "Partitioning and install orchestration have already been accepted.",
                "",
                f"Finalize blockers still reported: {blocker_line}",
                "If Hyper-V still needs manual EFI cleanup, that can be handled after this point.",
                "",
                "Press [Enter] to review issues or restart the flow.",
            ]
        )

    return "\n".join(
        [
            "Errors and Warnings",
            f"Dependencies: {'none' if snapshot.dependencies_ok else ', '.join(snapshot.missing_dependencies)}",
            f"Handoff: {snapshot.handoff_note or 'none'}",
            f"Network: {snapshot.network_error or 'none'}",
            f"Install: {snapshot.install_error or 'none'}",
            f"Finalize: {snapshot.boot_policy_error or 'none'}",
            "",
            "Press [Enter] to restart guided flow from Welcome.",
        ]
    )


class LiveInstallerApp(App[int]):
    """Interactive guided TUI for Linux live installer readiness."""

    CSS = """
    Screen {
      layout: vertical;
    }
    #body {
      padding: 1 2;
      height: 1fr;
    }
    #title {
      text-style: bold;
      margin-bottom: 1;
    }
    #subtitle {
      margin-bottom: 1;
      color: $text-muted;
    }
    #stages {
      margin-bottom: 1;
      color: $text;
      text-style: bold;
      background: $accent 20%;
      padding: 0 1;
    }
    #content {
      height: 1fr;
      border: round $accent;
      padding: 1 1;
    }
    #status {
      margin-top: 1;
      color: $text-muted;
    }
    #hints {
      margin-top: 1;
      color: $text-muted;
    }
    """

    BINDINGS = [
        Binding("enter", "next_guided_step", "Next Step"),
        Binding("d", "toggle_details", "Details"),
        Binding("r", "refresh_runtime", "Refresh"),
        Binding("q", "quit_flow", "Quit"),
    ]

    def __init__(
        self,
        *,
        live_runtime_version: str = "0.1.0-dev",
        max_plan_age_hours: int | None = 72,
        efi_mount: str = "/boot/efi",
    ) -> None:
        super().__init__()
        self._stage_ids = bootstrap_screen_ids()
        self._active_stage_index = 0
        self._details_mode = False
        self._status_message = "Loading runtime state..."
        self._partition_confirm_armed = False
        self._partition_confirm_text = ""
        self._partition_confirmed = False
        self._destructive_confirm_armed = False
        self._destructive_confirmed = False
        self._install_result_override: LiveInstallExecutionResult | None = None
        self._install_error_override = ""
        self._install_input_active = False
        self._install_input_index = 0
        self._install_input_buffer = ""
        self._install_inputs: dict[str, str] = {}
        self._live_runtime_version = live_runtime_version
        self._max_plan_age_hours = max_plan_age_hours
        self._efi_mount = efi_mount
        self._snapshot = LiveRuntimeSnapshot(
            generated_at_utc=_now_utc(),
            dependencies_ok=False,
            missing_dependencies=REQUIRED_LIVE_BINARIES,
            handoff_mode="standalone",
            handoff_sources=tuple(),
            handoff_result=None,
            handoff_note="Not collected yet.",
            network_result=None,
            network_error="Not collected yet.",
            install_result=None,
            install_error="Not collected yet.",
            boot_policy_result=None,
            boot_policy_error="Not collected yet.",
            partition_warnings=("Not collected yet.",),
        )

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="body"):
            yield Static("Omarchy Arch Live Installer (Python TUI)", id="title", markup=False)
            yield Static(
                "Simple guided setup. Press [Enter] for the next step. Press [D] for advanced details.",
                id="subtitle",
                markup=False,
            )
            yield Static("", id="stages", markup=False)
            yield Static("", id="content", markup=False)
            yield Static("", id="status", markup=False)
            yield Static("", id="hints", markup=False)

    def on_mount(self) -> None:
        self.action_refresh_runtime()

    def _active_stage_id(self) -> str:
        return self._stage_ids[self._active_stage_index]

    def _partition_confirmation_active(self) -> bool:
        return bool(
            self._partition_confirm_armed
            and self._active_stage_id() == "partitioning"
            and self._snapshot.handoff_mode == "standalone"
        )

    def _set_status(self, message: str) -> None:
        self._status_message = message.strip() or "Ready."

    def _focused_step_line(self) -> str:
        stage_id = self._active_stage_id()
        label = LIVE_STAGE_LABELS.get(stage_id, stage_id.title())
        return f">> CURRENT STEP: {self._active_stage_index + 1}/{len(self._stage_ids)} {label} <<"

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        del parameters
        if self._install_input_capture_active():
            return action == "next_guided_step"
        if self._partition_confirmation_active():
            return action == "next_guided_step"
        return True

    def _render(self) -> None:
        stage_line_parts = []
        for idx, stage_id in enumerate(self._stage_ids, start=1):
            marker = _status_marker(stage_id, self._snapshot)
            label = LIVE_STAGE_LABELS.get(stage_id, stage_id.title())
            active = "*" if idx - 1 == self._active_stage_index else " "
            stage_line_parts.append(f"{active}{idx}:{label}[{_status_tag(marker)}]")

        stages_widget = self.query_one("#stages", Static)
        if self._details_mode:
            stages_widget.update(self._focused_step_line() + "\n" + "  ".join(stage_line_parts))
        else:
            stages_widget.update(self._focused_step_line())

        self.query_one("#content", Static).update(
            format_stage_content(
                self._active_stage_id(),
                self._snapshot,
                partition_confirm_armed=self._partition_confirm_armed,
                partition_confirm_text=self._partition_confirm_text,
                partition_confirmed=self._partition_confirmed,
                destructive_confirm_armed=self._destructive_confirm_armed,
                destructive_confirmed=self._destructive_confirmed,
                install_input_active=self._install_input_active,
                install_input_field=INSTALL_FIELD_ORDER[self._install_input_index] if self._install_input_active else "",
                install_input_buffer=self._install_input_buffer,
                install_inputs=self._install_inputs,
            )
        )
        self.query_one("#status", Static).update(f"Status: {self._status_message}")

        hint_widget = self.query_one("#hints", Static)
        if self._details_mode:
            hint_widget.update("Keys: [Enter] next  [R] refresh  [D] details  [Q] quit")
        else:
            hint_widget.update("Keys: [Enter] next  [R] refresh  [D] details  [Q] quit")

    def _set_stage(self, stage_id: str) -> None:
        self._active_stage_index = self._stage_ids.index(stage_id)
        self._render()

    def _destructive_confirmation_active(self) -> bool:
        return bool(
            self._active_stage_id() == "destructive_confirm"
            and self._snapshot.handoff_mode == "standalone"
            and self._destructive_confirm_armed
            and not self._destructive_confirmed
        )

    def _install_input_capture_active(self) -> bool:
        return bool(self._active_stage_id() == "install" and self._install_input_active)

    def _snapshot_with_install_override(self, snapshot: LiveRuntimeSnapshot) -> LiveRuntimeSnapshot:
        if self._install_result_override is None and not self._install_error_override:
            return snapshot
        return replace(
            snapshot,
            install_result=self._install_result_override,
            install_error=self._install_error_override,
        )

    def _seed_install_inputs(self) -> None:
        plan = self._snapshot.handoff_result.plan if self._snapshot.handoff_result else None
        user_choices = plan.user_choices if plan is not None else {}
        seeded = {
            "hostname": str(user_choices.get("hostname", "")).strip() or _default_hostname(),
            "username": str(user_choices.get("username", "")).strip() or _default_username(),
            "timezone": str(user_choices.get("timezone", "")).strip() or _default_timezone(),
            "locale": str(user_choices.get("locale", "")).strip() or "en_US",
            "keyboard_layout": str(user_choices.get("kb_layout", "")).strip() or "us",
            "user_password": "",
            "user_password_confirm": "",
            "encryption_passphrase": "",
            "encryption_passphrase_confirm": "",
        }
        seeded.update({key: value for key, value in self._install_inputs.items() if value})
        self._install_inputs = seeded

    def _start_install_input_flow(self) -> None:
        self._seed_install_inputs()
        self._install_input_active = True
        self._install_input_index = 0
        field = INSTALL_FIELD_ORDER[self._install_input_index]
        self._install_input_buffer = self._install_inputs.get(field, "")
        self._set_status(f"Enter {INSTALL_FIELD_LABELS[field]}.")
        self._render()

    def _commit_install_input(self) -> bool:
        field = INSTALL_FIELD_ORDER[self._install_input_index]
        value = self._install_input_buffer
        if field in {"hostname", "username", "timezone", "locale", "keyboard_layout"} and not value.strip():
            self._set_status(f"{INSTALL_FIELD_LABELS[field]} cannot be empty.")
            self._render()
            return False
        if field.endswith("_confirm"):
            primary = field.removesuffix("_confirm")
            if value != self._install_inputs.get(primary, ""):
                self._set_status(f"{INSTALL_FIELD_LABELS[field]} does not match.")
                self._render()
                return False
        self._install_inputs[field] = value.strip() if field not in HIDDEN_INSTALL_FIELDS else value
        self._install_input_index += 1
        if self._install_input_index >= len(INSTALL_FIELD_ORDER):
            self._install_input_active = False
            self._install_input_index = 0
            self._install_input_buffer = ""
            self._set_status("Install details captured. Press [Enter] to execute install.")
            self._render()
            return True
        next_field = INSTALL_FIELD_ORDER[self._install_input_index]
        self._install_input_buffer = self._install_inputs.get(next_field, "")
        self._set_status(f"Enter {INSTALL_FIELD_LABELS[next_field]}.")
        self._render()
        return True

    def _execute_live_install(self) -> None:
        try:
            self._seed_install_inputs()
            plan_payload = self._snapshot.handoff_result.plan if self._snapshot.handoff_result else None
            result = execute_install_plan(
                plan_payload=plan_payload,
                dry_run=False,
                cleanup_after_success=False,
                hostname=self._install_inputs.get("hostname", ""),
                username=self._install_inputs.get("username", ""),
                timezone=self._install_inputs.get("timezone", ""),
                locale=self._install_inputs.get("locale", "en_US"),
                keyboard_layout=self._install_inputs.get("keyboard_layout", "us"),
                user_password=self._install_inputs.get("user_password", ""),
                encryption_passphrase=self._install_inputs.get("encryption_passphrase", ""),
            )
            self._install_result_override = result
            self._install_error_override = ""
            self._snapshot = replace(
                self._snapshot,
                install_result=result,
                install_error="",
            )
            self._set_status("Live install completed successfully.")
        except (LiveInstallError, OSError, ValueError) as exc:
            self._install_result_override = None
            self._install_error_override = str(exc)
            self._snapshot = replace(
                self._snapshot,
                install_result=None,
                install_error=str(exc),
            )
            self._set_status(f"Install failed: {exc}")
        self._render()

    def action_next_guided_step(self) -> None:
        current = self._active_stage_id()
        if current == "partitioning" and self._snapshot.handoff_mode == "standalone" and not self._partition_confirmed:
            if not self._partition_confirm_armed:
                self._partition_confirm_armed = True
                self._partition_confirm_text = ""
                self._set_status("WARNING YOU COULD DELETE YOUR EXISTING OS PROCEED WITH CAUTION")
                self._render()
                return
            if self._partition_confirm_text == "Proceed":
                self._partition_confirmed = True
                self._partition_confirm_armed = False
                self._partition_confirm_text = ""
                self._set_status('Risk confirmation accepted. Continuing.')
            else:
                self._set_status('Type exactly "Proceed" then press Enter.')
                self._render()
                return
        if current == "partitioning" and self._snapshot.handoff_mode == "ventoy-plan":
            self._partition_confirm_armed = False
            self._partition_confirm_text = ""
            self._partition_confirmed = True
        if current == "destructive_confirm" and self._snapshot.handoff_mode == "standalone" and not self._destructive_confirmed:
            if not self._destructive_confirm_armed:
                self._destructive_confirm_armed = True
                self._set_status("Final destructive confirmation armed. Press Y to continue or Q to quit.")
                self._render()
                return
            self._set_status("Press Y to continue or Q to quit.")
            self._render()
            return
        if current == "install":
            if self._install_input_active:
                self._commit_install_input()
                return
            missing_core = [
                key
                for key in ("hostname", "username", "timezone", "locale", "keyboard_layout", "user_password", "encryption_passphrase")
                if not self._install_inputs.get(key, "")
            ]
            if missing_core or self._install_inputs.get("user_password") != self._install_inputs.get("user_password_confirm") or self._install_inputs.get("encryption_passphrase") != self._install_inputs.get("encryption_passphrase_confirm"):
                self._start_install_input_flow()
                return
            if self._snapshot.install_result is None or self._snapshot.install_result.dry_run:
                self._set_status("Running full live install now.")
                self._render()
                self._execute_live_install()
                return
        target = _next_stage(current, self._snapshot)
        if target == "install" and current == "destructive_confirm" and self._snapshot.handoff_mode == "standalone":
            self._active_stage_index = self._stage_ids.index(target)
            self._seed_install_inputs()
            self._set_status("Moved to install details.")
            self._render()
            return
        if target == "install" and current == "partitioning" and self._snapshot.handoff_mode == "ventoy-plan":
            self._seed_install_inputs()
        if target in {"install", "finalize", "omarchy", "errors"}:
            self._snapshot = collect_live_runtime_snapshot(
                live_runtime_version=self._live_runtime_version,
                max_plan_age_hours=self._max_plan_age_hours,
                efi_mount=self._efi_mount,
            )
            self._snapshot = self._snapshot_with_install_override(self._snapshot)
        self._active_stage_index = self._stage_ids.index(target)
        if target == "destructive_confirm":
            self._set_status("Moved to final destructive confirmation.")
        elif target == "install":
            self._set_status("Moved to install details.")
        elif target == "finalize":
            self._set_status("Moved to finalize. EFI/bootloader checks attempted.")
        elif target == "omarchy":
            self._set_status("Moved to Omarchy handoff stage.")
        elif target == "welcome" and current == "errors":
            self._set_status("Guided flow restarted from welcome.")
        else:
            self._set_status(f"Moved to {target}.")
        self._render()

    def action_next_stage(self) -> None:
        if self._partition_confirmation_active():
            self._set_status('Type exactly "Proceed" then press Enter.')
            self._render()
            return
        if self._destructive_confirmation_active():
            self._set_status("Press Y to continue or Q to quit.")
            self._render()
            return
        self._active_stage_index = (self._active_stage_index + 1) % len(self._stage_ids)
        self._set_status(f"Moved to {self._active_stage_id()}.")
        self._render()

    def action_previous_stage(self) -> None:
        if self._partition_confirmation_active():
            self._set_status('Type exactly "Proceed" then press Enter.')
            self._render()
            return
        if self._destructive_confirmation_active():
            self._set_status("Press Y to continue or Q to quit.")
            self._render()
            return
        self._active_stage_index = (self._active_stage_index - 1) % len(self._stage_ids)
        self._set_status(f"Moved to {self._active_stage_id()}.")
        self._render()

    def action_goto_welcome(self) -> None:
        if self._partition_confirmation_active():
            self._set_status('Type exactly "Proceed" then press Enter.')
            self._render()
            return
        if self._destructive_confirmation_active():
            self._set_status("Press Y to continue or Q to quit.")
            self._render()
            return
        self._set_stage("welcome")

    def action_goto_network(self) -> None:
        if self._partition_confirmation_active():
            self._set_status('Type exactly "Proceed" then press Enter.')
            self._render()
            return
        if self._destructive_confirmation_active():
            self._set_status("Press Y to continue or Q to quit.")
            self._render()
            return
        self._set_stage("network")

    def action_goto_partitioning(self) -> None:
        if self._destructive_confirmation_active():
            self._set_status("Press Y to continue or Q to quit.")
            self._render()
            return
        self._set_stage("partitioning")

    def action_goto_install(self) -> None:
        if self._partition_confirmation_active():
            self._set_status('Type exactly "Proceed" then press Enter.')
            self._render()
            return
        if self._destructive_confirmation_active():
            self._set_status("Press Y to continue or Q to quit.")
            self._render()
            return
        self._set_stage("install")

    def action_goto_finalize(self) -> None:
        if self._partition_confirmation_active():
            self._set_status('Type exactly "Proceed" then press Enter.')
            self._render()
            return
        if self._destructive_confirmation_active():
            self._set_status("Press Y to continue or Q to quit.")
            self._render()
            return
        self._set_stage("finalize")

    def action_goto_errors(self) -> None:
        if self._partition_confirmation_active():
            self._set_status('Type exactly "Proceed" then press Enter.')
            self._render()
            return
        if self._destructive_confirmation_active():
            self._set_status("Press Y to continue or Q to quit.")
            self._render()
            return
        self._set_stage("errors")

    def action_toggle_details(self) -> None:
        if self._partition_confirmation_active():
            self._set_status('Type exactly "Proceed" then press Enter.')
            self._render()
            return
        if self._destructive_confirmation_active():
            self._set_status("Press Y to continue or Q to quit.")
            self._render()
            return
        if self._install_input_capture_active():
            self._set_status("Finish the current install field first.")
            self._render()
            return
        self._details_mode = not self._details_mode
        self._set_status("Detailed view enabled." if self._details_mode else "Simple guided view enabled.")
        self._render()

    def action_refresh_runtime(self) -> None:
        if self._partition_confirmation_active():
            self._set_status('Type exactly "Proceed" then press Enter.')
            self._render()
            return
        if self._destructive_confirmation_active():
            self._set_status("Press Y to continue or Q to quit.")
            self._render()
            return
        if self._install_input_capture_active():
            self._set_status("Finish the current install field first.")
            self._render()
            return
        self._snapshot = collect_live_runtime_snapshot(
            live_runtime_version=self._live_runtime_version,
            max_plan_age_hours=self._max_plan_age_hours,
            efi_mount=self._efi_mount,
        )
        self._snapshot = self._snapshot_with_install_override(self._snapshot)
        if self._snapshot.handoff_mode == "ventoy-plan":
            self._partition_confirmed = True
            self._partition_confirm_armed = False
            self._partition_confirm_text = ""
            self._destructive_confirmed = True
            self._destructive_confirm_armed = False
        else:
            self._partition_confirmed = False
            self._partition_confirm_armed = False
            self._partition_confirm_text = ""
            self._destructive_confirmed = False
            self._destructive_confirm_armed = False
        self._set_status("Runtime state refreshed.")
        self._render()

    def on_key(self, event: events.Key) -> None:
        if self._partition_confirmation_active():
            if event.key == "backspace":
                self._partition_confirm_text = self._partition_confirm_text[:-1]
                self._render()
                event.stop()
                return
            if event.key == "escape":
                self._partition_confirm_text = ""
                self._render()
                event.stop()
                return
            if len(event.character or "") == 1 and event.character.isprintable():
                self._partition_confirm_text += event.character
                self._render()
                event.stop()
            return
        if self._install_input_capture_active():
            if event.key == "backspace":
                self._install_input_buffer = self._install_input_buffer[:-1]
                self._render()
                event.stop()
                return
            if event.key == "escape":
                self._install_input_buffer = ""
                self._render()
                event.stop()
                return
            if len(event.character or "") == 1 and event.character.isprintable():
                self._install_input_buffer += event.character
                self._render()
                event.stop()
            return
        if self._destructive_confirmation_active() and (event.character or "").lower() == "y":
            self._destructive_confirmed = True
            self._destructive_confirm_armed = False
            self._set_status("Final destructive confirmation accepted. Continuing to install.")
            self.action_next_guided_step()
            event.stop()

    def action_quit_flow(self) -> None:
        self.exit(0)


def run_live_bootstrap_tui(
    *,
    live_runtime_version: str = "0.1.0-dev",
    max_plan_age_hours: int | None = 72,
    efi_mount: str = "/boot/efi",
) -> int:
    """Run the live installer Textual UI."""
    app = LiveInstallerApp(
        live_runtime_version=live_runtime_version,
        max_plan_age_hours=max_plan_age_hours,
        efi_mount=efi_mount,
    )
    result = app.run()
    if isinstance(result, int):
        return result
    return 0
