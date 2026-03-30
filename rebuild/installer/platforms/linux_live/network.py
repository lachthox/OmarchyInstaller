"""NetworkManager fallback strategy for Linux live install runtime."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import shutil
import subprocess
from typing import Any, Protocol


DEFAULT_RETRY_ATTEMPTS = 2


class NetworkFallbackError(RuntimeError):
    """Raised when network fallback strategy reaches mandatory abort state."""


class CommandRunner(Protocol):
    """Minimal command-runner protocol for deterministic test stubs."""

    def run(self, command: list[str]) -> subprocess.CompletedProcess[str]: ...


class SubprocessCommandRunner:
    """Default runner backed by subprocess."""

    def run(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )


@dataclass(frozen=True, slots=True)
class NetworkStepResult:
    step: str
    status: str
    detail: str


@dataclass(frozen=True, slots=True)
class NetworkResolutionResult:
    connected: bool
    connection_mode: str
    requires_abort: bool
    active_connection_name: str
    steps: tuple[NetworkStepResult, ...]
    hint: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["steps"] = [asdict(step) for step in self.steps]
        return payload


def _parse_nmcli_table(output: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for raw in output.splitlines():
        line = raw.strip()
        if not line:
            continue
        rows.append(line.split(":"))
    return rows


class NetworkManagerClient:
    def __init__(self, runner: CommandRunner | None = None) -> None:
        self.runner = runner or SubprocessCommandRunner()

    def _run(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        return self.runner.run(command)

    def _nmcli(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        return self._run(["nmcli", *args])

    def nmcli_available(self) -> bool:
        return shutil.which("nmcli") is not None

    def nmtui_available(self) -> bool:
        return shutil.which("nmtui") is not None

    def general_state(self) -> str:
        completed = self._nmcli(["-t", "-f", "STATE", "general", "status"])
        if completed.returncode != 0:
            return ""
        return completed.stdout.strip().lower()

    def active_connection_name(self) -> str:
        completed = self._nmcli(["-t", "-f", "NAME", "connection", "show", "--active"])
        if completed.returncode != 0:
            return ""
        for raw in completed.stdout.splitlines():
            value = raw.strip()
            if value:
                return value
        return ""

    def ethernet_connected(self) -> bool:
        completed = self._nmcli(["-t", "-f", "TYPE,STATE", "device", "status"])
        if completed.returncode != 0:
            return False
        for columns in _parse_nmcli_table(completed.stdout):
            if len(columns) < 2:
                continue
            dev_type, state = columns[0].strip().lower(), columns[1].strip().lower()
            if dev_type == "ethernet" and state == "connected":
                return True
        return False

    def wifi_connected(self) -> bool:
        completed = self._nmcli(["-t", "-f", "TYPE,STATE", "device", "status"])
        if completed.returncode != 0:
            return False
        for columns in _parse_nmcli_table(completed.stdout):
            if len(columns) < 2:
                continue
            dev_type, state = columns[0].strip().lower(), columns[1].strip().lower()
            if dev_type == "wifi" and state == "connected":
                return True
        return False

    def wifi_rescan(self) -> bool:
        completed = self._nmcli(["device", "wifi", "rescan"])
        return completed.returncode == 0

    def connect_wifi(self, profile: dict[str, Any]) -> tuple[bool, str]:
        ssid = str(profile.get("ssid", "")).strip()
        if not ssid:
            return False, "Missing SSID."

        command = ["device", "wifi", "connect", ssid]
        password = str(profile.get("passphrase", "") or profile.get("password", "")).strip()
        if password:
            command.extend(["password", password])
        interface_name = str(profile.get("interface_name", "")).strip()
        if interface_name:
            command.extend(["ifname", interface_name])
        if bool(profile.get("hidden", False)):
            command.extend(["hidden", "yes"])

        completed = self._nmcli(command)
        if completed.returncode != 0:
            message = completed.stderr.strip() or completed.stdout.strip() or "nmcli wifi connect failed"
            return False, message
        return True, completed.stdout.strip() or "Connected via nmcli."

    def run_nmtui(self) -> tuple[bool, str]:
        completed = self._run(["nmtui"])
        if completed.returncode != 0:
            message = completed.stderr.strip() or completed.stdout.strip() or "nmtui exited with non-zero status"
            return False, message
        return True, "nmtui completed successfully."


def _step(steps: list[NetworkStepResult], step: str, status: str, detail: str) -> None:
    steps.append(NetworkStepResult(step=step, status=status, detail=detail))


def _wifi_profile_summary(profile: dict[str, Any]) -> str:
    ssid = str(profile.get("ssid", "")).strip() or "<missing-ssid>"
    security = str(profile.get("wifi_security", "")).strip() or "unknown"
    interface_name = str(profile.get("interface_name", "")).strip() or "auto"
    hidden = bool(profile.get("hidden", False))
    return f"ssid={ssid}, security={security}, interface={interface_name}, hidden={hidden}"


def _sanitize_wifi_detail(detail: str, profile: dict[str, Any]) -> str:
    text = detail
    secrets = [
        str(profile.get("passphrase", "") or "").strip(),
        str(profile.get("password", "") or "").strip(),
    ]
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return text


def _connected_result(mode: str, client: NetworkManagerClient, steps: list[NetworkStepResult]) -> NetworkResolutionResult:
    return NetworkResolutionResult(
        connected=True,
        connection_mode=mode,
        requires_abort=False,
        active_connection_name=client.active_connection_name(),
        steps=tuple(steps),
        hint="",
    )


def resolve_network_connectivity(
    *,
    wifi_handoff_profile: dict[str, Any] | None = None,
    manual_wifi_profile: dict[str, Any] | None = None,
    retry_attempts: int = DEFAULT_RETRY_ATTEMPTS,
    allow_nmtui: bool = True,
    client: NetworkManagerClient | None = None,
) -> NetworkResolutionResult:
    """Resolve network with strict fallback order and fail-closed abort state."""
    active_client = client or NetworkManagerClient()
    steps: list[NetworkStepResult] = []

    if not active_client.nmcli_available():
        _step(steps, "ethernet-check", "fail", "nmcli is unavailable.")
        hint = "Attach a tethered network and verify NetworkManager installation."
        _step(steps, "tethering-hint", "warn", hint)
        _step(steps, "offline-abort", "fail", "No network manager control path is available.")
        return NetworkResolutionResult(
            connected=False,
            connection_mode="offline",
            requires_abort=True,
            active_connection_name="",
            steps=tuple(steps),
            hint=hint,
        )

    # 1) Ethernet
    if active_client.ethernet_connected() and active_client.general_state() == "connected":
        _step(steps, "ethernet-check", "pass", "Ethernet is connected.")
        return _connected_result("ethernet", active_client, steps)
    _step(steps, "ethernet-check", "warn", "Ethernet not connected.")

    # 2) Auto Wi-Fi handoff profile
    if wifi_handoff_profile:
        handoff_summary = _wifi_profile_summary(wifi_handoff_profile)
        ok, detail = active_client.connect_wifi(wifi_handoff_profile)
        safe_detail = _sanitize_wifi_detail(detail, wifi_handoff_profile)
        if ok and active_client.wifi_connected():
            _step(steps, "wifi-handoff", "pass", f"{safe_detail} ({handoff_summary})")
            return _connected_result("wifi", active_client, steps)
        _step(steps, "wifi-handoff", "warn", f"{safe_detail} ({handoff_summary})")
    else:
        _step(steps, "wifi-handoff", "warn", "No auto Wi-Fi handoff profile was provided.")

    # 3) Retry / rescan
    attempts = max(0, retry_attempts)
    for attempt in range(1, attempts + 1):
        scanned = active_client.wifi_rescan()
        if not scanned:
            _step(steps, "wifi-retry-rescan", "warn", f"Attempt {attempt}: wifi rescan failed.")
            continue
        if wifi_handoff_profile:
            handoff_summary = _wifi_profile_summary(wifi_handoff_profile)
            ok, detail = active_client.connect_wifi(wifi_handoff_profile)
            safe_detail = _sanitize_wifi_detail(detail, wifi_handoff_profile)
            if ok and active_client.wifi_connected():
                _step(steps, "wifi-retry-rescan", "pass", f"Attempt {attempt}: {safe_detail} ({handoff_summary})")
                return _connected_result("wifi", active_client, steps)
            _step(steps, "wifi-retry-rescan", "warn", f"Attempt {attempt}: {safe_detail} ({handoff_summary})")
        else:
            _step(steps, "wifi-retry-rescan", "warn", f"Attempt {attempt}: rescan complete, no profile to retry.")

    # 4) Manual profile
    if manual_wifi_profile:
        manual_summary = _wifi_profile_summary(manual_wifi_profile)
        ok, detail = active_client.connect_wifi(manual_wifi_profile)
        safe_detail = _sanitize_wifi_detail(detail, manual_wifi_profile)
        if ok and active_client.wifi_connected():
            _step(steps, "manual-ui-profile", "pass", f"{safe_detail} ({manual_summary})")
            return _connected_result("wifi", active_client, steps)
        _step(steps, "manual-ui-profile", "warn", f"{safe_detail} ({manual_summary})")
    else:
        _step(steps, "manual-ui-profile", "warn", "No manual Wi-Fi profile was provided.")

    # 5) nmtui fallback
    if allow_nmtui and active_client.nmtui_available():
        ok, detail = active_client.run_nmtui()
        if ok and active_client.general_state() == "connected":
            _step(steps, "nmtui-fallback", "pass", detail)
            mode = "wifi" if active_client.wifi_connected() else "ethernet"
            return _connected_result(mode, active_client, steps)
        _step(steps, "nmtui-fallback", "warn", detail)
    else:
        _step(steps, "nmtui-fallback", "warn", "nmtui fallback unavailable or disabled.")

    # 6) Tethering hint
    hint = "Use phone USB tethering or wired ethernet, then rerun preflight."
    _step(steps, "tethering-hint", "warn", hint)

    # 7) Offline abort
    _step(steps, "offline-abort", "fail", "Network fallback order exhausted; aborting install flow.")
    return NetworkResolutionResult(
        connected=False,
        connection_mode="offline",
        requires_abort=True,
        active_connection_name=active_client.active_connection_name(),
        steps=tuple(steps),
        hint=hint,
    )


def assert_network_ready(result: NetworkResolutionResult) -> None:
    """Fail closed if network fallback strategy ended in offline abort state."""
    if result.connected and not result.requires_abort:
        return
    raise NetworkFallbackError("Network fallback strategy reached offline/abort state.")
