from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from rebuild.installer.platforms.linux_live.archinstall_contract import (
    ARCHINSTALL_VERSION,
    Archinstall44Credentials,
    build_archinstall_config,
    build_archinstall_credentials,
    validate_archinstall_files,
)
from rebuild.installer.shared import validate_plan_contract
from rebuild.installer.shared.models import PlanContract
from rebuild.tools.validate_archinstall_upstream import validate_with_upstream


WORKSPACE = Path(__file__).resolve().parents[2]


def plan() -> PlanContract:
    payload = json.loads(
        (WORKSPACE / "rebuild" / "assets" / "templates" / "plan.template.json").read_text()
    )
    return validate_plan_contract(payload)


def test_pinned_44_config_is_premounted_and_not_internal_plan() -> None:
    config = build_archinstall_config(plan()).model_dump(mode="json", by_alias=True, exclude_none=True)
    assert config["version"] == ARCHINSTALL_VERSION == "4.4"
    assert config["disk_config"] == {
        "config_type": "pre_mounted_config",
        "mountpoint": "/mnt/archinstall",
    }
    # archinstall 4.4's pre-mounted-config bootloader auto-detection cannot
    # resolve a LUKS2-encrypted root (it only inspects a partition's own
    # lsblk mountpoints, never a dm-crypt mapped child's), so `add_bootloader`
    # always raises "Could not detect root" in this mode. Its own --config
    # parser also rejects the enum's "No bootloader" sentinel as an invalid
    # *input* value, so the field is omitted entirely (not merely set to
    # that sentinel) -- only an absent key reaches guided.py's runtime check
    # as None and skips add_bootloader; the install engine installs Limine
    # itself afterward.
    assert "bootloader_config" not in config
    assert "disk_identity" not in config
    assert "prepared_free_space_range" not in config
    assert "encryption_password" not in json.dumps(config)
    assert set(config["packages"]) >= {
        "btrfs-progs",
        "networkmanager",
        "sudo",
        "git",
        "curl",
        "base-devel",
        "limine",
        "efibootmgr",
    }


def test_credentials_are_separate_hashed_and_strict() -> None:
    credentials = build_archinstall_credentials(
        plan(), user_password_hash="$6$test$abcdefghijklmnopqrstuvwxyz0123456789"
    )
    assert credentials.users[0].username == "omarchy"
    with pytest.raises(ValidationError, match="crypt hash"):
        build_archinstall_credentials(plan(), user_password_hash="plaintext-password-is-long")
    with pytest.raises(ValidationError):
        Archinstall44Credentials.model_validate(
            {"users": [], "unexpected": "not accepted"}
        )


def test_serialized_files_pass_same_semantic_models(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    credentials_path = tmp_path / "credentials.json"
    config_path.write_text(
        build_archinstall_config(plan()).model_dump_json(by_alias=True, exclude_none=True), encoding="utf-8"
    )
    credentials_path.write_text(
        build_archinstall_credentials(
            plan(), user_password_hash="$6$test$abcdefghijklmnopqrstuvwxyz0123456789"
        ).model_dump_json(),
        encoding="utf-8",
    )
    validate_archinstall_files(config_path, credentials_path)


def test_generated_files_are_consumed_by_pinned_upstream_parser(tmp_path: Path) -> None:
    pytest.importorskip("archinstall")
    config_path = tmp_path / "config.json"
    credentials_path = tmp_path / "credentials.json"
    config_path.write_text(
        build_archinstall_config(plan()).model_dump_json(by_alias=True, exclude_none=True), encoding="utf-8"
    )
    credentials_path.write_text(
        build_archinstall_credentials(
            plan(), user_password_hash="$6$test$abcdefghijklmnopqrstuvwxyz0123456789"
        ).model_dump_json(),
        encoding="utf-8",
    )
    result = validate_with_upstream(config_path, credentials_path)
    assert result == {
        "archinstall_version": "4.4",
        "config_type": "pre_mounted_config",
        "mountpoint": "/mnt/archinstall",
        "username": "omarchy",
        "sudo": True,
    }
