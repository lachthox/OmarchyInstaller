"""Windows launcher entrypoint packaged into OmarchyInstaller.exe."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

LEGACY_HANDOFF_EXIT_CODE = 10


def bundled_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS"))  # type: ignore[arg-type]
    return Path(__file__).resolve().parents[3]


def ensure_rebuild_on_syspath() -> None:
    if getattr(sys, "frozen", False):
        return
    rebuild_root = bundled_root() / "rebuild"
    if rebuild_root.exists():
        rebuild_path = str(rebuild_root)
        if rebuild_path not in sys.path:
            sys.path.insert(0, rebuild_path)


def powershell_script() -> Path:
    return bundled_root() / "windows-prep.ps1"


def build_command(script_path: Path, passthrough_args: list[str]) -> list[str]:
    return [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script_path),
        *passthrough_args,
    ]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="OmarchyInstaller",
        add_help=True,
        description="Omarchy Windows installer launcher.",
    )
    parser.add_argument(
        "--legacy-powershell",
        action="store_true",
        help="Bypass Python TUI and launch legacy PowerShell workflow directly.",
    )
    parser.add_argument(
        "--python-preflight-only",
        action="store_true",
        help="Run Python preflight TUI and exit without launching legacy flow.",
    )
    parser.add_argument(
        "--python-preflight-json",
        action="store_true",
        help="Run Python preflight checks non-interactively and print JSON.",
    )
    return parser


def run_legacy_powershell(passthrough_args: list[str]) -> int:
    script_path = powershell_script()
    if not script_path.exists():
        print(f"Missing bundled script: {script_path}", file=sys.stderr)
        return 2

    command = build_command(script_path, passthrough_args)
    env = dict(os.environ)
    env.setdefault("OMARCHY_INSTALLER_WRAPPED", "1")
    completed = subprocess.run(command, env=env)
    return int(completed.returncode)


def run_python_tui(preflight_only: bool) -> int:
    ensure_rebuild_on_syspath()
    from installer.platforms.windows import EXIT_LAUNCH_LEGACY, run_windows_preflight_tui

    result = run_windows_preflight_tui(launch_legacy_on_continue=not preflight_only)
    if result == EXIT_LAUNCH_LEGACY:
        return LEGACY_HANDOFF_EXIT_CODE
    return int(result)


def run_python_preflight_json() -> int:
    ensure_rebuild_on_syspath()
    from installer.platforms.windows import run_windows_preflight

    report = run_windows_preflight()
    print(json.dumps(report, indent=2))
    return 0 if bool(report.get("can_proceed", False)) else 3


def main() -> int:
    parser = build_parser()
    args, passthrough_args = parser.parse_known_args(sys.argv[1:])

    if args.python_preflight_json:
        return run_python_preflight_json()

    if args.legacy_powershell:
        return run_legacy_powershell(passthrough_args)

    try:
        tui_result = run_python_tui(preflight_only=args.python_preflight_only)
    except Exception as exc:  # pragma: no cover - runtime fallback
        print(f"Python TUI startup failed, falling back to PowerShell: {exc}", file=sys.stderr)
        return run_legacy_powershell(passthrough_args)

    if tui_result == LEGACY_HANDOFF_EXIT_CODE:
        return run_legacy_powershell(passthrough_args)
    return int(tui_result)


if __name__ == "__main__":
    raise SystemExit(main())
