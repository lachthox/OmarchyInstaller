"""Validation entrypoints for shared plan and compatibility contracts."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from .models import CompatibilityContract, PlanContract


SUPPORTED_PLAN_SCHEMA_VERSIONS = {"1.0.0"}


def _plan_schema_version(payload: dict[str, Any]) -> str:
    meta = payload.get("meta")
    if not isinstance(meta, dict):
        return ""
    return str(meta.get("schema_version", "")).strip()


def validate_plan_contract(payload: dict[str, Any]) -> PlanContract:
    """Validate and return strict plan contract."""
    if not isinstance(payload, dict):
        raise TypeError("Plan payload must be a dictionary.")
    schema_version = _plan_schema_version(payload)
    if schema_version not in SUPPORTED_PLAN_SCHEMA_VERSIONS:
        raise ValueError(
            "Unsupported plan schema version "
            f"{schema_version or '<missing>'!r}; regenerate the handoff with a 1.0.0 producer. "
            "Safety-critical 0.1.0 plans are intentionally not auto-migrated."
        )
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

