"""Textual screen scaffolding."""

from __future__ import annotations


WINDOWS_PREP_SCREEN_CONTRACT: tuple[str, ...] = (
    "welcome",
    "compatibility",
    "backup",
    "partition_prep",
    "ventoy_usb",
    "secure_boot",
    "network",
    "summary",
    "confirm",
    "error_handling",
)

LIVE_BOOTSTRAP_SCREEN_CONTRACT: tuple[str, ...] = (
    "preflight",
    "network",
    "install_progress",
    "finalize",
    "error",
)


def bootstrap_screen_ids() -> list[str]:
    """Return the ordered Arch live bootstrap screen identifiers."""
    if len(set(LIVE_BOOTSTRAP_SCREEN_CONTRACT)) != len(LIVE_BOOTSTRAP_SCREEN_CONTRACT):
        raise ValueError("Bootstrap screen contract contains duplicate identifiers.")
    return list(LIVE_BOOTSTRAP_SCREEN_CONTRACT)


def windows_prep_screen_ids() -> list[str]:
    """Return the ordered Windows prep screen identifiers."""
    if len(set(WINDOWS_PREP_SCREEN_CONTRACT)) != len(WINDOWS_PREP_SCREEN_CONTRACT):
        raise ValueError("Windows prep screen contract contains duplicate identifiers.")
    return list(WINDOWS_PREP_SCREEN_CONTRACT)

