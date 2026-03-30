from __future__ import annotations

import json
from pathlib import Path
import sys

try:
    from rebuild.tools.windows import omarchy_installer_launcher as launcher
except ModuleNotFoundError:  # pragma: no cover - fallback for package-local test runs
    from tools.windows import omarchy_installer_launcher as launcher


def test_resolve_default_policy_prefers_embedded_config(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("OMARCHY_LAUNCHER_DEFAULT_POLICY", raising=False)
    monkeypatch.setattr(launcher.sys, "frozen", False, raising=False)

    defaults_path = tmp_path / "launcher-defaults.json"
    defaults_path.write_text(json.dumps({"default_policy": "python-then-legacy"}) + "\n", encoding="utf-8")
    monkeypatch.setattr(launcher, "bundled_root", lambda: tmp_path)

    assert launcher.resolve_default_policy() == "python-then-legacy"


def test_resolve_effective_policy_respects_cli_override() -> None:
    parser = launcher.build_parser()
    args = parser.parse_args(["--launcher-policy", "legacy-only"])
    assert launcher.resolve_effective_policy(args) == "legacy-only"


def test_resolve_default_policy_prefers_environment(monkeypatch) -> None:
    monkeypatch.setenv("OMARCHY_LAUNCHER_DEFAULT_POLICY", "legacy-only")
    monkeypatch.setattr(launcher.sys, "frozen", True, raising=False)
    assert launcher.resolve_default_policy() == "legacy-only"


def test_normalize_policy_rejects_invalid_value() -> None:
    try:
        launcher._normalize_policy("invalid-policy")
    except ValueError as exc:
        assert "Unsupported launcher policy" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected ValueError for invalid launcher policy")


def test_main_python_then_legacy_chains_on_clean_exit(monkeypatch) -> None:
    calls: dict[str, int] = {"python": 0, "legacy": 0}

    def fake_python_tui(**_: object) -> int:
        calls["python"] += 1
        return 0

    def fake_legacy(_: list[str]) -> int:
        calls["legacy"] += 1
        return 23

    monkeypatch.setattr(launcher, "run_python_tui", fake_python_tui)
    monkeypatch.setattr(launcher, "run_legacy_powershell", fake_legacy)
    monkeypatch.setattr(sys, "argv", ["omarchy", "--launcher-policy", "python-then-legacy"])

    assert launcher.main() == 23
    assert calls == {"python": 1, "legacy": 1}


def test_main_python_only_does_not_chain(monkeypatch) -> None:
    calls: dict[str, int] = {"python": 0, "legacy": 0}

    def fake_python_tui(**_: object) -> int:
        calls["python"] += 1
        return 0

    def fake_legacy(_: list[str]) -> int:
        calls["legacy"] += 1
        return 99

    monkeypatch.setattr(launcher, "run_python_tui", fake_python_tui)
    monkeypatch.setattr(launcher, "run_legacy_powershell", fake_legacy)
    monkeypatch.setattr(sys, "argv", ["omarchy", "--launcher-policy", "python-only"])

    assert launcher.main() == 0
    assert calls == {"python": 1, "legacy": 0}
