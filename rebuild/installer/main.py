"""Arch live runtime entrypoint for the rebuild installer."""

from __future__ import annotations

import argparse

from .ui.screens import (
    bootstrap_screen_ids,
    run_live_bootstrap_tui,
    validate_live_dependencies,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="omarchy-live-installer",
        description="Omarchy Arch live installer entrypoint.",
    )
    parser.add_argument(
        "--no-tui",
        action="store_true",
        help="Run dependency and screen-contract checks only.",
    )
    parser.add_argument(
        "--runtime-version",
        default="0.1.0-dev",
        help="Live runtime version used for handoff validation context.",
    )
    parser.add_argument(
        "--max-plan-age-hours",
        type=int,
        default=-1,
        help="Optional explicit maximum plan age; disabled by default in favor of artifact pairing.",
    )
    parser.add_argument(
        "--efi-mount",
        default="/boot/efi",
        help="EFI mount path used for finalize-stage boot policy checks.",
    )
    return parser


def run_no_tui_mode() -> int:
    ok, missing = validate_live_dependencies()
    print("Omarchy rebuild live installer bootstrap (no-tui mode)")
    print("Screen IDs:", ", ".join(bootstrap_screen_ids()))
    if ok:
        print("Dependency check: PASS")
        return 0
    print("Dependency check: BLOCKED")
    print("Missing binaries:", ", ".join(missing))
    return 2


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.no_tui:
        return run_no_tui_mode()

    max_plan_age_hours = None if args.max_plan_age_hours < 0 else args.max_plan_age_hours
    return run_live_bootstrap_tui(
        live_runtime_version=args.runtime_version,
        max_plan_age_hours=max_plan_age_hours,
        efi_mount=args.efi_mount,
    )


if __name__ == "__main__":
    raise SystemExit(main())
