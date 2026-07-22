"""Interactive Textual runtime for the Linux live installer flow."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
import shutil
import subprocess
import time

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Footer, Header, Input, Static
from textual import work

from ..platforms.linux_live.boot_policy import BootPolicySummary
from ..platforms.linux_live.discovery import (
    HandoffDiscoveryError,
    HandoffDiscoveryResult,
    HandoffValidationContext,
    build_validation_context_from_runtime,
    enumerate_ventoy_data_partitions,
    open_validated_handoff,
)
from ..platforms.linux_live.identity import (
    IdentityMatchResult,
    match_machine_identity,
    resolve_target_disk_path,
)
from ..platforms.linux_live.install import LiveInstallExecutionResult, execute_install_plan
from ..platforms.linux_live.network import NetworkResolutionResult, resolve_network_connectivity
from .live_state import confirmation_token


WINDOWS_PREP_SCREEN_CONTRACT: tuple[str, ...] = (
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

LIVE_BOOTSTRAP_SCREEN_CONTRACT: tuple[str, ...] = (
    "preflight",
    "network",
    "install_progress",
    "finalize",
    "error",
)

LIVE_WIZARD_TITLES: tuple[str, ...] = (
    "Check the installer USB",
    "Connect to the internet",
    "Create your password",
    "Ready to install Omarchy",
    "Installing Omarchy",
)
LIVE_INSTALLER_TITLE = "Omarchy Installer"

REQUIRED_LIVE_BINARIES: tuple[str, ...] = (
    "python3",
    "nmcli",
    "archinstall",
    "sgdisk",
    "openssl",
)


@dataclass(frozen=True, slots=True)
class LiveRuntimeSnapshot:
    generated_at_utc: str
    dependencies_ok: bool
    missing_dependencies: tuple[str, ...]
    handoff_sources: tuple[str, ...]
    handoff_result: HandoffDiscoveryResult | None
    handoff_error: str
    network_result: NetworkResolutionResult | None
    network_error: str
    install_result: LiveInstallExecutionResult | None
    install_error: str
    boot_policy_result: BootPolicySummary | None
    boot_policy_error: str
    identity_result: IdentityMatchResult | None = None
    identity_error: str = ""


def bootstrap_screen_ids() -> list[str]:
    """Return the ordered Arch live bootstrap screen identifiers."""
    if len(set(LIVE_BOOTSTRAP_SCREEN_CONTRACT)) != len(LIVE_BOOTSTRAP_SCREEN_CONTRACT):
        raise ValueError("Bootstrap screen contract contains duplicate identifiers.")
    return list(LIVE_BOOTSTRAP_SCREEN_CONTRACT)


def windows_prep_screen_ids() -> list[str]:
    """Return the ordered Windows prep screen identifiers."""
    if len(set(WINDOWS_PREP_SCREEN_CONTRACT)) != len(WINDOWS_PREP_SCREEN_CONTRACT):
        raise ValueError("Windows prep screen contract contains duplicate identifiers.")
    return list(WINDOWS_PREP_SCREEN_CONTRACT)


def validate_live_dependencies() -> tuple[bool, tuple[str, ...]]:
    """Validate required runtime binaries for live installer entry."""
    missing = tuple(binary for binary in REQUIRED_LIVE_BINARIES if shutil.which(binary) is None)
    return (len(missing) == 0, missing)


def _now_utc() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _discover_live_handoff(
    context: HandoffValidationContext,
    *,
    attempts: int = 3,
    retry_delay_seconds: float = 1.0,
) -> tuple[tuple[str, ...], HandoffDiscoveryResult | None, str]:
    """Retry removable-media discovery to absorb USB/udev startup races."""
    sources: tuple[str, ...] = tuple()
    last_error = ""
    for attempt in range(max(1, attempts)):
        try:
            sources = enumerate_ventoy_data_partitions()
            with open_validated_handoff(context) as validated_handoff:
                return sources, validated_handoff, ""
        except (HandoffDiscoveryError, OSError, ValueError) as exc:
            last_error = str(exc)
            if attempt + 1 < attempts:
                time.sleep(retry_delay_seconds)
    return sources, None, last_error


def collect_live_runtime_snapshot(
    *,
    live_runtime_version: str = "0.1.0-dev",
    max_plan_age_hours: int | None = None,
    efi_mount: str = "/boot/efi",
    integrity_key: bytes | None = None,
) -> LiveRuntimeSnapshot:
    """Collect live runtime state for all screen stages without destructive actions."""
    dependencies_ok, missing_dependencies = validate_live_dependencies()

    handoff_sources: tuple[str, ...] = tuple()
    handoff_result: HandoffDiscoveryResult | None = None
    handoff_error = ""
    context = build_validation_context_from_runtime(
        live_runtime_version=live_runtime_version,
        max_plan_age_hours=max_plan_age_hours,
        integrity_key=integrity_key,
    )
    handoff_sources, handoff_result, handoff_error = _discover_live_handoff(context)

    identity_result: IdentityMatchResult | None = None
    identity_error = ""
    if handoff_result is not None:
        try:
            identity_result = match_machine_identity(handoff_result.plan)
        except Exception as exc:
            identity_error = str(exc)
    else:
        identity_error = "Machine identity cannot be checked without a validated handoff."

    network_result: NetworkResolutionResult | None = None
    network_error = ""
    try:
        network_result = resolve_network_connectivity(
            retry_attempts=0,
            allow_nmtui=False,
        )
        if network_result.requires_abort or not network_result.connected:
            network_error = network_result.hint or "Network fallback strategy did not reach a connected state."
    except Exception as exc:  # pragma: no cover - defensive runtime guard
        network_error = str(exc)

    install_result: LiveInstallExecutionResult | None = None
    install_error = ""
    install_error = "Installation has not started yet."

    boot_policy_result: BootPolicySummary | None = None
    boot_policy_error = ""
    boot_policy_error = "Post-install boot policy validation has not run; Limine is not a pre-install requirement."

    return LiveRuntimeSnapshot(
        generated_at_utc=_now_utc(),
        dependencies_ok=dependencies_ok,
        missing_dependencies=missing_dependencies,
        handoff_sources=handoff_sources,
        handoff_result=handoff_result,
        handoff_error=handoff_error,
        network_result=network_result,
        network_error=network_error,
        install_result=install_result,
        install_error=install_error,
        boot_policy_result=boot_policy_result,
        boot_policy_error=boot_policy_error,
        identity_result=identity_result,
        identity_error=identity_error,
    )


def _shorten(value: str, *, max_len: int = 110) -> str:
    text = value.strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def format_stage_content(stage_id: str, snapshot: LiveRuntimeSnapshot) -> str:
    """Render stage-specific body content from collected runtime state."""
    if stage_id == "preflight":
        dependency_line = "PASS" if snapshot.dependencies_ok else f"BLOCKED: missing {', '.join(snapshot.missing_dependencies)}"
        handoff_line = "PASS" if snapshot.handoff_result else f"BLOCKED: {snapshot.handoff_error or 'handoff plan not available'}"
        identity_line = (
            f"PASS: {snapshot.identity_result.disk.path}"
            if snapshot.identity_result
            else f"BLOCKED: {snapshot.identity_error or 'identity not available'}"
        )
        source_lines = "\n".join(f"- {path}" for path in snapshot.handoff_sources) or "- none"
        plan_line = snapshot.handoff_result.plan_path if snapshot.handoff_result else "N/A"
        return "\n".join(
            [
                "Preflight",
                f"Generated: {snapshot.generated_at_utc}",
                f"Dependencies: {dependency_line}",
                f"Handoff: {handoff_line}",
                f"Machine identity: {identity_line}",
                f"Plan Path: {plan_line}",
                "Discovered Sources:",
                source_lines,
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
            for step in snapshot.network_result.steps[:10]
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
                "Steps:",
                steps,
            ]
        )

    if stage_id == "install_progress":
        if snapshot.install_result is None:
            return "\n".join(
                [
                    "Install Progress",
                    "Dry-run orchestration probe: FAILED",
                    f"Error: {snapshot.install_error or 'install probe did not execute'}",
                ]
            )
        commands = "\n".join(f"- {cmd}" for cmd in snapshot.install_result.commands[:10]) or "- none"
        return "\n".join(
            [
                "Install Progress",
                "Dry-run orchestration probe: PASS",
                f"Status: {snapshot.install_result.status}",
                f"Stage Root: {snapshot.install_result.stage_root}",
                f"Staged Files: {len(snapshot.install_result.staged_files)}",
                f"Cleanup Paths: {len(snapshot.install_result.removed_paths)}",
                "Planned Commands:",
                commands,
            ]
        )

    if stage_id == "finalize":
        if snapshot.boot_policy_result is None:
            if snapshot.install_result is not None:
                return "\n".join(
                    [
                        "Finalize",
                        f"Target finalization: {snapshot.install_result.target_finalization_status}",
                        "Installed-target invariants were checked by the production engine.",
                        "Reboot and firmware preservation remain release acceptance gates.",
                    ]
                )
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
                f"Windows EFI Exists: {snapshot.boot_policy_result.windows_efi_exists}",
                f"Limine EFI Exists: {snapshot.boot_policy_result.limine_efi_exists}",
                f"Boot Order: {', '.join(snapshot.boot_policy_result.boot_order) or 'unknown'}",
                "Blockers:",
                blockers,
                "Warnings:",
                warnings,
            ]
        )

    error_lines = [
        "Errors and Warnings",
        f"Preflight: {'none' if snapshot.dependencies_ok else 'missing dependencies'}",
        f"Handoff: {snapshot.handoff_error or 'none'}",
        f"Network: {snapshot.network_error or 'none'}",
        f"Install: {snapshot.install_error or 'none'}",
        f"Finalize: {snapshot.boot_policy_error or 'none'}",
    ]
    return "\n".join(error_lines)


def _status_marker(stage_id: str, snapshot: LiveRuntimeSnapshot) -> str:
    if stage_id == "preflight":
        return "ok" if snapshot.dependencies_ok and snapshot.handoff_result and snapshot.identity_result else "blocked"
    if stage_id == "network":
        if snapshot.network_result and snapshot.network_result.connected and not snapshot.network_result.requires_abort:
            return "ok"
        return "blocked"
    if stage_id == "install_progress":
        return "ok" if snapshot.install_result and not snapshot.install_error else "blocked"
    if stage_id == "finalize":
        if snapshot.install_result is not None:
            return (
                "ok"
                if snapshot.install_result.target_finalization_status == "completed"
                else "warn"
            )
        return "ok" if snapshot.boot_policy_result and snapshot.boot_policy_result.can_finalize else "blocked"
    return "warn"


class LiveInstallerApp(App[int]):
    """Beginner-first guided installer with diagnostics hidden by default."""

    TITLE = LIVE_INSTALLER_TITLE

    CSS = """
    Screen {
      layout: vertical;
    }
    #body {
      padding: 0 1;
      height: 1fr;
    }
    #title {
      text-style: bold;
      height: 1;
    }
    #wizard {
      height: auto;
      border: round $success;
      padding: 1 2;
    }
    #wiz-progress { color: $text-muted; height: 1; }
    #wiz-title { text-style: bold; height: auto; padding: 1 0 0 0; }
    #wiz-body { height: auto; padding: 1 0; }
    #wiz-status { height: auto; }
    #wiz-actions { color: $accent; text-style: bold; height: auto; padding: 1 0 0 0; }
    #password, #password-confirm { margin-top: 1; }
    #advanced { height: 1fr; }
    #stages { color: $text-muted; height: auto; }
    #content { height: 1fr; border: round $primary; padding: 0 1; }
    #advanced-hints {
      color: $text-muted;
      height: auto;
    }
    """

    BINDINGS = [
        Binding("enter", "wizard_primary", "Continue"),
        Binding("a", "toggle_view", "Advanced"),
        Binding("r", "refresh_runtime", "Refresh"),
        Binding("w", "connect_network", "Connect Network"),
        Binding("q", "quit_flow", "Quit"),
        Binding("escape", "quit_flow", "Quit", show=False),
    ]

    def __init__(
        self,
        *,
        live_runtime_version: str = "0.1.0-dev",
        max_plan_age_hours: int | None = None,
        efi_mount: str = "/boot/efi",
    ) -> None:
        super().__init__()
        self._stage_ids = bootstrap_screen_ids()
        self._active_stage_index = 0
        self._view = "wizard"
        self._refreshing = False
        self._installing = False
        self._install_started = False
        self._credentials_ready = False
        self._install_password = ""
        self._live_runtime_version = live_runtime_version
        self._max_plan_age_hours = max_plan_age_hours
        self._efi_mount = efi_mount
        self._snapshot = LiveRuntimeSnapshot(
            generated_at_utc=_now_utc(),
            dependencies_ok=False,
            missing_dependencies=REQUIRED_LIVE_BINARIES,
            handoff_sources=tuple(),
            handoff_result=None,
            handoff_error="Not collected yet.",
            network_result=None,
            network_error="Not collected yet.",
            install_result=None,
            install_error="Not collected yet.",
            boot_policy_result=None,
            boot_policy_error="Not collected yet.",
        )

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="body"):
            yield Static(LIVE_INSTALLER_TITLE, id="title")
            with Vertical(id="wizard"):
                yield Static("", id="wiz-progress")
                yield Static("", id="wiz-title")
                yield Static("", id="wiz-body")
                yield Input(placeholder="Choose a password", password=True, id="password")
                yield Input(placeholder="Type the password again", password=True, id="password-confirm")
                yield Static("", id="wiz-status")
                yield Static("", id="wiz-actions")
            with Vertical(id="advanced"):
                yield Static("", id="stages", markup=False)
                yield Static("", id="content")
                yield Static("[A] Guided view   [R] Refresh checks   [W] Network setup   [Q] Quit", id="advanced-hints")
        yield Footer()

    def on_mount(self) -> None:
        for field in self.query(Input):
            field.can_focus = False
            field.display = False
        self._apply_view()
        self.action_refresh_runtime()

    def _active_stage_id(self) -> str:
        return self._stage_ids[self._active_stage_index]

    def _preflight_ready(self) -> bool:
        return bool(
            self._snapshot.dependencies_ok
            and self._snapshot.handoff_result
            and self._snapshot.identity_result
        )

    def _network_ready(self) -> bool:
        network = self._snapshot.network_result
        return bool(network and network.connected and not network.requires_abort)

    def _wizard_step(self) -> int:
        if self._install_started:
            return 4
        if not self._preflight_ready():
            return 0
        if not self._network_ready():
            return 1
        if not self._credentials_ready:
            return 2
        return 3

    def _apply_view(self) -> None:
        guided = self._view == "wizard"
        wizard = self.query_one("#wizard", Vertical)
        advanced = self.query_one("#advanced", Vertical)
        wizard.display = guided
        advanced.display = not guided
        if guided:
            wizard.can_focus = True
            wizard.focus(scroll_visible=False)
        self._render()

    def action_toggle_view(self) -> None:
        self._view = "advanced" if self._view == "wizard" else "wizard"
        self._apply_view()

    def _wizard_body(self, step: int) -> str:
        if step == 0:
            return (
                "We are checking the USB and matching it to the Windows setup. "
                "This does not change your computer."
            )
        if step == 1:
            return (
                "Omarchy needs an internet connection to finish installing. "
                "If Wi-Fi setup opens, choose your network and enter its password."
            )
        if step == 2:
            return (
                "Choose one password for unlocking Omarchy and signing in. "
                "Use at least 8 characters. You will need this password whenever the computer starts."
            )
        if step == 3:
            handoff = self._snapshot.handoff_result
            size_gib = 0.0
            if handoff is not None:
                target = handoff.plan.linux_install_target
                if target is not None:
                    size_gib = target.disk_identity.disk_size_bytes / (1024**3)
                else:
                    size_gib = handoff.plan.prepared_free_space_range.size_bytes / (1024**3)
            return (
                f"Omarchy will use the {size_gib:.0f} GB space prepared by Windows.\n\n"
                "Your Windows partition and Windows boot files will be kept. "
                "Keep the computer plugged into power during installation."
            )
        if self._snapshot.install_result is not None:
            return (
                "Omarchy was installed successfully.\n\n"
                "Remove the USB stick, then press Enter to restart your computer."
            )
        if self._snapshot.install_error and self._install_started and not self._installing:
            return (
                "Installation stopped before it could finish. Your diagnostic details are available "
                "in Advanced view. Leave the computer on while you record the error."
            )
        return (
            "Installing Omarchy now. This usually takes 15–40 minutes. "
            "The screen may stay on one message for several minutes; do not turn off the computer."
        )

    def _wizard_status(self, step: int) -> str:
        if step == 0:
            if self._refreshing:
                return "⏳ Checking the installer USB…"
            if self._preflight_ready():
                return "✔ Installer USB is ready."
            if self._snapshot.handoff_error and self._snapshot.handoff_error != "Not collected yet.":
                return "✖ We couldn't read the installer USB. Press Enter to try again."
            return "Press Enter to check the installer USB."
        if step == 1:
            return "Press Enter to connect to the internet."
        if step == 2:
            return "Type the same password in both boxes, then press Enter."
        if step == 3:
            return "Press Enter to begin the real installation."
        if self._installing:
            return "⏳ Installation is running. Please wait."
        if self._snapshot.install_result is not None:
            return "✔ Installation complete."
        return "✖ Installation did not finish. Press A to view details."

    def _render_wizard(self) -> None:
        step = self._wizard_step()
        dots = " ".join("●" if index < step else ("◉" if index == step else "○") for index in range(5))
        self.query_one("#wiz-progress", Static).update(f"Step {step + 1} of 5   {dots}")
        self.query_one("#wiz-title", Static).update(LIVE_WIZARD_TITLES[step])
        self.query_one("#wiz-body", Static).update(self._wizard_body(step))
        self.query_one("#wiz-status", Static).update(self._wizard_status(step))

        password = self.query_one("#password", Input)
        confirmation = self.query_one("#password-confirm", Input)
        show_passwords = step == 2 and self._view == "wizard"
        for field in (password, confirmation):
            field.display = show_passwords
            field.can_focus = show_passwords
        if show_passwords and not (password.has_focus or confirmation.has_focus):
            password.focus()

        primary = {
            0: "Try again",
            1: "Connect",
            2: "Continue",
            3: "Install Omarchy",
            4: "Restart" if self._snapshot.install_result is not None else "Please wait",
        }[step]
        advanced = "   [A] Advanced details"
        self.query_one("#wiz-actions", Static).update(
            f"[Enter] {primary}{advanced}   [Q] Quit"
        )

    def _render(self) -> None:
        stage_line_parts = []
        for idx, stage_id in enumerate(self._stage_ids, start=1):
            marker = _status_marker(stage_id, self._snapshot)
            active = "*" if idx - 1 == self._active_stage_index else " "
            stage_line_parts.append(f"{active}{idx}:{stage_id}[{marker}]")
        self.query_one("#stages", Static).update("  ".join(stage_line_parts))
        self.query_one("#content", Static).update(format_stage_content(self._active_stage_id(), self._snapshot))
        self._render_wizard()

    def _set_stage(self, stage_id: str) -> None:
        self._active_stage_index = self._stage_ids.index(stage_id)
        self._render()

    def action_goto_preflight(self) -> None:
        self._set_stage("preflight")

    def action_goto_network(self) -> None:
        self._set_stage("network")

    def action_goto_install(self) -> None:
        self._set_stage("install_progress")

    def action_goto_finalize(self) -> None:
        self._set_stage("finalize")

    def action_goto_error(self) -> None:
        self._set_stage("error")

    @work(thread=True, exclusive=True, group="live-refresh")
    def _refresh_worker(self) -> None:
        try:
            snapshot = collect_live_runtime_snapshot(
                live_runtime_version=self._live_runtime_version,
                max_plan_age_hours=self._max_plan_age_hours,
                efi_mount=self._efi_mount,
            )
            self.call_from_thread(self._apply_refresh, snapshot, None)
        except Exception as exc:  # pragma: no cover - defensive worker boundary
            self.call_from_thread(self._apply_refresh, None, str(exc))

    def _apply_refresh(self, snapshot: LiveRuntimeSnapshot | None, error: str | None) -> None:
        self._refreshing = False
        if snapshot is None:
            self._snapshot = LiveRuntimeSnapshot(
                generated_at_utc=_now_utc(),
                dependencies_ok=False,
                missing_dependencies=REQUIRED_LIVE_BINARIES,
                handoff_sources=tuple(),
                handoff_result=None,
                handoff_error=error or "Runtime refresh failed.",
                network_result=None,
                network_error=error or "Runtime refresh failed.",
                install_result=None,
                install_error=error or "Runtime refresh failed.",
                boot_policy_result=None,
                boot_policy_error=error or "Runtime refresh failed.",
            )
            self._render()
            self.notify("Runtime refresh failed.", severity="error")
            return
        self._snapshot = snapshot
        self._render()
        self.notify("Runtime state refreshed.", severity="information")

    def action_refresh_runtime(self) -> None:
        if self._refreshing or self._installing:
            return
        self._refreshing = True
        self._render()
        self.notify("Refreshing runtime state…", severity="information")
        self._refresh_worker()

    @work(thread=True, exclusive=True, group="live-network")
    def _network_worker(self) -> None:
        try:
            result = resolve_network_connectivity(retry_attempts=2, allow_nmtui=True)
            error = "" if result.connected and not result.requires_abort else result.hint
            self.call_from_thread(self._apply_network_result, result, error)
        except Exception as exc:
            self.call_from_thread(self._apply_network_result, None, str(exc))

    def _apply_network_result(
        self, result: NetworkResolutionResult | None, error: str
    ) -> None:
        self._snapshot = replace(
            self._snapshot,
            network_result=result,
            network_error=error,
        )
        self._render()
        self.notify(
            "Network readiness passed." if result and not error else "Network readiness blocked.",
            severity="information" if result and not error else "error",
        )

    def action_connect_network(self) -> None:
        self.notify("Starting interactive NetworkManager fallback.")
        self._network_worker()

    def _start_install(self) -> None:
        snapshot = self._snapshot
        if not snapshot.dependencies_ok or snapshot.handoff_result is None or snapshot.identity_result is None:
            self.notify("Preflight, handoff, and machine identity must pass.", severity="error")
            return
        if snapshot.network_result is None or not snapshot.network_result.connected or snapshot.network_result.requires_abort:
            self.notify("Network readiness must pass before installation.", severity="error")
            return
        if not self._credentials_ready or not self._install_password:
            self.notify("Create your password before starting installation.", severity="error")
            return
        confirmation = confirmation_token(snapshot.handoff_result.plan)
        password = self._install_password
        self._install_password = ""
        self._install_started = True
        self._installing = True
        self._render()
        self.notify("Installation started. Keep the computer plugged into power.")
        self._install_worker(False, confirmation, password, password)

    @work(thread=True, exclusive=True, group="live-install")
    def _install_worker(
        self,
        dry_run: bool,
        confirmation: str,
        encryption_passphrase: str,
        user_password: str,
    ) -> None:
        try:
            handoff = self._snapshot.handoff_result
            identity = self._snapshot.identity_result
            if handoff is None or identity is None:
                raise RuntimeError("Validated handoff and machine identity disappeared before apply.")
            expected = confirmation_token(handoff.plan)
            if not dry_run and confirmation != expected:
                raise RuntimeError(f"Typed confirmation must exactly match {expected}.")
            password_hash = ""
            if not dry_run:
                completed = subprocess.run(
                    ["openssl", "passwd", "-6", "-stdin"],
                    input=user_password + "\n",
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if completed.returncode != 0 or not completed.stdout.strip().startswith("$6$"):
                    raise RuntimeError("Unable to derive the target user password hash.")
                password_hash = completed.stdout.strip()
            # Separate-disk install: the Linux root goes on the target disk while
            # the ESP + Limine stay on the Windows disk. Single-disk installs use
            # the Windows disk for both.
            if handoff.plan.linux_install_target is not None:
                linux_disk_path = resolve_target_disk_path(handoff.plan)
                esp_disk_path = identity.disk.path
            else:
                linux_disk_path = identity.disk.path
                esp_disk_path = ""
            result = execute_install_plan(
                handoff.plan,
                target_disk_path=linux_disk_path,
                esp_disk_path=esp_disk_path,
                dry_run=dry_run,
                encryption_passphrase=encryption_passphrase,
                user_password_hash=password_hash,
                efi_partition_path=identity.efi_partition.path,
                cleanup_after_success=not dry_run,
            )
            self.call_from_thread(self._apply_install_result, result, None)
        except Exception as exc:
            self.call_from_thread(self._apply_install_result, None, str(exc))

    def _apply_install_result(
        self, result: LiveInstallExecutionResult | None, error: str | None
    ) -> None:
        self._installing = False
        self._snapshot = replace(
            self._snapshot,
            install_result=result,
            install_error=error or "",
        )
        self._active_stage_index = self._stage_ids.index("install_progress" if result else "error")
        self._render()
        self.notify(
            "Installation orchestration completed." if result else "Installation failed.",
            severity="information" if result else "error",
        )

    def action_apply_install(self) -> None:
        self._start_install()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "password":
            self.query_one("#password-confirm", Input).focus()
            return
        if event.input.id == "password-confirm":
            self.action_wizard_primary()

    def action_wizard_primary(self) -> None:
        if self._view != "wizard" or self._refreshing or self._installing:
            return
        step = self._wizard_step()
        if step == 0:
            self.action_refresh_runtime()
            return
        if step == 1:
            self.action_connect_network()
            return
        if step == 2:
            password_field = self.query_one("#password", Input)
            confirmation_field = self.query_one("#password-confirm", Input)
            password = password_field.value
            repeated = confirmation_field.value
            if len(password) < 8:
                self.notify("Choose a password with at least 8 characters.", severity="error")
                password_field.focus()
                return
            if password != repeated:
                self.notify("The two passwords do not match. Please try again.", severity="error")
                confirmation_field.value = ""
                confirmation_field.focus()
                return
            self._install_password = password
            self._credentials_ready = True
            password_field.value = ""
            confirmation_field.value = ""
            self._render()
            return
        if step == 3:
            self._start_install()
            return
        if self._snapshot.install_result is not None:
            self.notify("Restarting… remove the USB stick now.")
            subprocess.Popen(["systemctl", "reboot"])

    def action_quit_flow(self) -> None:
        self.exit(0)


def run_live_bootstrap_tui(
    *,
    live_runtime_version: str = "0.1.0-dev",
    max_plan_age_hours: int | None = None,
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
