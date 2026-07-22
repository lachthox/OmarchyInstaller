from __future__ import annotations

import sys
import json

import rebuild.tools.build_windows_exe as exe_builder

from rebuild.tools.windows import omarchy_installer_launcher as launcher


def test_parser_has_no_legacy_powershell_bypass() -> None:
    options = {action.dest for action in launcher.build_parser()._actions}

    assert "legacy_powershell" not in options
    assert launcher.build_parser().parse_args([]).python_apply is True
    assert launcher.build_parser().parse_args([]).allow_ventoy_install is True
    assert launcher.build_parser().parse_args(["--no-ventoy-install"]).allow_ventoy_install is False


def test_double_click_launch_is_always_real_apply(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def capture_launch(**kwargs: object) -> int:
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(launcher, "run_python_tui", capture_launch)
    monkeypatch.setattr(sys, "argv", ["OmarchyInstaller"])

    assert launcher.main() == 0
    assert captured["apply_changes"] is True
    assert captured["allow_ventoy_install"] is True


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


def test_executable_builder_bakes_release_provisioning_metadata(
    tmp_path,
    monkeypatch,
) -> None:
    launcher_path = tmp_path / "rebuild" / "tools" / "windows" / "omarchy_installer_launcher.py"
    template_path = tmp_path / "rebuild" / "assets" / "templates" / "plan.template.json"
    launcher_path.parent.mkdir(parents=True)
    template_path.parent.mkdir(parents=True)
    launcher_path.write_text("raise SystemExit(0)\n", encoding="utf-8")
    template_path.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(exe_builder, "detect_git_commit", lambda _workspace: "a" * 40)

    output_dir = tmp_path / "output"
    work_dir = tmp_path / "work"
    args = exe_builder.build_parser().parse_args(
        [
            "--workspace",
            str(tmp_path),
            "--output-dir",
            str(output_dir),
            "--work-dir",
            str(work_dir),
            "--release-version",
            "1.2.3",
            "--release-tag",
            "v1.2.3",
            "--release-repo",
            "owner/repo",
            "--dry-run",
        ]
    )

    assert exe_builder.run_pipeline(args) == 0
    build_info = json.loads((work_dir / "build_info.json").read_text(encoding="utf-8"))
    assert build_info["release_tag"] == "v1.2.3"
    assert build_info["release_repo"] == "owner/repo"
    assert build_info["producer_version"] == "1.2.3.0"


def test_executable_builder_requests_uac_elevation(
    tmp_path,
    monkeypatch,
) -> None:
    launcher_path = tmp_path / "rebuild" / "tools" / "windows" / "omarchy_installer_launcher.py"
    template_path = tmp_path / "rebuild" / "assets" / "templates" / "plan.template.json"
    launcher_path.parent.mkdir(parents=True)
    template_path.parent.mkdir(parents=True)
    launcher_path.write_text("raise SystemExit(0)\n", encoding="utf-8")
    template_path.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(exe_builder, "detect_git_commit", lambda _workspace: "a" * 40)
    captured: list[str] = []

    def fake_build(command: list[str], cwd=None) -> None:
        captured.extend(command)
        dist = tmp_path / "output"
        dist.mkdir(parents=True, exist_ok=True)
        (dist / "OmarchyInstaller.exe").write_bytes(b"packaged-exe")

    monkeypatch.setattr(exe_builder, "run_command", fake_build)
    args = exe_builder.build_parser().parse_args(
        [
            "--workspace",
            str(tmp_path),
            "--output-dir",
            str(tmp_path / "output"),
            "--work-dir",
            str(tmp_path / "work"),
            "--release-version",
            "1.2.3",
            "--release-tag",
            "v1.2.3",
        ]
    )

    assert exe_builder.run_pipeline(args) == 0
    assert "--uac-admin" in captured
