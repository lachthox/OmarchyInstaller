"""PEP 440 version helpers backed by the standards-compliant packaging library."""

from __future__ import annotations

from packaging.version import InvalidVersion, Version


ParsedVersion = Version


def parse_version(value: str) -> ParsedVersion:
    normalized = value.strip()
    if not normalized:
        raise ValueError("Version value cannot be empty.")
    try:
        return Version(normalized)
    except InvalidVersion as exc:
        raise ValueError(f"Invalid version format: {value}") from exc


def normalize_version(value: str) -> str:
    return str(parse_version(value))


def compare_versions(left: str, right: str) -> int:
    left_parsed = parse_version(left)
    right_parsed = parse_version(right)
    return (left_parsed > right_parsed) - (left_parsed < right_parsed)


def is_version_at_least(current: str, minimum: str) -> bool:
    return compare_versions(current, minimum) >= 0
