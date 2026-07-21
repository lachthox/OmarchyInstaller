"""Validate generated files with the pinned upstream archinstall parser."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
from pathlib import Path
from typing import Any


PINNED_ARCHINSTALL_VERSION = "4.4"


def validate_with_upstream(config_path: Path, credentials_path: Path) -> dict[str, Any]:
    try:
        installed_version = importlib.metadata.version("archinstall")
        from archinstall.lib.args import ArchConfig, Arguments  # type: ignore[import-not-found]
        from archinstall.lib.models.device import DiskLayoutType  # type: ignore[import-not-found]
    except (ImportError, importlib.metadata.PackageNotFoundError) as exc:
        raise RuntimeError("Pinned archinstall 4.4 must be installed for upstream validation") from exc
    if installed_version != PINNED_ARCHINSTALL_VERSION:
        raise RuntimeError(
            f"Expected archinstall {PINNED_ARCHINSTALL_VERSION}, found {installed_version}"
        )
    config = json.loads(config_path.read_text(encoding="utf-8"))
    credentials = json.loads(credentials_path.read_text(encoding="utf-8"))
    parsed = ArchConfig.from_config({**config, **credentials}, Arguments())
    if parsed.disk_config is None or parsed.disk_config.config_type != DiskLayoutType.Pre_mount:
        raise RuntimeError("Upstream parser did not accept pre_mounted_config")
    if str(parsed.disk_config.mountpoint) != "/mnt/archinstall":
        raise RuntimeError("Upstream parser changed the pre-mounted mountpoint")
    if parsed.auth_config is None or len(parsed.auth_config.users) != 1:
        raise RuntimeError("Upstream parser did not accept exactly one user credential")
    user = parsed.auth_config.users[0]
    if not user.sudo or not user.password.enc_password:
        raise RuntimeError("Upstream parser rejected hashed sudo-user credentials")
    return {
        "archinstall_version": installed_version,
        "config_type": parsed.disk_config.config_type.value,
        "mountpoint": str(parsed.disk_config.mountpoint),
        "username": user.username,
        "sudo": user.sudo,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--credentials", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(validate_with_upstream(args.config, args.credentials), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
