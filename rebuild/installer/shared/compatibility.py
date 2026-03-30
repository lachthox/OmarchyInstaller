"""Compatibility evaluation helpers for shared rebuild contracts."""

from __future__ import annotations

from dataclasses import dataclass

from .models import CompatibilityContract
from .versioning import is_version_at_least


@dataclass(frozen=True, slots=True)
class CompatibilityResult:
    is_compatible: bool
    reasons: tuple[str, ...]


def evaluate_runtime_compatibility(
    contract: CompatibilityContract,
    *,
    windows_prep_version: str,
    live_runtime_version: str,
    plan_schema_version: str,
) -> CompatibilityResult:
    reasons: list[str] = []

    if plan_schema_version != contract.required_plan_schema_version:
        reasons.append(
            "plan schema mismatch "
            f"(expected {contract.required_plan_schema_version}, got {plan_schema_version})"
        )
    if not is_version_at_least(windows_prep_version, contract.minimum_windows_prep_version):
        reasons.append(
            "windows prep version below minimum "
            f"(minimum {contract.minimum_windows_prep_version}, got {windows_prep_version})"
        )
    if not is_version_at_least(live_runtime_version, contract.minimum_live_runtime_version):
        reasons.append(
            "live runtime version below minimum "
            f"(minimum {contract.minimum_live_runtime_version}, got {live_runtime_version})"
        )

    return CompatibilityResult(is_compatible=not reasons, reasons=tuple(reasons))


def assert_runtime_compatibility(
    contract: CompatibilityContract,
    *,
    windows_prep_version: str,
    live_runtime_version: str,
    plan_schema_version: str,
) -> None:
    result = evaluate_runtime_compatibility(
        contract,
        windows_prep_version=windows_prep_version,
        live_runtime_version=live_runtime_version,
        plan_schema_version=plan_schema_version,
    )
    if result.is_compatible:
        return
    raise ValueError("; ".join(result.reasons))

