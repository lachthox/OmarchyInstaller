from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from rebuild.installer.shared.models import (
    DiskIdentity,
    FreeSpaceRange,
    PartitionIdentity,
    ReleaseManifestContract,
)
from rebuild.installer.shared.validation import validate_plan_contract
from rebuild.installer.shared.versioning import compare_versions, normalize_version


REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = REPO_ROOT / "rebuild" / "assets" / "templates"


def load_plan_template() -> dict[str, object]:
    return json.loads((TEMPLATES / "plan.template.json").read_text(encoding="utf-8"))


def test_shipped_plan_template_passes_production_validator() -> None:
    plan = validate_plan_contract(load_plan_template())

    assert plan.meta.schema_version == "1.0.0"
    assert plan.disk_identity.partition_style == "GPT"
    assert plan.user_choices.filesystem.root_mountpoint == "/mnt/archinstall"


def test_shipped_release_template_passes_production_model() -> None:
    payload = json.loads(
        (TEMPLATES / "release_manifest.template.json").read_text(encoding="utf-8")
    )

    manifest = ReleaseManifestContract.model_validate(payload)

    assert manifest.contracts.plan_schema_version == "1.0.0"


def test_gpt_is_the_only_supported_partition_style() -> None:
    with pytest.raises(ValidationError, match="partition_style"):
        DiskIdentity(
            gpt_disk_guid="disk-guid",
            disk_size_bytes=1024,
            logical_sector_size=512,
            runtime_disk_number=0,
            partition_style="MBR",  # type: ignore[arg-type]
        )


def test_sector_range_size_must_match_inclusive_geometry() -> None:
    with pytest.raises(ValidationError, match="sector span"):
        FreeSpaceRange(
            start_sector=100,
            end_sector=199,
            logical_sector_size=4096,
            size_bytes=100,
        )


def test_partition_uuid_namespaces_are_not_interchangeable() -> None:
    with pytest.raises(ValidationError, match="same partition"):
        PartitionIdentity(
            partition_guid="gpt-guid",
            partuuid="different-partuuid",
            filesystem_uuid="filesystem-uuid",
            filesystem_type="vfat",
            partition_number=1,
            start_sector=1,
            end_sector=1,
            logical_sector_size=512,
            size_bytes=512,
        )


def test_unknown_safety_field_fails_closed() -> None:
    payload = load_plan_template()
    payload["allow_unsafe"] = True

    with pytest.raises(ValueError, match="extra_forbidden"):
        validate_plan_contract(payload)


def test_legacy_schema_requires_regeneration_not_guessing() -> None:
    payload = deepcopy(load_plan_template())
    payload["meta"]["schema_version"] = "0.1.0"  # type: ignore[index]

    with pytest.raises(ValueError, match="intentionally not auto-migrated"):
        validate_plan_contract(payload)


def test_version_comparison_uses_standard_prerelease_ordering() -> None:
    assert compare_versions("1.0.0rc10", "1.0.0rc2") > 0
    assert compare_versions("1.0.0+build.2", "1.0.0+build.1") > 0
    assert compare_versions("1.0.0rc1", "1.0.0") < 0
    assert normalize_version(" 1.0.0-RC1 ") == "1.0.0rc1"


def test_plan_cross_validates_disk_sector_size() -> None:
    payload = load_plan_template()
    payload["efi_identity"]["logical_sector_size"] = 4096  # type: ignore[index]
    payload["efi_identity"]["size_bytes"] = 4294967296  # type: ignore[index]

    with pytest.raises(ValueError, match="disk logical sector size"):
        validate_plan_contract(payload)
