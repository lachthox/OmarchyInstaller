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
        "--python-legacy-handoff",
        action="store_true",
        help="After Python flow completes, hand off to legacy PowerShell workflow.",
    )
    parser.add_argument(
        "--python-preflight-json",
        action="store_true",
        help="Run Python preflight checks non-interactively and print JSON.",
    )
    parser.add_argument(
        "--python-apply",
        action="store_true",
        help="Apply Python backup/partition steps (default is dry-run simulation).",
    )
    parser.add_argument(
        "--python-target-free-gib",
        type=int,
        default=120,
        help="Target unallocated free space (GiB) for Python partition prep.",
    )
    parser.add_argument(
        "--python-backup-destination",
        default="",
        help="Backup destination path for Python backup step.",
    )
    parser.add_argument(
        "--python-backup-fallback-destination",
        default="",
        help="Fallback backup destination path for Python backup step.",
    )
    parser.add_argument(
        "--python-ventoy-disk-number",
        type=int,
        default=None,
        help="Optional Ventoy USB disk number to validate in Python TUI.",
    )
    parser.add_argument(
        "--python-source-iso",
        default="",
        help="Optional source ISO path used when validating Ventoy capacity.",
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


def run_python_tui(
    *,
    launch_legacy_on_continue: bool,
    preflight_only: bool,
    apply_changes: bool,
    target_free_gib: int,
    backup_destination: str,
    backup_fallback_destination: str,
    ventoy_disk_number: int | None,
    source_iso_path: str,
) -> int:
    ensure_rebuild_on_syspath()
    from installer.platforms.windows import EXIT_LAUNCH_LEGACY, run_windows_preflight_tui

    result = run_windows_preflight_tui(
        launch_legacy_on_continue=launch_legacy_on_continue and not preflight_only,
        apply_changes=apply_changes,
        target_free_gib=target_free_gib,
        backup_destination=backup_destination or None,
        backup_fallback_destination=backup_fallback_destination or None,
        ventoy_disk_number=ventoy_disk_number,
        source_iso_path=source_iso_path or None,
    )
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
        tui_result = run_python_tui(
            launch_legacy_on_continue=args.python_legacy_handoff,
            preflight_only=args.python_preflight_only,
            apply_changes=args.python_apply,
            target_free_gib=max(40, int(args.python_target_free_gib)),
            backup_destination=args.python_backup_destination,
            backup_fallback_destination=args.python_backup_fallback_destination,
            ventoy_disk_number=args.python_ventoy_disk_number,
            source_iso_path=args.python_source_iso,
        )
    except Exception as exc:  # pragma: no cover - runtime fallback
        print(f"Python TUI startup failed, falling back to PowerShell: {exc}", file=sys.stderr)
        return run_legacy_powershell(passthrough_args)

    if tui_result == LEGACY_HANDOFF_EXIT_CODE:
        return run_legacy_powershell(passthrough_args)
    return int(tui_result)


if __name__ == "__main__":
    raise SystemExit(main())
