"""Interactive Textual runtime for the Linux live installer flow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import shutil

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
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
    "preflight",
    "network",
    "install_progress",
    "finalize",
    "error",
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
    handoff_sources: tuple[str, ...]
    handoff_result: HandoffDiscoveryResult | None
    handoff_error: str
    network_result: NetworkResolutionResult | None
    network_error: str
    install_result: LiveInstallExecutionResult | None
    install_error: str
    boot_policy_result: BootPolicySummary | None
    boot_policy_error: str


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


def collect_live_runtime_snapshot(
    *,
    live_runtime_version: str = "0.1.0-dev",
    max_plan_age_hours: int | None = 72,
    efi_mount: str = "/boot/efi",
) -> LiveRuntimeSnapshot:
    """Collect live runtime state for all screen stages without destructive actions."""
    dependencies_ok, missing_dependencies = validate_live_dependencies()

    handoff_sources = tuple(discover_handoff_sources())
    handoff_result: HandoffDiscoveryResult | None = None
    handoff_error = ""
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
        except (HandoffDiscoveryError, ValueError) as exc:
            handoff_error = str(exc)
    else:
        handoff_error = "No handoff source containing omarchy/plan.json was discovered."

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
        source_lines = "\n".join(f"- {path}" for path in snapshot.handoff_sources) or "- none"
        plan_line = snapshot.handoff_result.plan_path if snapshot.handoff_result else "N/A"
        return "\n".join(
            [
                "Preflight",
                f"Generated: {snapshot.generated_at_utc}",
                f"Dependencies: {dependency_line}",
                f"Handoff: {handoff_line}",
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
        return "ok" if snapshot.dependencies_ok and snapshot.handoff_result else "blocked"
    if stage_id == "network":
        if snapshot.network_result and snapshot.network_result.connected and not snapshot.network_result.requires_abort:
            return "ok"
        return "blocked"
    if stage_id == "install_progress":
        return "ok" if snapshot.install_result and not snapshot.install_error else "blocked"
    if stage_id == "finalize":
        return "ok" if snapshot.boot_policy_result and snapshot.boot_policy_result.can_finalize else "blocked"
    return "warn"


class LiveInstallerApp(App[int]):
    """Interactive multi-stage TUI for Linux live installer readiness."""

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
    #stages {
      margin-bottom: 1;
      color: $text-muted;
    }
    #content {
      height: 1fr;
    }
    #hints {
      margin-top: 1;
      color: $text-muted;
    }
    """

    BINDINGS = [
        Binding("n,right", "next_stage", "Next Stage"),
        Binding("p,left", "previous_stage", "Previous Stage"),
        Binding("r", "refresh_runtime", "Refresh"),
        Binding("1", "goto_preflight", "Preflight"),
        Binding("2", "goto_network", "Network"),
        Binding("3", "goto_install", "Install"),
        Binding("4", "goto_finalize", "Finalize"),
        Binding("5", "goto_error", "Errors"),
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
            yield Static("Omarchy Arch Live Installer (Python TUI)", id="title")
            yield Static("", id="stages")
            yield Static("", id="content")
            yield Static(
                "Keys: [1-5] select stage  [N/P] next/prev  [R] refresh  [Q] quit",
                id="hints",
            )
        yield Footer()

    def on_mount(self) -> None:
        self.action_refresh_runtime()

    def _active_stage_id(self) -> str:
        return self._stage_ids[self._active_stage_index]

    def _render(self) -> None:
        stage_line_parts = []
        for idx, stage_id in enumerate(self._stage_ids, start=1):
            marker = _status_marker(stage_id, self._snapshot)
            active = "*" if idx - 1 == self._active_stage_index else " "
            stage_line_parts.append(f"{active}{idx}:{stage_id}[{marker}]")
        self.query_one("#stages", Static).update("  ".join(stage_line_parts))
        self.query_one("#content", Static).update(format_stage_content(self._active_stage_id(), self._snapshot))

    def _set_stage(self, stage_id: str) -> None:
        self._active_stage_index = self._stage_ids.index(stage_id)
        self._render()

    def action_next_stage(self) -> None:
        self._active_stage_index = (self._active_stage_index + 1) % len(self._stage_ids)
        self._render()

    def action_previous_stage(self) -> None:
        self._active_stage_index = (self._active_stage_index - 1) % len(self._stage_ids)
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

    def action_refresh_runtime(self) -> None:
        self._snapshot = collect_live_runtime_snapshot(
            live_runtime_version=self._live_runtime_version,
            max_plan_age_hours=self._max_plan_age_hours,
            efi_mount=self._efi_mount,
        )
        self._render()
        self.notify("Runtime state refreshed.", severity="information")

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
