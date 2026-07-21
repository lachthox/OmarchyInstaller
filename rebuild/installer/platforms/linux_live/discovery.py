"""Ventoy handoff discovery and anti-stale plan validation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
import json
from pathlib import Path
from typing import Any, Iterable, Sequence

from ...shared import PLAN_SCHEMA_VERSION, PlanContract, assert_runtime_compatibility, validate_plan_contract


DEFAULT_HANDOFF_RELATIVE_PATH = "omarchy/plan.json"
DEFAULT_MOUNT_BASES = (Path("/run/media"), Path("/media"), Path("/mnt"))
DEFAULT_RUNTIME_METADATA_PATH = Path("/opt/omarchy-setup/build-metadata.json")


class HandoffDiscoveryError(RuntimeError):
    """Raised when no safe handoff source can be discovered and validated."""


@dataclass(frozen=True, slots=True)
class HandoffValidationContext:
    live_runtime_version: str
    expected_plan_schema_version: str = PLAN_SCHEMA_VERSION
    expected_handoff_relative_path: str = DEFAULT_HANDOFF_RELATIVE_PATH
    expected_release_tag: str = ""
    expected_build_commit: str = ""
    max_plan_age_hours: int | None = None


@dataclass(frozen=True, slots=True)
class HandoffDiscoveryResult:
    source_root: str
    plan_path: str
    discovered_relative_path: str
    plan_mtime_utc: str
    plan: PlanContract

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["plan"] = self.plan.model_dump()
        return payload


def _normalize_relative_path(path_value: str) -> str:
    return Path(path_value).as_posix().lstrip("/")


def _iter_default_mount_roots() -> Iterable[Path]:
    for base in DEFAULT_MOUNT_BASES:
        if not base.exists() or not base.is_dir():
            continue
        for child in sorted(base.iterdir()):
            if child.is_dir():
                yield child


def discover_handoff_sources(search_roots: Sequence[str | Path] | None = None) -> list[str]:
    """Return candidate handoff roots that contain omarchy/plan.json."""
    relative = _normalize_relative_path(DEFAULT_HANDOFF_RELATIVE_PATH)
    roots: list[Path] = []
    if search_roots:
        for raw in search_roots:
            root = Path(raw).expanduser()
            roots.append(root)
    else:
        roots.extend(_iter_default_mount_roots())

    discovered: list[str] = []
    seen: set[str] = set()
    for root in roots:
        plan_path = root / relative
        if not plan_path.exists() or not plan_path.is_file():
            continue
        key = str(root.resolve())
        if key in seen:
            continue
        seen.add(key)
        discovered.append(key)
    return discovered


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise HandoffDiscoveryError(f"Failed to read handoff plan: {path} ({exc})") from exc
    except json.JSONDecodeError as exc:
        raise HandoffDiscoveryError(f"Invalid JSON in handoff plan: {path} ({exc})") from exc
    if not isinstance(payload, dict):
        raise HandoffDiscoveryError(f"Handoff plan payload must be an object: {path}")
    return payload


def _mtime_utc(path: Path) -> str:
    timestamp = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    return timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_utc(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise HandoffDiscoveryError(f"Invalid UTC timestamp in plan meta: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _apply_anti_stale_validation(
    *,
    plan: PlanContract,
    context: HandoffValidationContext,
    source_root: Path,
    plan_path: Path,
) -> None:
    if plan.meta.schema_version != context.expected_plan_schema_version:
        raise HandoffDiscoveryError(
            "Plan schema version mismatch "
            f"(expected {context.expected_plan_schema_version}, got {plan.meta.schema_version})."
        )

    assert_runtime_compatibility(
        plan.compatibility,
        windows_prep_version=plan.meta.producer_version,
        live_runtime_version=context.live_runtime_version,
        plan_schema_version=plan.meta.schema_version,
    )

    expected_handoff = _normalize_relative_path(context.expected_handoff_relative_path)
    contract_handoff = _normalize_relative_path(plan.compatibility.ventoy_handoff_path)
    if contract_handoff != expected_handoff:
        raise HandoffDiscoveryError(
            "Plan handoff path contract mismatch "
            f"(expected {expected_handoff}, got {contract_handoff})."
        )

    try:
        discovered_relative = _normalize_relative_path(str(plan_path.resolve().relative_to(source_root.resolve())))
    except ValueError as exc:
        raise HandoffDiscoveryError("Plan path is not inside the discovered handoff source root.") from exc
    if discovered_relative != expected_handoff:
        raise HandoffDiscoveryError(
            f"Discovered plan path mismatch (expected {expected_handoff}, got {discovered_relative})."
        )

    expected_release_tag = context.expected_release_tag.strip()
    if expected_release_tag:
        if not plan.meta.release_tag:
            raise HandoffDiscoveryError("Plan is missing release_tag while runtime expects an explicit release tag.")
        if plan.meta.release_tag != expected_release_tag:
            raise HandoffDiscoveryError(
                f"Plan release_tag mismatch (expected {expected_release_tag}, got {plan.meta.release_tag})."
            )

    expected_build_commit = context.expected_build_commit.strip()
    if expected_build_commit:
        if not plan.meta.build_commit:
            raise HandoffDiscoveryError("Plan is missing build_commit while runtime expects an explicit build commit.")
        if plan.meta.build_commit != expected_build_commit:
            raise HandoffDiscoveryError(
                f"Plan build_commit mismatch (expected {expected_build_commit}, got {plan.meta.build_commit})."
            )

    if context.max_plan_age_hours is not None:
        generated_at = plan.meta.generated_at_utc
        age = datetime.now(UTC) - generated_at
        if age > timedelta(hours=context.max_plan_age_hours):
            raise HandoffDiscoveryError(
                f"Plan is older than allowed freshness window ({context.max_plan_age_hours}h): age={age}."
            )


def load_runtime_metadata(metadata_path: str | Path = DEFAULT_RUNTIME_METADATA_PATH) -> dict[str, Any]:
    """Load local runtime metadata generated by the ISO payload pipeline."""
    path = Path(metadata_path)
    if not path.exists():
        return {}
    payload = _load_json(path)
    return payload if isinstance(payload, dict) else {}


def build_validation_context_from_runtime(
    *,
    live_runtime_version: str,
    runtime_metadata_path: str | Path = DEFAULT_RUNTIME_METADATA_PATH,
    max_plan_age_hours: int | None = None,
) -> HandoffValidationContext:
    """Build validation context from local runtime metadata when available."""
    metadata = load_runtime_metadata(runtime_metadata_path)
    build_commit = str(metadata.get("git_commit", "")).strip()
    return HandoffValidationContext(
        live_runtime_version=live_runtime_version,
        expected_build_commit=build_commit,
        max_plan_age_hours=max_plan_age_hours,
    )


def discover_and_validate_handoff_plan(
    context: HandoffValidationContext,
    *,
    search_roots: Sequence[str | Path] | None = None,
) -> HandoffDiscoveryResult:
    """Locate and validate the active Ventoy handoff plan in a fail-closed way."""
    handoff_relative_path = _normalize_relative_path(context.expected_handoff_relative_path)
    roots = [Path(path) for path in discover_handoff_sources(search_roots=search_roots)]
    if not roots:
        raise HandoffDiscoveryError("No handoff sources with plan.json were discovered.")

    candidates: list[tuple[float, Path, Path]] = []
    for root in roots:
        plan_path = root / handoff_relative_path
        if not plan_path.exists() or not plan_path.is_file():
            continue
        candidates.append((plan_path.stat().st_mtime, root, plan_path))

    if not candidates:
        raise HandoffDiscoveryError("No handoff plan files were found in candidate roots.")

    candidates.sort(key=lambda item: item[0], reverse=True)
    errors: list[str] = []

    for _mtime, source_root, plan_path in candidates:
        try:
            plan_payload = _load_json(plan_path)
            plan = validate_plan_contract(plan_payload)
            _apply_anti_stale_validation(
                plan=plan,
                context=context,
                source_root=source_root,
                plan_path=plan_path,
            )
            return HandoffDiscoveryResult(
                source_root=str(source_root.resolve()),
                plan_path=str(plan_path.resolve()),
                discovered_relative_path=handoff_relative_path,
                plan_mtime_utc=_mtime_utc(plan_path),
                plan=plan,
            )
        except (HandoffDiscoveryError, ValueError) as exc:
            errors.append(f"{plan_path}: {exc}")
            continue

    detail = "; ".join(errors) if errors else "unknown validation failure"
    raise HandoffDiscoveryError(f"No valid handoff plan was found. {detail}")
