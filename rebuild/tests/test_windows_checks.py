from __future__ import annotations

from dataclasses import dataclass

import pytest

from rebuild.installer.platforms.windows.checks import (
    CheckStatus,
    PowerShellProbe,
    evaluate_windows_preflight,
)


@dataclass
class Probe:
    bitlocker: str = "Off"
    fast_startup: bool | None = False
    winre: bool | None = True

    def is_admin(self) -> bool:
        return True

    def windows_version(self) -> str:
        return "10.0.26100"

    def boot_mode(self) -> str:
        return "UEFI"

    def partition_style(self) -> str:
        return "GPT"

    def secure_boot_enabled(self) -> bool | None:
        return True

    def bitlocker_state(self) -> str:
        return self.bitlocker

    def fast_startup_enabled(self) -> bool | None:
        return self.fast_startup

    def winre_enabled(self) -> bool | None:
        return self.winre


def test_preflight_positive_state_passes() -> None:
    report = evaluate_windows_preflight(Probe())
    assert report.can_proceed is True
    assert not report.failures


@pytest.mark.parametrize(
    ("probe", "name"),
    [
        (Probe(bitlocker="Unknown"), "bitlocker"),
        (Probe(fast_startup=None), "fast_startup"),
        (Probe(winre=None), "winre"),
    ],
)
def test_unknown_safety_state_blocks_apply(probe: Probe, name: str) -> None:
    report = evaluate_windows_preflight(probe)
    assert report.can_proceed is False
    assert any(item.name == name and item.status == CheckStatus.FAIL for item in report.failures)


def test_winre_probe_uses_language_neutral_xml(monkeypatch: pytest.MonkeyPatch) -> None:
    commands: list[str] = []
    probe = PowerShellProbe()

    def fake_run(command: str) -> str:
        commands.append(command)
        return "true"

    monkeypatch.setattr(probe, "_run_ps", fake_run)
    assert probe.winre_enabled() is True
    assert "ReAgent.xml" in commands[0]
    assert "reagentc" not in commands[0].casefold()
