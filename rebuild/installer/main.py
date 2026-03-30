"""Arch live runtime entrypoint for the rebuild installer."""

from __future__ import annotations

import shutil

from .ui.screens import bootstrap_screen_ids


REQUIRED_EXECUTABLES = (
    "python3",
    "nmcli",
    "archinstall",
    "sgdisk",
)


def validate_live_dependencies() -> tuple[bool, tuple[str, ...]]:
    """Validate required live runtime binaries for Layer 2 execution."""
    missing = tuple(binary for binary in REQUIRED_EXECUTABLES if shutil.which(binary) is None)
    return (len(missing) == 0, missing)


def main() -> int:
    ok, missing = validate_live_dependencies()
    if not ok:
        print("Omarchy rebuild live runtime dependency check failed.")
        print("Missing binaries:", ", ".join(missing))
        return 2

    print("Omarchy rebuild live installer bootstrap")
    print("Screen contract:", ", ".join(bootstrap_screen_ids()))
    print("Entrypoint: python3 /opt/omarchy-installer/main.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
