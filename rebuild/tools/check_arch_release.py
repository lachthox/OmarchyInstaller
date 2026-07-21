"""Detect whether a new official Arch ISO release is available.

Used by the scheduled release workflow: compares the currently pinned ISO
date/archinstall version (recorded in `rebuild/pinned-arch-release.json`)
against what the official mirror currently publishes. Emits GitHub Actions
step outputs so downstream jobs can decide whether to build/test/publish a
new pinned release, and does nothing (exit 0, `changed=false`) when the
upstream release is unchanged.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path


MIRROR_LATEST_DIR = "https://geo.mirror.pkgbuild.com/iso/latest/"
PINNED_FILE = Path(__file__).resolve().parents[1] / "pinned-arch-release.json"


def fetch_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "OmarchyInstaller-release-check/1"})
    with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
        return response.read().decode("utf-8", errors="replace")


def detect_latest_iso_date() -> str:
    listing = fetch_text(MIRROR_LATEST_DIR)
    match = re.search(r"archlinux-(\d{4}\.\d{2}\.\d{2})-x86_64\.iso", listing)
    if not match:
        raise RuntimeError("Could not determine the latest published Arch ISO date from the mirror listing.")
    return match.group(1)


def load_pinned() -> dict[str, str]:
    if not PINNED_FILE.is_file():
        return {"iso_version": "", "archinstall_version": ""}
    return json.loads(PINNED_FILE.read_text(encoding="utf-8"))


def write_pinned(iso_version: str, archinstall_version: str) -> None:
    PINNED_FILE.write_text(
        json.dumps({"iso_version": iso_version, "archinstall_version": archinstall_version}, indent=2) + "\n",
        encoding="utf-8",
    )


def emit_output(name: str, value: str) -> None:
    github_output = os.environ.get("GITHUB_OUTPUT")
    line = f"{name}={value}\n"
    if github_output:
        with open(github_output, "a", encoding="utf-8") as handle:
            handle.write(line)
    print(line, end="")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--update-pinned-file", action="store_true", help="Write the newly detected version as pinned (call only after a successful, published build).")
    args = parser.parse_args()

    pinned = load_pinned()
    try:
        latest_iso_date = detect_latest_iso_date()
    except (OSError, RuntimeError) as exc:
        print(f"WARNING: could not check upstream Arch release: {exc}", file=sys.stderr)
        emit_output("changed", "false")
        emit_output("reason", f"check-failed: {exc}")
        return 0

    changed = latest_iso_date != pinned.get("iso_version", "")
    emit_output("changed", "true" if changed else "false")
    emit_output("latest_iso_version", latest_iso_date)
    emit_output("previous_iso_version", pinned.get("iso_version", ""))

    if args.update_pinned_file and changed:
        write_pinned(latest_iso_date, pinned.get("archinstall_version", ""))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
