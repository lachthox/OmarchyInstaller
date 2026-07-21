"""Installed-system first-login and health-guardian modules."""
from .first_login import (
    FirstLoginContext,
    FirstLoginError,
    FirstLoginResult,
    ReleasePairing,
    run_first_login,
)
from .target_finalize import (
    TargetFinalizationError,
    TargetFinalizationResult,
    TargetMachineState,
    deploy_target_assets,
    finalize_target_system,
    validate_target_root,
)
from .boot_guardian import record_boot_policy_completion


def __getattr__(name: str):
    if name == "boot_guardian":
        from . import boot_guardian as module

        return module
    raise AttributeError(name)

__all__ = [
    "FirstLoginContext",
    "FirstLoginError",
    "FirstLoginResult",
    "ReleasePairing",
    "run_first_login",
    "TargetFinalizationError",
    "TargetFinalizationResult",
    "TargetMachineState",
    "deploy_target_assets",
    "finalize_target_system",
    "validate_target_root",
    "record_boot_policy_completion",
]
