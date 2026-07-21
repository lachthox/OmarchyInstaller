"""Windows launcher entrypoint packaged into OmarchyInstaller.exe."""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

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
        "--python-preflight-only",
        action="store_true",
        help="Run Python preflight TUI without applying changes.",
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
    return parser


def run_python_tui(
    *,
    preflight_only: bool,
    apply_changes: bool,
    target_free_gib: int,
    backup_destination: str,
    backup_fallback_destination: str,
) -> int:
    ensure_rebuild_on_syspath()
    from installer.platforms.windows import run_windows_preflight_tui  # type: ignore[import-not-found]

    return int(
        run_windows_preflight_tui(
        apply_changes=apply_changes,
        target_free_gib=target_free_gib,
        backup_destination=backup_destination or None,
        backup_fallback_destination=backup_fallback_destination or None,
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
            preflight_only=args.python_preflight_only,
            apply_changes=args.python_apply,
            target_free_gib=max(40, int(args.python_target_free_gib)),
            backup_destination=args.python_backup_destination,
            backup_fallback_destination=args.python_backup_fallback_destination,
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
