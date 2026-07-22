"""Windows launcher entrypoint packaged into OmarchyInstaller.exe."""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path
from typing import Any

EXIT_FATAL_STARTUP = 1


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="OmarchyInstaller",
        add_help=True,
        description="Omarchy Windows installer launcher.",
    )
    parser.add_argument(
        "--python-preflight-json",
        action="store_true",
        help="Run Python preflight checks non-interactively and print JSON.",
    )
    parser.add_argument(
        "--python-apply",
        action="store_true",
        default=True,
        help=argparse.SUPPRESS,
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
    parser.add_argument("--plan", default="", help="Release-paired plan JSON path.")
    parser.add_argument("--iso", default="", help="Release-paired customized ISO path.")
    parser.add_argument("--release-manifest", default="", help="Paired release manifest path.")
    parser.add_argument("--usb-disk-number", type=int, default=-1, help="Explicit Ventoy USB disk number.")
    parser.add_argument("--usb-confirmation", default="", help="Exact ERASE <stable-id> confirmation.")
    ventoy = parser.add_mutually_exclusive_group()
    ventoy.add_argument(
        "--allow-ventoy-install",
        dest="allow_ventoy_install",
        action="store_true",
        help="Allow verified download of the official Ventoy release (the default).",
    )
    ventoy.add_argument(
        "--no-ventoy-install",
        dest="allow_ventoy_install",
        action="store_false",
        help="Require Ventoy to be installed already.",
    )
    parser.set_defaults(allow_ventoy_install=True)
    return parser


def run_python_tui(
    *,
    apply_changes: bool,
    target_free_gib: int,
    backup_destination: str,
    backup_fallback_destination: str,
    plan_path: str,
    iso_path: str,
    release_manifest_path: str,
    usb_disk_number: int,
    usb_confirmation: str,
    allow_ventoy_install: bool,
) -> int:
    ensure_rebuild_on_syspath()
    from installer.platforms import windows as windows_platform  # type: ignore[import-not-found]

    run_windows_preflight_tui: Any = windows_platform.run_windows_preflight_tui

    return int(
        run_windows_preflight_tui(
        apply_changes=apply_changes,
        target_free_gib=target_free_gib,
        backup_destination=backup_destination or None,
        backup_fallback_destination=backup_fallback_destination or None,
        plan_path=plan_path,
        iso_path=iso_path,
        release_manifest_path=release_manifest_path,
        usb_disk_number=usb_disk_number,
        usb_confirmation=usb_confirmation,
        allow_ventoy_install=allow_ventoy_install,
        )
    )


def run_python_preflight_json() -> int:
    ensure_rebuild_on_syspath()
    from installer.platforms.windows import run_windows_preflight  # type: ignore[import-not-found]

    report = run_windows_preflight()
    print(json.dumps(report, indent=2))
    return 0 if bool(report.get("can_proceed", False)) else 3


def main() -> int:
    parser = build_parser()
    args = parser.parse_args(sys.argv[1:])

    if args.python_preflight_json:
        return run_python_preflight_json()

    try:
        tui_result = run_python_tui(
            # The packaged end-user executable is always a real guided run.
            # Simulation remains an internal test capability, not a launch mode.
            apply_changes=True,
            target_free_gib=max(40, int(args.python_target_free_gib)),
            backup_destination=args.python_backup_destination,
            backup_fallback_destination=args.python_backup_fallback_destination,
            plan_path=args.plan,
            iso_path=args.iso,
            release_manifest_path=args.release_manifest,
            usb_disk_number=args.usb_disk_number,
            usb_confirmation=args.usb_confirmation,
            allow_ventoy_install=args.allow_ventoy_install,
        )
    except Exception as exc:  # pragma: no cover - exercised by packaged runtime
        print("FATAL: OmarchyInstaller Python TUI could not start.", file=sys.stderr)
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        print("No alternate installer was launched.", file=sys.stderr)
        return EXIT_FATAL_STARTUP

    return int(tui_result)


if __name__ == "__main__":
    raise SystemExit(main())
