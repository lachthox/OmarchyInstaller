"""Provision the release-paired ISO, plan, and manifests for a real run.

On a genuine end-user run the Windows installer must obtain three things that
the VM test harness previously supplied by hand:

* the customized Arch ISO for this exe's release tag,
* the release manifest (which pins the ISO name + sha256), and
* a release-paired ``plan.json`` whose provenance matches both.

This module downloads the release assets from GitHub for a specific tag,
verifies them against the published ``sha256sums.txt``, caches them under the
user's local app data, and generates the base plan from the bundled template by
filling in the real provenance. The disk-identity blocks stay as template
placeholders here -- they are overwritten from the live disk probe by
``apply_partition_metadata_to_plan`` during the partition step.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
from typing import Any, Protocol
import urllib.request
import uuid

from ...shared import ReleaseManifestContract, atomic_write_json, validate_plan_contract

_CHUNK = 1024 * 1024


class ProvisioningError(RuntimeError):
    """Raised when release assets cannot be obtained or verified."""


@dataclass(frozen=True, slots=True)
class ProvisionedAssets:
    tag: str
    iso_path: Path
    plan_path: Path
    release_manifest_path: Path
    compatibility_manifest_path: Path

    def to_dict(self) -> dict[str, str]:
        return {
            "tag": self.tag,
            "iso_path": str(self.iso_path),
            "plan_path": str(self.plan_path),
            "release_manifest_path": str(self.release_manifest_path),
            "compatibility_manifest_path": str(self.compatibility_manifest_path),
        }


class AssetDownloader(Protocol):
    def fetch_text(self, url: str) -> str: ...

    def download(self, url: str, dest: Path) -> None: ...


class UrllibDownloader:
    """Default downloader using the standard library (no third-party deps)."""

    def __init__(self, *, text_timeout: int = 60, file_timeout: int = 1800) -> None:
        self._text_timeout = text_timeout
        self._file_timeout = file_timeout

    def fetch_text(self, url: str) -> str:
        try:
            with urllib.request.urlopen(url, timeout=self._text_timeout) as response:  # noqa: S310
                return response.read().decode("utf-8")
        except OSError as exc:
            raise ProvisioningError(f"Could not fetch {url}: {exc}") from exc

    def download(self, url: str, dest: Path) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".part")
        try:
            with urllib.request.urlopen(url, timeout=self._file_timeout) as response, tmp.open("wb") as handle:  # noqa: S310
                shutil.copyfileobj(response, handle, length=_CHUNK)
        except OSError as exc:
            tmp.unlink(missing_ok=True)
            raise ProvisioningError(f"Could not download {url}: {exc}") from exc
        tmp.replace(dest)


def default_cache_root() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    root = Path(base) if base else Path.home() / ".omarchy"
    return root / "Omarchy" / "releases"


def asset_url(repo: str, tag: str, name: str) -> str:
    return f"https://github.com/{repo}/releases/download/{tag}/{name}"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_sha256sums(text: str) -> dict[str, str]:
    """Parse a ``sha256sums.txt`` (``<hex>  <name>`` per line) into {name: hex}."""
    sums: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parts = stripped.split(None, 1)
        if len(parts) != 2:
            continue
        digest, name = parts
        digest = digest.lower()
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            continue
        normalized_name = name.lstrip("*").strip()
        if normalized_name:
            sums[normalized_name] = digest
    return sums


def build_release_plan(
    template: dict[str, Any],
    release_manifest: dict[str, Any],
    release_manifest_sha256: str,
    *,
    producer_version: str,
) -> dict[str, Any]:
    """Fill the plan template's provenance from a downloaded release manifest.

    Identity blocks are left as template placeholders on purpose; the partition
    step overwrites them with the live disk probe before the handoff runs.
    """
    plan = copy.deepcopy(template)
    try:
        iso = release_manifest["artifacts"]["iso"]
        tag = release_manifest["tag"]
    except (KeyError, TypeError) as exc:
        raise ProvisioningError(f"Release manifest is missing required fields: {exc}") from exc

    build = release_manifest.get("build", {}) or {}
    build_commit = str(build.get("git_commit") or plan["provenance"]["build_commit"])
    run_id = str(build.get("github_run_id") or "release")

    provenance = plan["provenance"]
    provenance["release_tag"] = tag
    provenance["build_commit"] = build_commit
    provenance["workflow_run_id"] = run_id
    provenance["producer_version"] = producer_version
    provenance["iso_name"] = str(iso["name"])
    provenance["iso_sha256"] = str(iso["sha256"]).lower()
    provenance["release_manifest_sha256"] = release_manifest_sha256.lower()

    meta = plan["meta"]
    meta["release_tag"] = tag
    meta["build_commit"] = build_commit
    meta["producer_version"] = producer_version
    meta["plan_id"] = uuid.uuid4().hex
    meta["generated_at_utc"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return validate_plan_contract(plan).model_dump(mode="json")


def _asset_name(name: str) -> str:
    """Reject release-controlled paths; every asset must stay inside its tag cache."""
    candidate = name.strip()
    if not candidate or Path(candidate).name != candidate or "/" in candidate or "\\" in candidate:
        raise ProvisioningError(f"Release manifest contains an unsafe asset name: {name!r}")
    return candidate


def _ensure_asset(
    downloader: AssetDownloader,
    *,
    repo: str,
    tag: str,
    name: str,
    cache: Path,
    checksums: dict[str, str],
    verify: bool,
) -> Path:
    name = _asset_name(name)
    dest = cache / name
    expected = checksums.get(name)
    if verify and expected is None:
        raise ProvisioningError(f"{name} is not listed in sha256sums.txt for {tag}.")

    if dest.is_file() and (not verify or _sha256(dest) == expected):
        return dest

    downloader.download(asset_url(repo, tag, name), dest)
    if verify:
        actual = _sha256(dest)
        if actual != expected:
            dest.unlink(missing_ok=True)
            raise ProvisioningError(
                f"Checksum mismatch for {name}: expected {expected}, got {actual}."
            )
    return dest


def provision_release_assets(
    *,
    tag: str,
    repo: str,
    template_path: Path,
    producer_version: str = "1.0.0",
    cache_root: Path | None = None,
    downloader: AssetDownloader | None = None,
    verify: bool = True,
) -> ProvisionedAssets:
    """Download + verify the release assets and generate the paired plan."""
    if not tag:
        raise ProvisioningError("No release tag is available to provision from.")
    active = downloader or UrllibDownloader()
    cache = (cache_root or default_cache_root()) / tag
    cache.mkdir(parents=True, exist_ok=True)

    checksums = parse_sha256sums(active.fetch_text(asset_url(repo, tag, "sha256sums.txt")))
    if not checksums:
        raise ProvisioningError(f"sha256sums.txt for {tag} did not contain valid checksums.")

    release_manifest_path = _ensure_asset(
        active, repo=repo, tag=tag, name="release_manifest.json", cache=cache, checksums=checksums, verify=verify
    )
    compatibility_manifest_path = _ensure_asset(
        active, repo=repo, tag=tag, name="compatibility_manifest.json", cache=cache, checksums=checksums, verify=verify
    )

    try:
        release_manifest = json.loads(release_manifest_path.read_text(encoding="utf-8"))
        release_contract = ReleaseManifestContract.model_validate(release_manifest)
        if release_contract.tag != tag:
            raise ProvisioningError(
                f"Release manifest tag {release_contract.tag!r} does not match requested tag {tag!r}."
            )
        iso_name = _asset_name(release_contract.artifacts.iso.name)
        checksum_iso = checksums.get(iso_name, "")
        if checksum_iso != release_contract.artifacts.iso.sha256:
            raise ProvisioningError("Release manifest ISO hash does not match sha256sums.txt.")
    except ProvisioningError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise ProvisioningError(f"Release manifest could not be parsed: {exc}") from exc

    iso_path = _ensure_asset(
        active, repo=repo, tag=tag, name=iso_name, cache=cache, checksums=checksums, verify=verify
    )

    try:
        compatibility = json.loads(compatibility_manifest_path.read_text(encoding="utf-8"))
        if not isinstance(compatibility, dict):
            raise TypeError("manifest root is not an object")
        if compatibility.get("schema_version") != "1.0.0" or compatibility.get("tag") != tag:
            raise ProvisioningError("Compatibility manifest schema or release tag does not match.")
        pairing = compatibility.get("artifact_pairing", {})
        if not isinstance(pairing, dict) or pairing.get("iso_sha256") != release_contract.artifacts.iso.sha256:
            raise ProvisioningError("Compatibility manifest does not match the release ISO.")
    except ProvisioningError:
        raise
    except (OSError, TypeError, ValueError) as exc:
        raise ProvisioningError(f"Compatibility manifest could not be parsed: {exc}") from exc

    try:
        template = json.loads(Path(template_path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ProvisioningError(f"Bundled plan template could not be read: {exc}") from exc

    plan = build_release_plan(
        template,
        release_manifest,
        _sha256(release_manifest_path),
        producer_version=producer_version,
    )
    plan_path = cache / "plan.json"
    atomic_write_json(plan_path, plan)

    return ProvisionedAssets(
        tag=tag,
        iso_path=iso_path,
        plan_path=plan_path,
        release_manifest_path=release_manifest_path,
        compatibility_manifest_path=compatibility_manifest_path,
    )
