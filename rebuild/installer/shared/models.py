"""Shared Pydantic models used by Windows producer and Arch consumer."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


PLAN_SCHEMA_VERSION = "0.1.0"


class ContractBaseModel(BaseModel):
    """Base model with strict validation and immutable fields."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class VersionedMeta(ContractBaseModel):
    schema_version: str = Field(default=PLAN_SCHEMA_VERSION)
    producer_version: str
    generated_at_utc: str
    build_commit: str = ""
    release_tag: str = ""


class DiskIdentity(ContractBaseModel):
    disk_serial: str = Field(min_length=1)
    disk_model: str = Field(min_length=1)
    disk_size_bytes: int = Field(gt=0)
    gpt_disk_guid: str = Field(min_length=1)
    partition_style: Literal["GPT", "MBR"]


class PartitionIdentity(ContractBaseModel):
    partition_guid: str = Field(min_length=1)
    partuuid: str = Field(default="")
    filesystem: str = Field(default="")
    start_sector: int = Field(ge=0)
    end_sector: int = Field(ge=0)
    size_bytes: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_bounds(self) -> "PartitionIdentity":
        if self.end_sector < self.start_sector:
            raise ValueError("end_sector must be greater than or equal to start_sector")
        return self


class FreeSpaceRange(ContractBaseModel):
    start_sector: int = Field(ge=0)
    end_sector: int = Field(ge=0)
    size_bytes: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_bounds(self) -> "FreeSpaceRange":
        if self.end_sector < self.start_sector:
            raise ValueError("end_sector must be greater than or equal to start_sector")
        return self


class NetworkProfile(ContractBaseModel):
    mode: Literal["ethernet", "wifi", "offline"] = "offline"
    ssid: str = ""
    wifi_security: Literal["", "open", "wpa2", "wpa3"] = ""
    interface_name: str = ""
    has_credentials: bool = False

    @model_validator(mode="after")
    def validate_wifi_fields(self) -> "NetworkProfile":
        if self.mode == "wifi" and not self.ssid:
            raise ValueError("ssid is required when mode=wifi")
        if self.mode != "wifi" and self.ssid:
            raise ValueError("ssid must be empty unless mode=wifi")
        return self


class CompatibilityContract(ContractBaseModel):
    schema_version: str
    minimum_windows_prep_version: str
    minimum_live_runtime_version: str
    required_plan_schema_version: str = PLAN_SCHEMA_VERSION
    bootstrap_expectation: Literal["post-install-only"] = "post-install-only"
    ventoy_handoff_path: str = "omarchy/plan.json"


class PlanContract(ContractBaseModel):
    meta: VersionedMeta
    disk_identity: DiskIdentity
    efi_identity: PartitionIdentity
    windows_partition_identity: PartitionIdentity
    prepared_free_space_range: FreeSpaceRange
    user_choices: dict[str, Any]
    network: NetworkProfile | None = None
    omarchy_assumptions: dict[str, Any]
    compatibility: CompatibilityContract

