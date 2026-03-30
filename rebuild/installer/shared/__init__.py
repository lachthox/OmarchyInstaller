"""Shared models, validation, and versioning contracts."""

from .compatibility import CompatibilityResult, assert_runtime_compatibility, evaluate_runtime_compatibility
from .models import (
    PLAN_SCHEMA_VERSION,
    CompatibilityContract,
    DiskIdentity,
    FreeSpaceRange,
    NetworkProfile,
    PartitionIdentity,
    PlanContract,
    VersionedMeta,
)
from .validation import validate_compatibility_contract, validate_plan_contract
from .versioning import compare_versions, is_version_at_least, normalize_version, parse_version

__all__ = [
    "PLAN_SCHEMA_VERSION",
    "CompatibilityContract",
    "CompatibilityResult",
    "DiskIdentity",
    "FreeSpaceRange",
    "NetworkProfile",
    "PartitionIdentity",
    "PlanContract",
    "VersionedMeta",
    "assert_runtime_compatibility",
    "compare_versions",
    "evaluate_runtime_compatibility",
    "is_version_at_least",
    "normalize_version",
    "parse_version",
    "validate_compatibility_contract",
    "validate_plan_contract",
]

