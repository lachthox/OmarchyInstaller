from __future__ import annotations

import sys

from rebuild.tools.windows import omarchy_installer_launcher as launcher


def test_parser_has_no_legacy_powershell_bypass() -> None:
    options = {action.dest for action in launcher.build_parser()._actions}

    assert "legacy_powershell" not in options


def test_startup_failure_is_fatal_and_does_not_fallback(
    monkeypatch,
    capsys,
) -> None:
    def fail_to_start(**_kwargs: object) -> int:
        raise RuntimeError("textual import failed")

    monkeypatch.setattr(launcher, "run_python_tui", fail_to_start)
    monkeypatch.setattr(sys, "argv", ["OmarchyInstaller"])

    assert launcher.main() == launcher.EXIT_FATAL_STARTUP
    error = capsys.readouterr().err
    assert "could not start" in error
    assert "No alternate installer was launched" in error
    assert "PowerShell" not in error


def test_executable_builder_does_not_require_legacy_script(tmp_path) -> None:
    launcher_path = (
        tmp_path / "rebuild" / "tools" / "windows" / "omarchy_installer_launcher.py"
    )
    launcher_path.parent.mkdir(parents=True)
    launcher_path.write_text("raise SystemExit(0)\n", encoding="utf-8")

    assert launcher.ensure_rebuild_on_syspath is not None

    from rebuild.tools.build_windows_exe import ensure_paths

    assert ensure_paths(tmp_path) == launcher_path
