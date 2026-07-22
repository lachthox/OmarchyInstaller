from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from rebuild.installer.platforms.windows.release_provisioning import (
    ProvisioningError,
    asset_url,
    parse_sha256sums,
    provision_release_assets,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
TAG = "v1.2.3"
REPO = "owner/repo"
ISO_NAME = "omarchy-v1.2.3.iso"


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class FakeDownloader:
    def __init__(self, payloads: dict[str, bytes], sums: str, tag: str = TAG) -> None:
        self.payloads = payloads
        self.sums = sums
        self.tag = tag
        self.downloads: list[str] = []

    def fetch_text(self, url: str) -> str:
        assert url == asset_url(REPO, self.tag, "sha256sums.txt")
        return self.sums

    def download(self, url: str, dest: Path) -> None:
        name = url.rsplit("/", 1)[-1]
        self.downloads.append(name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self.payloads[name])


def release_payloads(*, tag: str = TAG, iso_name: str = ISO_NAME) -> tuple[dict[str, bytes], str]:
    iso = b"paired iso bytes"
    compatibility = json.dumps(
        {
            "schema_version": "1.0.0",
            "tag": tag,
            "artifact_pairing": {"iso_sha256": sha256(iso), "exe_sha256": "b" * 64},
        }
    ).encode()
    manifest = {
        "schema_version": "1.0.0",
        "generated_at_utc": "2026-07-22T00:00:00Z",
        "tag": tag,
        "build": {
            "git_commit": "a" * 40,
            "github_run_id": "12345",
            "github_ref": f"refs/tags/{tag}",
        },
        "artifacts": {
            "iso": {"name": iso_name, "sha256": sha256(iso), "size_bytes": len(iso)},
            "exe": {"name": "OmarchyInstaller.exe", "sha256": "b" * 64, "size_bytes": 10},
            "checksums_file": "sha256sums.txt",
            "release_manifest_file": "release_manifest.json",
            "compatibility_manifest_file": "compatibility_manifest.json",
        },
        "contracts": {
            "plan_schema_version": "1.0.0",
            "compatibility_schema_version": "1.0.0",
            "iso_pipeline_manifest_schema": "1.0.0",
            "exe_pipeline_manifest_schema": "1.0.0",
        },
    }
    manifest_bytes = (json.dumps(manifest, indent=2) + "\n").encode()
    payloads = {
        "release_manifest.json": manifest_bytes,
        "compatibility_manifest.json": compatibility,
        iso_name: iso,
    }
    sums = "".join(f"{sha256(content)}  {name}\n" for name, content in payloads.items())
    return payloads, sums


def test_provisions_verified_release_and_generates_paired_plan(tmp_path: Path) -> None:
    payloads, sums = release_payloads()
    downloader = FakeDownloader(payloads, sums)

    assets = provision_release_assets(
        tag=TAG,
        repo=REPO,
        template_path=REPO_ROOT / "rebuild" / "assets" / "templates" / "plan.template.json",
        producer_version="1.2.3.0",
        cache_root=tmp_path,
        downloader=downloader,
    )

    plan = json.loads(assets.plan_path.read_text(encoding="utf-8"))
    assert assets.iso_path.read_bytes() == payloads[ISO_NAME]
    assert plan["provenance"]["release_tag"] == TAG
    assert plan["provenance"]["iso_name"] == ISO_NAME
    assert plan["provenance"]["iso_sha256"] == sha256(payloads[ISO_NAME])
    assert plan["provenance"]["producer_version"] == "1.2.3.0"
    assert plan["meta"]["producer_version"] == "1.2.3.0"
    assert downloader.downloads == [
        "release_manifest.json",
        "compatibility_manifest.json",
        ISO_NAME,
    ]

    provision_release_assets(
        tag=TAG,
        repo=REPO,
        template_path=REPO_ROOT / "rebuild" / "assets" / "templates" / "plan.template.json",
        producer_version="1.2.3.0",
        cache_root=tmp_path,
        downloader=downloader,
    )
    assert len(downloader.downloads) == 3


def test_rejects_manifest_tag_mismatch(tmp_path: Path) -> None:
    payloads, sums = release_payloads(tag="v9.9.9")
    downloader = FakeDownloader(payloads, sums)

    with pytest.raises(ProvisioningError, match="does not match requested tag"):
        provision_release_assets(
            tag=TAG,
            repo=REPO,
            template_path=REPO_ROOT / "rebuild" / "assets" / "templates" / "plan.template.json",
            cache_root=tmp_path,
            downloader=downloader,
        )


def test_rejects_unsafe_iso_asset_name(tmp_path: Path) -> None:
    payloads, sums = release_payloads(iso_name="../escape.iso")
    downloader = FakeDownloader(payloads, sums)

    with pytest.raises(ProvisioningError, match="unsafe asset name"):
        provision_release_assets(
            tag=TAG,
            repo=REPO,
            template_path=REPO_ROOT / "rebuild" / "assets" / "templates" / "plan.template.json",
            cache_root=tmp_path,
            downloader=downloader,
        )


def test_checksum_parser_ignores_malformed_entries() -> None:
    assert parse_sha256sums("not-a-hash  bad.iso\n" + f"{'a' * 64}  good.iso\n") == {
        "good.iso": "a" * 64
    }


def test_released_plan_is_self_compatible(tmp_path: Path) -> None:
    """Regression: v0.1.9 shipped a plan whose hardcoded template minimums (1.0.0)
    rejected its own producer (0.1.9.0) and the paired live runtime, blocking every
    real install at preflight. A released plan must always clear its own gate when
    paired with same-tag artifacts."""
    tag = "v0.1.9"
    iso_name = "omarchy-v0.1.9.iso"
    producer_version = "0.1.9.0"
    payloads, sums = release_payloads(tag=tag, iso_name=iso_name)
    downloader = FakeDownloader(payloads, sums, tag=tag)

    assets = provision_release_assets(
        tag=tag,
        repo=REPO,
        template_path=REPO_ROOT / "rebuild" / "assets" / "templates" / "plan.template.json",
        producer_version=producer_version,
        cache_root=tmp_path,
        downloader=downloader,
    )
    plan = json.loads(assets.plan_path.read_text(encoding="utf-8"))

    from rebuild.installer.shared.compatibility import evaluate_runtime_compatibility
    from rebuild.installer.shared.models import CompatibilityContract

    contract = CompatibilityContract.model_validate(plan["compatibility"])
    result = evaluate_runtime_compatibility(
        contract,
        windows_prep_version=plan["meta"]["producer_version"],
        # The live runtime resolves the same-tag release version from the ISO's
        # baked build metadata.
        live_runtime_version=tag.lstrip("v"),
        plan_schema_version=plan["meta"]["schema_version"],
    )
    assert result.is_compatible, result.reasons
