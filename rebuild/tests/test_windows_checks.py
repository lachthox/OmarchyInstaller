from __future__ import annotations

try:
    from rebuild.installer.platforms.windows.checks import evaluate_windows_preflight
except ModuleNotFoundError:  # pragma: no cover - fallback for package-local test runs
    from installer.platforms.windows.checks import evaluate_windows_preflight


class _Probe:
    def __init__(self, *, secure_boot_enabled: bool | None) -> None:
        self._secure_boot_enabled = secure_boot_enabled

    def is_admin(self) -> bool:
        return True

    def windows_version(self) -> str:
        return "10.0.22631"

    def boot_mode(self) -> str:
        return "UEFI"

    def partition_style(self) -> str:
        return "GPT"

    def secure_boot_enabled(self) -> bool | None:
        return self._secure_boot_enabled

    def bitlocker_state(self) -> str:
        return "Off"

    def fast_startup_enabled(self) -> bool | None:
        return False

    def winre_enabled(self) -> bool | None:
        return True


def _status(report: dict, name: str) -> str:
    checks = report.get("checks", [])
    for check in checks:
        if isinstance(check, dict) and check.get("name") == name:
            raw = str(check.get("status", "")).strip().lower()
            if "." in raw:
                return raw.split(".")[-1]
            return raw
    return ""


def test_secure_boot_enabled_blocks_preflight() -> None:
    report = evaluate_windows_preflight(_Probe(secure_boot_enabled=True)).to_dict()
    assert _status(report, "secure_boot") == "fail"
    assert report["can_proceed"] is False


def test_secure_boot_disabled_passes_preflight() -> None:
    report = evaluate_windows_preflight(_Probe(secure_boot_enabled=False)).to_dict()
    assert _status(report, "secure_boot") == "pass"
    assert report["can_proceed"] is True
