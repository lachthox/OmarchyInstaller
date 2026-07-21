"""Strict contracts shared by Windows producer and Arch-live consumer."""

from __future__ import annotations

from datetime import datetime
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


PLAN_SCHEMA_VERSION = "1.0.0"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
HOSTNAME_PATTERN = re.compile(
    r"^(?=.{1,253}$)(?!-)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)(?:\.(?!-)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*$"
)
USERNAME_PATTERN = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")


class ContractBaseModel(BaseModel):
    """Strict, immutable base for data crossing a platform boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class VersionedMeta(ContractBaseModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    plan_id: str = Field(min_length=8, max_length=128)
    producer_version: str = Field(min_length=1)
    generated_at_utc: datetime
    build_commit: str = Field(min_length=7, max_length=64)
    release_tag: str = Field(min_length=1, max_length=128)


class DiskIdentity(ContractBaseModel):
    gpt_disk_guid: str = Field(min_length=1)
    disk_size_bytes: int = Field(gt=0)
    logical_sector_size: int
    disk_model: str = Field(default="", max_length=256)
    disk_serial: str = Field(default="", max_length=256)
    partition_style: Literal["GPT"] = "GPT"

    @field_validator("logical_sector_size")
    @classmethod
    def validate_sector_size(cls, value: int) -> int:
        if value not in {512, 4096}:
            raise ValueError("logical_sector_size must be 512 or 4096 bytes")
        return value


class SectorRange(ContractBaseModel):
    start_sector: int = Field(ge=0)
    end_sector: int = Field(ge=0)
    logical_sector_size: int
    size_bytes: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_geometry(self) -> "SectorRange":
        if self.end_sector < self.start_sector:
            raise ValueError("end_sector must be greater than or equal to start_sector")
        if self.logical_sector_size not in {512, 4096}:
            raise ValueError("logical_sector_size must be 512 or 4096 bytes")
        expected = (self.end_sector - self.start_sector + 1) * self.logical_sector_size
        if self.size_bytes != expected:
            raise ValueError(f"size_bytes must equal sector span ({expected} bytes)")
        return self


class PartitionIdentity(SectorRange):
    partition_guid: str = Field(min_length=1, description="GPT partition GUID")
    partuuid: str = Field(min_length=1, description="Linux PARTUUID namespace")
    filesystem_uuid: str = Field(default="", description="Filesystem UUID namespace")
    filesystem_type: str = Field(default="", max_length=32)

    @model_validator(mode="after")
    def validate_gpt_namespaces(self) -> "PartitionIdentity":
        if self.partition_guid.casefold() != self.partuuid.casefold():
            raise ValueError("GPT partition_guid and PARTUUID must identify the same partition")
        return self


class FreeSpaceRange(SectorRange):
    pass


class TargetFreeSpacePolicy(ContractBaseModel):
    minimum_bytes: int = Field(ge=40 * 1024**3)
    alignment_bytes: int = Field(default=1024**2, ge=4096)


class EncryptionSettings(ContractBaseModel):
    enabled: Literal[True] = True
    format: Literal["luks2"] = "luks2"
    mapper_name: str = Field(default="omarchy-root", pattern=r"^[a-zA-Z0-9_.-]{1,64}$")
    allow_discard: bool = False


class BtrfsSubvolume(ContractBaseModel):
    name: str = Field(pattern=r"^@[a-zA-Z0-9_.-]*$")
    mountpoint: str = Field(pattern=r"^/$|^/[a-zA-Z0-9_./-]+$")
    mount_options: tuple[str, ...] = ("compress=zstd", "noatime")


class FilesystemLayout(ContractBaseModel):
    filesystem: Literal["btrfs"] = "btrfs"
    root_mountpoint: Literal["/mnt/archinstall"] = "/mnt/archinstall"
    esp_mountpoint: Literal["/boot"] = "/boot"
    subvolumes: tuple[BtrfsSubvolume, ...]

    @model_validator(mode="after")
    def validate_subvolumes(self) -> "FilesystemLayout":
        names = [item.name for item in self.subvolumes]
        mountpoints = [item.mountpoint for item in self.subvolumes]
        if "@" not in names or "/" not in mountpoints:
            raise ValueError("a root Btrfs subvolume named '@' mounted at '/' is required")
        if len(names) != len(set(names)) or len(mountpoints) != len(set(mountpoints)):
            raise ValueError("Btrfs subvolume names and mountpoints must be unique")
        return self


class BootPolicy(ContractBaseModel):
    mode: Literal["preserve-windows-limine"] = "preserve-windows-limine"
    preserve_windows_loader: Literal[True] = True
    allow_automatic_order_repair: bool = False


class UserChoices(ContractBaseModel):
    hostname: str
    username: str
    locale: str = Field(pattern=r"^[A-Za-z]{2}_[A-Za-z]{2}\.UTF-8$")
    timezone: str = Field(pattern=r"^[A-Za-z0-9_+.-]+(?:/[A-Za-z0-9_+.-]+)+$")
    keyboard_layout: str = Field(pattern=r"^[a-z0-9_-]{2,32}$")
    target_free_space: TargetFreeSpacePolicy
    encryption: EncryptionSettings
    filesystem: FilesystemLayout
    boot_policy: BootPolicy

    @field_validator("hostname")
    @classmethod
    def validate_hostname(cls, value: str) -> str:
        normalized = value.casefold()
        if not HOSTNAME_PATTERN.fullmatch(normalized):
            raise ValueError("hostname is not RFC-compatible")
        return normalized

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        if not USERNAME_PATTERN.fullmatch(value):
            raise ValueError("username must be a safe Linux account name")
        return value


class NetworkProfile(ContractBaseModel):
    mode: Literal["ethernet", "wifi", "interactive", "offline"] = "interactive"
    ssid: str = ""
    wifi_security: Literal["", "open", "wpa2", "wpa3"] = ""
    interface_name: str = ""
    credentials_on_removable_media: Literal[False] = False

    @model_validator(mode="after")
    def validate_wifi_fields(self) -> "NetworkProfile":
        if self.mode == "wifi" and not self.ssid:
            raise ValueError("ssid is required when mode=wifi")
        if self.mode != "wifi" and self.ssid:
            raise ValueError("ssid must be empty unless mode=wifi")
        return self


class OmarchyAssumptions(ContractBaseModel):
    handoff_mode: Literal["normal-user-interactive"] = "normal-user-interactive"
    bootstrap_url: str = Field(min_length=8)
    upstream_version: str = Field(min_length=1)
    expected_sha256: str
    automatic_retry: Literal[False] = False

    @field_validator("expected_sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        normalized = value.casefold()
        if not SHA256_PATTERN.fullmatch(normalized):
            raise ValueError("expected_sha256 must be a lowercase SHA256 digest")
        return normalized


class ArtifactProvenance(ContractBaseModel):
    release_tag: str = Field(min_length=1)
    build_commit: str = Field(min_length=7, max_length=64)
    workflow_run_id: str = Field(min_length=1)
    producer_version: str = Field(min_length=1)
    iso_name: str = Field(min_length=1)
    iso_sha256: str
    release_manifest_sha256: str

    @field_validator("iso_sha256", "release_manifest_sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        normalized = value.casefold()
        if not SHA256_PATTERN.fullmatch(normalized):
            raise ValueError("artifact hashes must be lowercase SHA256 digests")
        return normalized


class CompatibilityContract(ContractBaseModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    minimum_windows_prep_version: str
    minimum_live_runtime_version: str
    required_plan_schema_version: Literal["1.0.0"] = "1.0.0"
    bootstrap_expectation: Literal["post-install-only"] = "post-install-only"
    ventoy_handoff_path: Literal["omarchy/plan.json"] = "omarchy/plan.json"


class PlanContract(ContractBaseModel):
    meta: VersionedMeta
    provenance: ArtifactProvenance
    disk_identity: DiskIdentity
    efi_identity: PartitionIdentity
    windows_partition_identity: PartitionIdentity
    prepared_free_space_range: FreeSpaceRange
    user_choices: UserChoices
    network: NetworkProfile
    omarchy_assumptions: OmarchyAssumptions
    compatibility: CompatibilityContract

    @model_validator(mode="after")
    def validate_cross_contract_invariants(self) -> "PlanContract":
        sector_size = self.disk_identity.logical_sector_size
        ranges = (
            self.efi_identity,
            self.windows_partition_identity,
            self.prepared_free_space_range,
        )
        if any(item.logical_sector_size != sector_size for item in ranges):
            raise ValueError("all sector ranges must use the disk logical sector size")
        if self.prepared_free_space_range.size_bytes < self.user_choices.target_free_space.minimum_bytes:
            raise ValueError("prepared free space is smaller than the requested minimum")
        if self.meta.release_tag != self.provenance.release_tag:
            raise ValueError("metadata and provenance release tags must match")
        if self.meta.build_commit != self.provenance.build_commit:
            raise ValueError("metadata and provenance build commits must match")
        return self


class ReleaseBuildIdentity(ContractBaseModel):
    git_commit: str = Field(min_length=7, max_length=64)
    github_run_id: str = Field(min_length=1)
    github_ref: str = Field(min_length=1)


class ReleaseArtifact(ContractBaseModel):
    name: str = Field(min_length=1)
    sha256: str
    size_bytes: int = Field(gt=0)

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        normalized = value.casefold()
        if not SHA256_PATTERN.fullmatch(normalized):
            raise ValueError("sha256 must be a lowercase SHA256 digest")
        return normalized


class ReleaseArtifacts(ContractBaseModel):
    iso: ReleaseArtifact
    exe: ReleaseArtifact
    checksums_file: str = "sha256sums.txt"
    release_manifest_file: str = "release_manifest.json"
    compatibility_manifest_file: str = "compatibility_manifest.json"


class ReleaseContracts(ContractBaseModel):
    plan_schema_version: Literal["1.0.0"] = "1.0.0"
    compatibility_schema_version: Literal["1.0.0"] = "1.0.0"
    iso_pipeline_manifest_schema: str = Field(min_length=1)
    exe_pipeline_manifest_schema: str = Field(min_length=1)


class ReleaseManifestContract(ContractBaseModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    generated_at_utc: datetime
    tag: str = Field(min_length=1)
    build: ReleaseBuildIdentity
    artifacts: ReleaseArtifacts
    contracts: ReleaseContracts
