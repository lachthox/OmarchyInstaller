"""Installed-system modules for first boot and health guardrails."""

from .firstboot import (
    DEFAULT_FIRSTBOOT_ATTEMPT_LOG,
    DEFAULT_FIRSTBOOT_COMPLETION_MARKER,
    DEFAULT_BOOTSTRAP_REPO,
    DEFAULT_BOOTSTRAP_ROOT,
    DEFAULT_BOOTSTRAP_URL,
    DEFAULT_INSTALL_SUCCESS_MARKER,
    DEFAULT_OMARCHY_INSTALL_COMMAND,
    FirstBootExecutionResult,
    FirstBootPolicyError,
    FirstBootRuntimeContext,
    assert_firstboot_ready,
    detect_runtime_context,
    evaluate_firstboot_timing_policy,
    run_firstboot_handoff,
)
from .post_install import (
    BootstrapContract,
    BootstrapHealthResult,
    PostInstallNormalizationError,
    PostInstallNormalizationResult,
    build_bootstrap_contract,
    evaluate_bootstrap_health,
    normalize_boot_policy,
)
from .target_finalize import (
    TargetFinalizationError,
    TargetFinalizationResult,
    TargetMachineState,
    deploy_target_assets,
    finalize_target_system,
    validate_target_root,
)


def __getattr__(name: str):
    if name == "boot_guardian":
        from . import boot_guardian as module

        return module
    raise AttributeError(name)

__all__ = [
    "DEFAULT_FIRSTBOOT_ATTEMPT_LOG",
    "DEFAULT_FIRSTBOOT_COMPLETION_MARKER",
    "DEFAULT_BOOTSTRAP_REPO",
    "DEFAULT_BOOTSTRAP_ROOT",
    "DEFAULT_BOOTSTRAP_URL",
    "DEFAULT_INSTALL_SUCCESS_MARKER",
    "DEFAULT_OMARCHY_INSTALL_COMMAND",
    "BootstrapContract",
    "BootstrapHealthResult",
    "FirstBootExecutionResult",
    "FirstBootPolicyError",
    "FirstBootRuntimeContext",
    "assert_firstboot_ready",
    "build_bootstrap_contract",
    "detect_runtime_context",
    "evaluate_bootstrap_health",
    "evaluate_firstboot_timing_policy",
    "normalize_boot_policy",
    "PostInstallNormalizationError",
    "PostInstallNormalizationResult",
    "run_firstboot_handoff",
    "TargetFinalizationError",
    "TargetFinalizationResult",
    "TargetMachineState",
    "deploy_target_assets",
    "finalize_target_system",
    "validate_target_root",
]
