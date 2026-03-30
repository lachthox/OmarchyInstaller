"""Validation entrypoints for shared plan and compatibility contracts."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from .models import CompatibilityContract, PlanContract


def validate_plan_contract(payload: dict[str, Any]) -> PlanContract:
    """Validate and return strict plan contract."""
    if not isinstance(payload, dict):
        raise TypeError("Plan payload must be a dictionary.")
    try:
        return PlanContract.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(f"Invalid plan contract: {exc}") from exc


def validate_compatibility_contract(payload: dict[str, Any]) -> CompatibilityContract:
    """Validate and return strict compatibility contract."""
    if not isinstance(payload, dict):
        raise TypeError("Compatibility payload must be a dictionary.")
    try:
        return CompatibilityContract.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(f"Invalid compatibility contract: {exc}") from exc

