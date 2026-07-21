"""Strict compatibility contract for the pinned archinstall 4.4 release."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ...shared import PlanContract


ARCHINSTALL_VERSION = "4.4"
ARCHINSTALL_MOUNTPOINT = "/mnt/archinstall"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class PreMountedDiskConfig(StrictModel):
    config_type: Literal["pre_mounted_config"] = "pre_mounted_config"
    mountpoint: Literal["/mnt/archinstall"] = "/mnt/archinstall"


class BootloaderConfig(StrictModel):
    bootloader: Literal["Limine"] = "Limine"
    uki: Literal[False] = False
    removable: Literal[False] = False


class LocaleConfig(StrictModel):
    kb_layout: str = Field(min_length=2)
    sys_lang: str = Field(pattern=r"^[A-Za-z]{2}_[A-Za-z]{2}\.UTF-8$")
    sys_enc: Literal["UTF-8"] = "UTF-8"
    console_font: Literal["default8x16"] = "default8x16"


class NetworkConfig(StrictModel):
    type: Literal["nm"] = "nm"


class Archinstall44Config(StrictModel):
    version: Literal["4.4"] = "4.4"
    script: Literal["guided"] = "guided"
    archinstall_language: Literal["English"] = Field(default="English", alias="archinstall-language")
    disk_config: PreMountedDiskConfig
    bootloader_config: BootloaderConfig
    hostname: str
    kernels: tuple[Literal["linux"], ...] = ("linux",)
    locale_config: LocaleConfig
    network_config: NetworkConfig
    ntp: Literal[True] = True
    packages: tuple[str, ...] = ()
    services: tuple[Literal["NetworkManager"], ...] = ("NetworkManager",)
    timezone: str


class ArchinstallUserCredential(StrictModel):
    username: str
    enc_password: str = Field(min_length=20)
    sudo: Literal[True] = True

    @model_validator(mode="after")
    def password_must_be_hash(self) -> "ArchinstallUserCredential":
        if not self.enc_password.startswith("$"):
            raise ValueError("archinstall user password must be a crypt hash, not plaintext")
        return self


class Archinstall44Credentials(StrictModel):
    users: tuple[ArchinstallUserCredential, ...]

    @model_validator(mode="after")
    def require_one_sudo_user(self) -> "Archinstall44Credentials":
        if len(self.users) != 1:
            raise ValueError("exactly one planned sudo user is required")
        return self


def build_archinstall_config(plan: PlanContract) -> Archinstall44Config:
    return Archinstall44Config.model_validate(
        {
            "version": ARCHINSTALL_VERSION,
            "script": "guided",
            "archinstall-language": "English",
            "disk_config": {
                "config_type": "pre_mounted_config",
                "mountpoint": plan.user_choices.filesystem.root_mountpoint,
            },
            "bootloader_config": {"bootloader": "Limine", "uki": False, "removable": False},
            "hostname": plan.user_choices.hostname,
            "kernels": ("linux",),
            "locale_config": {
                "kb_layout": plan.user_choices.keyboard_layout,
                "sys_lang": plan.user_choices.locale,
                "sys_enc": "UTF-8",
                "console_font": "default8x16",
            },
            "network_config": {"type": "nm"},
            "ntp": True,
            "packages": (
                "btrfs-progs",
                "networkmanager",
                "sudo",
                "git",
                "curl",
                "base-devel",
            ),
            "services": ("NetworkManager",),
            "timezone": plan.user_choices.timezone,
        }
    )


def build_archinstall_credentials(
    plan: PlanContract, *, user_password_hash: str
) -> Archinstall44Credentials:
    return Archinstall44Credentials(
        users=(
            ArchinstallUserCredential(
                username=plan.user_choices.username,
                enc_password=user_password_hash,
                sudo=True,
            ),
        )
    )


def validate_archinstall_files(config_path: Path, credentials_path: Path) -> None:
    Archinstall44Config.model_validate_json(config_path.read_text(encoding="utf-8"))
    Archinstall44Credentials.model_validate_json(credentials_path.read_text(encoding="utf-8"))
