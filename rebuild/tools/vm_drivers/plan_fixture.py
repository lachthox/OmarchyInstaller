"""Build a real, schema-validated handoff plan + authenticated manifest for VM testing.

This does not mock the Windows-side producer's *output shape* — it constructs the
exact PlanContract/manifest payload a real Windows prep run would hand off, using
the project's own production Pydantic models, so the Linux live installer consumes
it through the identical discovery/validation code path as a real user.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sys
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from rebuild.installer.shared import PlanContract, validate_plan_contract  # noqa: E402
from rebuild.installer.ui.live_state import confirmation_token  # noqa: E402


# Low, easily-satisfied compatibility floors so the ISO's default
# `--runtime-version 0.1.0-dev` entrypoint (unmodified) clears the gate.
MINIMUM_COMPAT_VERSION = "0.0.1"

TEST_HOSTNAME = "omarchy-vmtest"
TEST_USERNAME = "omarchy"
TEST_LOCALE = "en_US.UTF-8"
TEST_TIMEZONE = "UTC/UTC" if False else "Etc/UTC"
TEST_KEYBOARD_LAYOUT = "us"


@dataclass(frozen=True, slots=True)
class DiskGeometry:
    gpt_disk_guid: str
    disk_size_bytes: int
    logical_sector_size: int
    disk_model: str
    disk_serial: str
    esp_start_sector: int
    esp_end_sector: int
    esp_size_bytes: int
    esp_partition_guid: str
    esp_filesystem_uuid: str
    windows_start_sector: int
    windows_end_sector: int
    windows_size_bytes: int
    windows_partition_guid: str
    windows_filesystem_uuid: str
    free_start_sector: int
    free_end_sector: int
    free_size_bytes: int


def _placeholder_sha256(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def build_plan_payload(
    *,
    geometry: DiskGeometry,
    release_tag: str,
    build_commit: str,
    workflow_run_id: str,
    producer_version: str,
    iso_name: str,
    iso_sha256: str,
    bootstrap_url: str,
    bootstrap_sha256: str,
    bootstrap_upstream_version: str,
) -> dict[str, Any]:
    plan_id = uuid.uuid4().hex
    generated_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "meta": {
            "schema_version": "1.0.0",
            "plan_id": plan_id,
            "producer_version": producer_version,
            "generated_at_utc": generated_at,
            "build_commit": build_commit,
            "release_tag": release_tag,
        },
        "provenance": {
            "release_tag": release_tag,
            "build_commit": build_commit,
            "workflow_run_id": workflow_run_id,
            "producer_version": producer_version,
            "iso_name": iso_name,
            "iso_sha256": iso_sha256,
            "release_manifest_sha256": _placeholder_sha256(f"release-manifest:{release_tag}:{build_commit}"),
        },
        "disk_identity": {
            "gpt_disk_guid": geometry.gpt_disk_guid,
            "disk_size_bytes": geometry.disk_size_bytes,
            "logical_sector_size": geometry.logical_sector_size,
            "disk_model": geometry.disk_model,
            "disk_serial": geometry.disk_serial,
            "runtime_disk_number": 0,
            "partition_style": "GPT",
        },
        "efi_identity": {
            "start_sector": geometry.esp_start_sector,
            "end_sector": geometry.esp_end_sector,
            "logical_sector_size": geometry.logical_sector_size,
            "size_bytes": geometry.esp_size_bytes,
            "partition_guid": geometry.esp_partition_guid,
            "partuuid": geometry.esp_partition_guid,
            "filesystem_uuid": geometry.esp_filesystem_uuid,
            "filesystem_type": "vfat",
            "partition_number": 1,
        },
        "windows_partition_identity": {
            "start_sector": geometry.windows_start_sector,
            "end_sector": geometry.windows_end_sector,
            "logical_sector_size": geometry.logical_sector_size,
            "size_bytes": geometry.windows_size_bytes,
            "partition_guid": geometry.windows_partition_guid,
            "partuuid": geometry.windows_partition_guid,
            "filesystem_uuid": geometry.windows_filesystem_uuid,
            "filesystem_type": "ntfs",
            "partition_number": 2,
        },
        "prepared_free_space_range": {
            "start_sector": geometry.free_start_sector,
            "end_sector": geometry.free_end_sector,
            "logical_sector_size": geometry.logical_sector_size,
            "size_bytes": geometry.free_size_bytes,
        },
        "user_choices": {
            "hostname": TEST_HOSTNAME,
            "username": TEST_USERNAME,
            "locale": TEST_LOCALE,
            "timezone": TEST_TIMEZONE,
            "keyboard_layout": TEST_KEYBOARD_LAYOUT,
            "target_free_space": {
                "minimum_bytes": geometry.free_size_bytes,
                "alignment_bytes": 1048576,
            },
            "encryption": {
                "enabled": True,
                "format": "luks2",
                "mapper_name": "omarchy-root",
                "allow_discard": False,
            },
            "filesystem": {
                "filesystem": "btrfs",
                "root_mountpoint": "/mnt/archinstall",
                "esp_mountpoint": "/boot",
                "subvolumes": [
                    {"name": "@", "mountpoint": "/", "mount_options": ["compress=zstd", "noatime"]},
                    {"name": "@home", "mountpoint": "/home", "mount_options": ["compress=zstd", "noatime"]},
                ],
            },
            "boot_policy": {
                "mode": "preserve-windows-limine",
                "preserve_windows_loader": True,
                "allow_automatic_order_repair": False,
            },
        },
        "network": {
            "mode": "interactive",
            "ssid": "",
            "wifi_security": "",
            "interface_name": "",
            "credentials_on_removable_media": False,
        },
        "omarchy_assumptions": {
            "handoff_mode": "normal-user-interactive",
            "bootstrap_url": bootstrap_url,
            "upstream_version": bootstrap_upstream_version,
            "expected_sha256": bootstrap_sha256,
            "automatic_retry": False,
        },
        "compatibility": {
            "schema_version": "1.0.0",
            "minimum_windows_prep_version": MINIMUM_COMPAT_VERSION,
            "minimum_live_runtime_version": MINIMUM_COMPAT_VERSION,
            "required_plan_schema_version": "1.0.0",
            "bootstrap_expectation": "post-install-only",
            "ventoy_handoff_path": "omarchy/plan.json",
        },
    }


def validated_plan(payload: dict[str, Any]) -> PlanContract:
    return validate_plan_contract(payload)


def build_manifest(
    *,
    plan: PlanContract,
    plan_path: Path,
    iso_path: Path,
    integrity_key: bytes,
) -> dict[str, Any]:
    unsigned = {
        "schema_version": "1.0.0",
        "file_sha256": {
            "plan": hashlib.sha256(plan_path.read_bytes()).hexdigest(),
            "iso": hashlib.sha256(iso_path.read_bytes()).hexdigest(),
        },
        "release_tag": plan.provenance.release_tag,
        "build_commit": plan.provenance.build_commit,
        "workflow_run_id": plan.provenance.workflow_run_id,
        "producer_version": plan.provenance.producer_version,
        "plan_schema_version": plan.meta.schema_version,
        "disk_guid": plan.disk_identity.gpt_disk_guid,
        "partition_guids": {
            "efi": plan.efi_identity.partition_guid,
            "windows": plan.windows_partition_identity.partition_guid,
        },
    }
    canonical = json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
    digest = hmac.new(integrity_key, canonical, hashlib.sha256).hexdigest()
    return {**unsigned, "hmac_sha256": digest}


def new_integrity_key() -> bytes:
    return secrets.token_bytes(32)


def write_plan_and_manifest(
    *,
    ventoy_root: Path,
    geometry: DiskGeometry,
    release_tag: str,
    build_commit: str,
    workflow_run_id: str,
    producer_version: str,
    iso_name: str,
    iso_sha256: str,
    iso_path_on_ventoy: Path,
    bootstrap_url: str,
    bootstrap_sha256: str,
    bootstrap_upstream_version: str,
) -> tuple[bytes, dict[str, Any]]:
    """Write omarchy/plan.json + omarchy/handoff-manifest.json under ventoy_root.

    Returns (integrity_key, plan_payload) for the caller to drive the TUI with.
    """
    omarchy_dir = ventoy_root / "omarchy"
    omarchy_dir.mkdir(parents=True, exist_ok=True)

    payload = build_plan_payload(
        geometry=geometry,
        release_tag=release_tag,
        build_commit=build_commit,
        workflow_run_id=workflow_run_id,
        producer_version=producer_version,
        iso_name=iso_name,
        iso_sha256=iso_sha256,
        bootstrap_url=bootstrap_url,
        bootstrap_sha256=bootstrap_sha256,
        bootstrap_upstream_version=bootstrap_upstream_version,
    )
    plan = validated_plan(payload)
    plan_path = omarchy_dir / "plan.json"
    plan_path.write_text(json.dumps(plan.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")

    integrity_key = new_integrity_key()
    manifest = build_manifest(
        plan=plan,
        plan_path=plan_path,
        iso_path=iso_path_on_ventoy,
        integrity_key=integrity_key,
    )
    manifest_path = omarchy_dir / "handoff-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    return integrity_key, payload


__all__ = [
    "DiskGeometry",
    "build_plan_payload",
    "validated_plan",
    "build_manifest",
    "new_integrity_key",
    "write_plan_and_manifest",
    "confirmation_token",
]
