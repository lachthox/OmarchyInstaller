from __future__ import annotations

import subprocess

import pytest

from rebuild.installer.platforms.linux_live.network import (
    NetworkFallbackError,
    NetworkManagerClient,
    NetworkReadiness,
    assert_network_ready,
    resolve_network_connectivity,
)


class FakeClient:
    def __init__(self, *, ethernet: bool = True) -> None:
        self.ethernet = ethernet

    def nmcli_available(self) -> bool:
        return True

    def nmtui_available(self) -> bool:
        return False

    def general_state(self) -> str:
        return "connected"

    def active_connection_name(self) -> str:
        return "Wired connection 1"

    def ethernet_connected(self) -> bool:
        return self.ethernet

    def wifi_connected(self) -> bool:
        return False

    def wifi_rescan(self) -> bool:
        return True

    def connect_wifi(self, profile: dict) -> tuple[bool, str]:
        return False, "not used"


class FixedProbe:
    def __init__(self, readiness: NetworkReadiness) -> None:
        self.readiness = readiness

    def assess(self, client: NetworkManagerClient) -> NetworkReadiness:
        return self.readiness


def ready(**overrides: bool) -> NetworkReadiness:
    values = {
        "link": True,
        "ip_configuration": True,
        "dns": True,
        "tls": True,
        "http": True,
        "package_mirror": True,
        "omarchy_bootstrap": True,
        "captive_portal": False,
    }
    values.update(overrides)
    return NetworkReadiness(**values)


def test_networkmanager_connected_with_failed_dns_is_not_ready() -> None:
    result = resolve_network_connectivity(
        client=FakeClient(),  # type: ignore[arg-type]
        connectivity_probe=FixedProbe(ready(dns=False)),
    )
    assert result.connected is False
    assert result.requires_abort is True
    assert result.connection_mode == "limited"
    with pytest.raises(NetworkFallbackError):
        assert_network_ready(result)


def test_tls_http_mirror_bootstrap_and_captive_portal_are_independent() -> None:
    for field in ("tls", "http", "package_mirror", "omarchy_bootstrap"):
        result = resolve_network_connectivity(
            client=FakeClient(),  # type: ignore[arg-type]
            connectivity_probe=FixedProbe(ready(**{field: False})),
        )
        assert result.requires_abort
    portal = resolve_network_connectivity(
        client=FakeClient(),  # type: ignore[arg-type]
        connectivity_probe=FixedProbe(ready(captive_portal=True)),
    )
    assert portal.requires_abort


def test_all_layers_ready_allows_install_preflight() -> None:
    result = resolve_network_connectivity(
        client=FakeClient(),  # type: ignore[arg-type]
        connectivity_probe=FixedProbe(ready()),
    )
    assert result.connected and not result.requires_abort
    assert_network_ready(result)


class RecordingRunner:
    def __init__(self) -> None:
        self.captured: list[list[str]] = []
        self.interactive: list[list[str]] = []

    def run(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        self.captured.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    def run_interactive(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        self.interactive.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")


def test_wifi_password_never_enters_argv_and_interactive_tools_inherit_terminal() -> None:
    runner = RecordingRunner()
    client = NetworkManagerClient(runner=runner)
    secret = "super-secret-passphrase"
    ok, detail = client.connect_wifi({"ssid": "Home", "passphrase": secret})
    assert not ok and "not accepted" in detail
    assert all(secret not in argument for command in runner.interactive for argument in command)

    ok, _ = client.connect_wifi({"ssid": "Home"})
    assert ok
    assert runner.interactive[-1] == ["nmcli", "--ask", "device", "wifi", "connect", "Home"]
    client.run_nmtui()
    assert runner.interactive[-1] == ["nmtui"]
    assert ["nmtui"] not in runner.captured


def test_removable_media_wifi_profile_is_rejected_without_execution() -> None:
    result = resolve_network_connectivity(
        wifi_handoff_profile={"ssid": "Home", "password": "secret"},
        client=FakeClient(),  # type: ignore[arg-type]
        connectivity_probe=FixedProbe(ready()),
    )
    assert result.requires_abort
    assert result.steps[0].step == "wifi-handoff"
