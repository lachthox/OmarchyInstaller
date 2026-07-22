from __future__ import annotations

import json
from pathlib import Path

import pytest

from rebuild.installer.shared.validation import validate_plan_contract


REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = REPO_ROOT / "rebuild" / "assets" / "templates" / "plan.template.json"
GIB = 1024**3


def base_plan() -> dict:
    return json.loads(TEMPLATE.read_text(encoding="utf-8"))


def target_disk_block(*, size_gib: int = 1000, install_gib: int = 200, guid: str = "target-disk-guid") -> dict:
    sector = 512
    start = (1024**2) // sector  # 1 MiB aligned
    span = install_gib * GIB // sector
    end = start + span - 1
    return {
        "disk_identity": {
            "gpt_disk_guid": guid,
            "disk_size_bytes": size_gib * GIB,
            "logical_sector_size": sector,
            "disk_model": "Target NVMe",
            "disk_serial": "TGT123",
            "runtime_disk_number": 1,
            "partition_style": "GPT",
        },
        "install_range": {
            "start_sector": start,
            "end_sector": end,
            "logical_sector_size": sector,
            "size_bytes": (end - start + 1) * sector,
        },
        "mode": "free_space",
        "erases_existing_data": False,
    }


def test_template_still_validates_without_target() -> None:
    plan = validate_plan_contract(base_plan())
    assert plan.linux_install_target is None


def test_separate_disk_plan_validates() -> None:
    payload = base_plan()
    payload["linux_install_target"] = target_disk_block(install_gib=200)
    plan = validate_plan_contract(payload)
    assert plan.linux_install_target is not None
    assert plan.linux_install_target.disk_identity.runtime_disk_number == 1
    assert plan.linux_install_target.mode == "free_space"


def test_separate_disk_target_must_differ_from_windows_disk() -> None:
    payload = base_plan()
    windows_guid = payload["disk_identity"]["gpt_disk_guid"]
    payload["linux_install_target"] = target_disk_block(guid=windows_guid)
    with pytest.raises(ValueError, match="must differ from the Windows disk"):
        validate_plan_contract(payload)


def test_separate_disk_target_below_minimum_rejected() -> None:
    payload = base_plan()
    minimum = payload["user_choices"]["target_free_space"]["minimum_bytes"]
    # Carve a target install range well under the required minimum.
    too_small = target_disk_block(install_gib=10)
    assert too_small["install_range"]["size_bytes"] < minimum
    payload["linux_install_target"] = too_small
    with pytest.raises(ValueError, match="smaller than the requested minimum"):
        validate_plan_contract(payload)


def test_separate_disk_ignores_windows_free_space_size() -> None:
    # With a separate target, the Windows-disk prepared_free_space may be empty.
    payload = base_plan()
    payload["linux_install_target"] = target_disk_block(install_gib=200)
    empty = {
        "start_sector": 100,
        "end_sector": 99,
        "logical_sector_size": payload["prepared_free_space_range"]["logical_sector_size"],
        "size_bytes": 0,
    }
    payload["prepared_free_space_range"] = empty
    plan = validate_plan_contract(payload)
    assert plan.prepared_free_space_range.size_bytes == 0
    assert plan.linux_install_target is not None
