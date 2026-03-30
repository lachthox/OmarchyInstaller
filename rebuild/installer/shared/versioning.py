"""Version helpers for rebuild module compatibility checks."""

from __future__ import annotations

from dataclasses import dataclass
import re


VERSION_PATTERN = re.compile(r"^\s*(\d+)\.(\d+)\.(\d+)(?:\.(\d+))?(?:[-+_.]([0-9A-Za-z.-]+))?\s*$")


@dataclass(frozen=True, slots=True)
class ParsedVersion:
    major: int
    minor: int
    patch: int
    build: int = 0
    suffix: str = ""

    def core_tuple(self) -> tuple[int, int, int, int]:
        return (self.major, self.minor, self.patch, self.build)


def parse_version(value: str) -> ParsedVersion:
    normalized = value.strip()
    if not normalized:
        raise ValueError("Version value cannot be empty.")
    match = VERSION_PATTERN.match(normalized)
    if not match:
        raise ValueError(f"Invalid version format: {value}")
    major, minor, patch, build, suffix = match.groups()
    return ParsedVersion(
        major=int(major),
        minor=int(minor),
        patch=int(patch),
        build=int(build or 0),
        suffix=suffix or "",
    )


def normalize_version(value: str) -> str:
    parsed = parse_version(value)
    core = f"{parsed.major}.{parsed.minor}.{parsed.patch}.{parsed.build}"
    return f"{core}-{parsed.suffix}" if parsed.suffix else core


def compare_versions(left: str, right: str) -> int:
    left_parsed = parse_version(left)
    right_parsed = parse_version(right)
    if left_parsed.core_tuple() < right_parsed.core_tuple():
        return -1
    if left_parsed.core_tuple() > right_parsed.core_tuple():
        return 1
    if left_parsed.suffix and not right_parsed.suffix:
        return -1
    if right_parsed.suffix and not left_parsed.suffix:
        return 1
    if left_parsed.suffix < right_parsed.suffix:
        return -1
    if left_parsed.suffix > right_parsed.suffix:
        return 1
    return 0


def is_version_at_least(current: str, minimum: str) -> bool:
    return compare_versions(current, minimum) >= 0

