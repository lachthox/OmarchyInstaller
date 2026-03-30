"""Interactive Textual runtime for the Linux live installer flow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import shutil

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual import events
from textual.widgets import Footer, Header, Static

from ..platforms.linux_live.boot_policy import BootPolicyError, BootPolicySummary, summarize_boot_policy
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
    "install",
    "finalize",
    "errors",
)

REQUIRED_LIVE_BINARIES: tuple[str, ...] = (
    "python3",
    "nmcli",
    "archinstall",
    "sgdisk",
)


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
        "Partition step is HIGH-RISK without plan metadata from Windows prep.",
        "Wrong disk or partition choice can permanently destroy data.",
        "Verify target disk, EFI partition, and free-space range manually before continuing.",
        "Confirm Windows backup and recovery path before any partition write.",
    ]
    if handoff_note.strip():
        warnings.append(f"Discovery note: {handoff_note.strip()}")
    return tuple(warnings)


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
            plan_payload=None,
            dry_run=True,
            cleanup_after_success=True,
        )
    except (LiveInstallError, OSError, ValueError) as exc:
        install_error = str(exc)

    boot_policy_result: BootPolicySummary | None = None
    boot_policy_error = ""
    try:
        boot_policy_result = summarize_boot_policy(
            "limine",
            efi_mount=efi_mount,
        )
        if not boot_policy_result.can_finalize:
            boot_policy_error = "; ".join(boot_policy_result.blockers)
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
    if stage_id == "install":
        return "ok" if snapshot.install_result and not snapshot.install_error else "blocked"
    if stage_id == "finalize":
        return "ok" if snapshot.boot_policy_result and snapshot.boot_policy_result.can_finalize else "warn"
    error_present = any(
        (
            not snapshot.dependencies_ok,
            bool(snapshot.network_error),
            bool(snapshot.install_error),
            bool(snapshot.boot_policy_error),
        )
    )
    return "warn" if error_present else "ok"


def _next_stage(stage_id: str, snapshot: LiveRuntimeSnapshot) -> str:
    if stage_id == "welcome":
        if not snapshot.dependencies_ok:
            return "welcome"
        return "network"
    if stage_id == "network":
        if not _network_ready(snapshot):
            return "network"
        return "partitioning"
    if stage_id == "partitioning":
        return "install"
    if stage_id == "install":
        return "finalize"
    if stage_id == "finalize":
        return "errors"
    return "errors"


def format_stage_content(
    stage_id: str,
    snapshot: LiveRuntimeSnapshot,
    *,
    partition_confirm_armed: bool = False,
    partition_confirm_text: str = "",
    partition_confirmed: bool = False,
) -> str:
    """Render stage-specific body content from collected runtime state."""
    if stage_id == "welcome":
        mode_line = "Plan mode (validated handoff)" if snapshot.handoff_mode == "ventoy-plan" else "Standalone mode (manual partition caution)"
        partition_line = "Ready from handoff plan" if _partition_ready(snapshot) else "Manual partition mode with warnings"
        return "\n".join(
            [
                "Guided Setup",
                f"Generated: {snapshot.generated_at_utc}",
                f"Flow Mode: {mode_line}",
                "",
                "1. Network checks",
                "2. Partition plan review",
                "3. Install orchestration",
                "4. Finalize boot policy",
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
                "HIGH-RISK MANUAL MODE",
                "",
                warning_lines or "WARNING. No validated partition plan was found.",
                "",
                "Proceed only if you manually verified disk/partition targets.",
                "",
                confirm_lines,
            ]
        )

    if stage_id == "install":
        if snapshot.install_result is None:
            return "\n".join(
                [
                    "Install",
                    "Dry-run orchestration probe: FAILED",
                    f"Error: {snapshot.install_error or 'install probe did not execute'}",
                ]
            )
        commands = "\n".join(f"- {cmd}" for cmd in snapshot.install_result.commands[:8]) or "- none"
        return "\n".join(
            [
                "Install",
                "Dry-run orchestration probe: PASS",
                f"Status: {snapshot.install_result.status}",
                f"Stage Root: {snapshot.install_result.stage_root}",
                f"Error: {snapshot.install_error or 'none'}",
                "",
                "Planned Commands:",
                commands,
            ]
        )

    if stage_id == "finalize":
        if snapshot.boot_policy_result is None:
            return "\n".join(
                [
                    "Finalize",
                    "Boot policy check: BLOCKED",
                    f"Error: {snapshot.boot_policy_error or 'boot policy probe did not execute'}",
                ]
            )
        blockers = "\n".join(f"- {item}" for item in snapshot.boot_policy_result.blockers) or "- none"
        warnings = "\n".join(f"- {item}" for item in snapshot.boot_policy_result.warnings) or "- none"
        return "\n".join(
            [
                "Finalize",
                f"Can Finalize: {snapshot.boot_policy_result.can_finalize}",
                f"EFI Mount: {snapshot.boot_policy_result.efi_mount}",
                "",
                "Blockers:",
                blockers,
                "Warnings:",
                warnings,
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
      color: $text-muted;
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
        Binding("enter,c", "next_guided_step", "Next Step"),
        Binding("d", "toggle_details", "Details"),
        Binding("r", "refresh_runtime", "Refresh"),
        Binding("q", "quit_flow", "Quit"),
        Binding("n,right", "next_stage", "Next Stage"),
        Binding("p,left", "previous_stage", "Previous Stage"),
        Binding("1", "goto_welcome", "Welcome"),
        Binding("2", "goto_network", "Network"),
        Binding("3", "goto_partitioning", "Partition"),
        Binding("4", "goto_install", "Install"),
        Binding("5", "goto_finalize", "Finalize"),
        Binding("6", "goto_errors", "Errors"),
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
            yield Static("Omarchy Arch Live Installer (Python TUI)", id="title")
            yield Static("Guided mode: Network -> Partitioning -> Install -> Finalize. Press [D] for advanced details.", id="subtitle")
            yield Static("", id="stages")
            yield Static("", id="content")
            yield Static("", id="status")
            yield Static("", id="hints")
        yield Footer()

    def on_mount(self) -> None:
        self.action_refresh_runtime()

    def _active_stage_id(self) -> str:
        return self._stage_ids[self._active_stage_index]

    def _set_status(self, message: str) -> None:
        self._status_message = message.strip() or "Ready."

    def _render(self) -> None:
        stage_line_parts = []
        for idx, stage_id in enumerate(self._stage_ids, start=1):
            marker = _status_marker(stage_id, self._snapshot)
            active = "*" if idx - 1 == self._active_stage_index else " "
            stage_line_parts.append(f"{active}{idx}:{stage_id}[{marker}]")

        stages_widget = self.query_one("#stages", Static)
        if self._details_mode:
            stages_widget.update("  ".join(stage_line_parts))
        else:
            stages_widget.update("")

        self.query_one("#content", Static).update(
            format_stage_content(
                self._active_stage_id(),
                self._snapshot,
                partition_confirm_armed=self._partition_confirm_armed,
                partition_confirm_text=self._partition_confirm_text,
                partition_confirmed=self._partition_confirmed,
            )
        )
        self.query_one("#status", Static).update(f"Status: {self._status_message}")

        hint_widget = self.query_one("#hints", Static)
        if self._details_mode:
            hint_widget.update("Keys: [Enter] next step  [N/P] nav  [1-6] jump  [R] refresh  [D] details  [Q] quit")
        else:
            hint_widget.update("Keys: [Enter] next step  [R] refresh  [D] details  [Q] quit")

    def _set_stage(self, stage_id: str) -> None:
        self._active_stage_index = self._stage_ids.index(stage_id)
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
        target = _next_stage(current, self._snapshot)
        self._active_stage_index = self._stage_ids.index(target)
        self._set_status(f"Moved to {target}.")
        self._render()

    def action_next_stage(self) -> None:
        self._active_stage_index = (self._active_stage_index + 1) % len(self._stage_ids)
        self._set_status(f"Moved to {self._active_stage_id()}.")
        self._render()

    def action_previous_stage(self) -> None:
        self._active_stage_index = (self._active_stage_index - 1) % len(self._stage_ids)
        self._set_status(f"Moved to {self._active_stage_id()}.")
        self._render()

    def action_goto_welcome(self) -> None:
        self._set_stage("welcome")

    def action_goto_network(self) -> None:
        self._set_stage("network")

    def action_goto_partitioning(self) -> None:
        self._set_stage("partitioning")

    def action_goto_install(self) -> None:
        self._set_stage("install")

    def action_goto_finalize(self) -> None:
        self._set_stage("finalize")

    def action_goto_errors(self) -> None:
        self._set_stage("errors")

    def action_toggle_details(self) -> None:
        self._details_mode = not self._details_mode
        self._set_status("Detailed view enabled." if self._details_mode else "Simple guided view enabled.")
        self._render()

    def action_refresh_runtime(self) -> None:
        self._snapshot = collect_live_runtime_snapshot(
            live_runtime_version=self._live_runtime_version,
            max_plan_age_hours=self._max_plan_age_hours,
            efi_mount=self._efi_mount,
        )
        if self._snapshot.handoff_mode == "ventoy-plan":
            self._partition_confirmed = True
            self._partition_confirm_armed = False
            self._partition_confirm_text = ""
        else:
            self._partition_confirmed = False
            self._partition_confirm_armed = False
            self._partition_confirm_text = ""
        self._set_status("Runtime state refreshed.")
        self._render()

    def on_key(self, event: events.Key) -> None:
        if not self._partition_confirm_armed:
            return
        if self._active_stage_id() != "partitioning" or self._snapshot.handoff_mode != "standalone":
            return
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
