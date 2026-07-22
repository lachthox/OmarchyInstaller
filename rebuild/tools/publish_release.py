#!/usr/bin/env python3
"""Publish rebuild release metadata and optional GitHub release assets."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rebuild.installer.shared.atomic_io import atomic_write_json, atomic_write_text
from rebuild.installer.shared.models import PLAN_SCHEMA_VERSION, ReleaseManifestContract


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def compute_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_command(command: list[str], cwd: Path | None = None) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def run_capture(command: list[str], cwd: Path | None = None) -> str:
    completed = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


def detect_git_commit(workspace: Path) -> str:
    try:
        return run_capture(["git", "-C", str(workspace), "rev-parse", "HEAD"])
    except subprocess.CalledProcessError:
        return "unknown"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_write_json(path, payload)


def find_single_file(artifact_dir: Path, pattern: str) -> Path:
    matches = sorted(artifact_dir.rglob(pattern))
    if not matches:
        raise RuntimeError(f"Missing required artifact matching pattern: {pattern}")
    if len(matches) != 1:
        raise RuntimeError(
            f"Ambiguous artifact match for {pattern}: " + ", ".join(str(path) for path in matches)
        )
    return matches[0]


def _require_manifest_pair(
    *,
    checkout_commit: str,
    requested_tag: str,
    iso_manifest: dict[str, Any],
    exe_manifest: dict[str, Any],
    iso_file: Path,
    exe_file: Path,
) -> tuple[str, str, str]:
    for name, manifest in (("ISO", iso_manifest), ("EXE", exe_manifest)):
        if manifest.get("dry_run") is not False:
            raise RuntimeError(f"{name} manifest is dry-run or missing an explicit false dry_run state")
    fields = ("git_commit", "release_tag", "release_version", "github_run_id", "github_ref")
    for field in fields:
        left = str(iso_manifest.get(field, "")).strip()
        right = str(exe_manifest.get(field, "")).strip()
        if not left or left != right:
            raise RuntimeError(f"ISO/EXE provenance mismatch for {field}: {left!r} != {right!r}")
    commit = str(iso_manifest["git_commit"])
    release_version = str(iso_manifest["release_version"])
    run_id = str(iso_manifest["github_run_id"])
    if commit != checkout_commit:
        raise RuntimeError("Artifact commit does not match the publishing checkout commit")
    if str(iso_manifest["release_tag"]) != requested_tag:
        raise RuntimeError("Artifact release tag does not match requested publication tag")
    iso_output = iso_manifest.get("output_iso", {})
    exe_output = exe_manifest.get("output", {})
    if not isinstance(iso_output, dict) or not isinstance(exe_output, dict):
        raise RuntimeError("Build manifests are missing output descriptors")
    expected = (
        ("ISO", iso_file, iso_output.get("name"), iso_output.get("sha256")),
        ("EXE", exe_file, exe_output.get("exe_name"), exe_output.get("sha256")),
    )
    for name, artifact, manifest_name, manifest_hash in expected:
        if artifact.name != manifest_name:
            raise RuntimeError(f"{name} filename does not match its build manifest")
        if compute_sha256(artifact) != manifest_hash:
            raise RuntimeError(f"{name} hash does not match its build manifest")
    return commit, release_version, run_id


def build_release_payload(
    workspace: Path,
    artifact_dir: Path,
    output_dir: Path,
    tag: str,
) -> dict[str, Any]:
    commit_sha = detect_git_commit(workspace)
    iso_file = find_single_file(artifact_dir, "*-omarchy-auto.iso")
    exe_file = find_single_file(artifact_dir, "OmarchyInstaller.exe")
    iso_manifest_path = find_single_file(artifact_dir, "iso-build-manifest.json")
    exe_manifest_path = find_single_file(artifact_dir, "windows-exe-build-manifest.json")

    iso_manifest = read_json(iso_manifest_path)
    exe_manifest = read_json(exe_manifest_path)

    commit_sha, _release_version, run_id = _require_manifest_pair(
        checkout_commit=commit_sha,
        requested_tag=tag,
        iso_manifest=iso_manifest,
        exe_manifest=exe_manifest,
        iso_file=iso_file,
        exe_file=exe_file,
    )

    iso_sha = compute_sha256(iso_file)
    exe_sha = compute_sha256(exe_file)

    release_manifest = {
        "schema_version": "1.0.0",
        "generated_at_utc": utc_now(),
        "tag": tag,
        "build": {
            "git_commit": commit_sha,
            "github_run_id": run_id,
            "github_ref": str(iso_manifest["github_ref"]),
        },
        "artifacts": {
            "iso": {
                "name": iso_file.name,
                "sha256": iso_sha,
                "size_bytes": iso_file.stat().st_size,
            },
            "exe": {
                "name": exe_file.name,
                "sha256": exe_sha,
                "size_bytes": exe_file.stat().st_size,
            },
            "checksums_file": "sha256sums.txt",
            "release_manifest_file": "release_manifest.json",
            "compatibility_manifest_file": "compatibility_manifest.json",
        },
        "contracts": {
            "plan_schema_version": PLAN_SCHEMA_VERSION,
            "compatibility_schema_version": "1.0.0",
            "iso_pipeline_manifest_schema": iso_manifest.get("schema_version", ""),
            "exe_pipeline_manifest_schema": exe_manifest.get("schema_version", ""),
        },
    }
    ReleaseManifestContract.model_validate(release_manifest)

    compatibility_manifest = {
        "schema_version": "1.0.0",
        "generated_at_utc": utc_now(),
        "tag": tag,
        "build_commit": commit_sha,
        "artifact_pairing": {
            "iso_sha256": iso_sha,
            "exe_sha256": exe_sha,
        },
        "minimum_versions": {
            "windows_prep_exe_version": exe_manifest.get("version_stamp", {}).get("dotted_quad", ""),
            "live_runtime_plan_schema_version": PLAN_SCHEMA_VERSION,
        },
        "compatibility_rules": [
            "Windows EXE and Arch ISO artifacts must come from the same release tag.",
            "Plan schema compatibility must be validated before destructive operations.",
            "Consumers must fail closed on missing or incompatible compatibility metadata.",
        ],
        "bootstrap_expectations": {
            "live_entrypoint": "/opt/omarchy-venv/bin/python -m installer.main",
            "first_login_launcher_target": "/usr/local/bin/omarchy-first-login",
            "omarchy_timing_contract": "post-install-only",
        },
        "transport_contract": {
            "model": "Ventoy",
            "handoff_plan_path": "omarchy/plan.json",
            "handoff_manifest_path": "omarchy/handoff-manifest.json",
            "network_credentials": "interactive-only",
        },
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "release_manifest.json", release_manifest)
    write_json(output_dir / "compatibility_manifest.json", compatibility_manifest)

    checksums_path = output_dir / "sha256sums.txt"
    atomic_write_text(
        checksums_path,
        "".join(
            [
                f"{iso_sha}  {iso_file.name}\n",
                f"{exe_sha}  {exe_file.name}\n",
                f"{compute_sha256(output_dir / 'release_manifest.json')}  release_manifest.json\n",
                f"{compute_sha256(output_dir / 'compatibility_manifest.json')}  compatibility_manifest.json\n",
            ]
        ),
    )

    bundle = {
        "iso_file": iso_file,
        "exe_file": exe_file,
        "release_manifest": output_dir / "release_manifest.json",
        "compatibility_manifest": output_dir / "compatibility_manifest.json",
        "checksums": checksums_path,
    }
    return bundle


def enforce_signing_gate(signing_evidence_path: Path, allow_unsigned: bool) -> dict[str, Any]:
    """Decide whether the Windows EXE's signing state permits publication.

    Default (fail-closed): the EXE must carry a production Authenticode
    signature (`production_signing` and `signed` both true).

    With `allow_unsigned=True` the caller has made a deliberate decision to
    publish an unsigned (or non-production-signed) EXE -- the signing evidence
    file must still exist and be recorded, but a non-production signature no
    longer blocks the publish. This is the supported $0 open-source path;
    Windows SmartScreen will warn users, and origin/integrity are covered by
    the release checksums and GitHub build attestation rather than by
    Authenticode. See docs/windows-code-signing.md for the signed path.
    """
    if not signing_evidence_path.is_file():
        raise RuntimeError(
            "Windows EXE signing evidence is missing; refusing to publish an "
            "unverified production artifact. Run rebuild.tools.sign_windows_exe first."
        )
    signing_evidence = read_json(signing_evidence_path)
    is_production = signing_evidence.get("production_signing") is True and signing_evidence.get("signed") is True
    if is_production:
        return signing_evidence
    if allow_unsigned:
        print(
            "WARNING: publishing an EXE that is NOT signed with a production "
            "Authenticode certificate (--allow-unsigned). Users will see a "
            "Windows SmartScreen warning. Certificate source: "
            f"{signing_evidence.get('certificate_source', 'none')}, "
            f"signed={signing_evidence.get('signed')}.",
            file=sys.stderr,
        )
        return signing_evidence
    raise RuntimeError(
        "Windows EXE is not signed with a production Authenticode certificate "
        "(production_signing must be true). Configure WINDOWS_CODESIGN_PFX_BASE64 / "
        "WINDOWS_CODESIGN_PASSWORD secrets, or pass --allow-unsigned to publish an "
        "unsigned open-source release; production release remains blocked until then."
    )


def publish_release_assets(repo: str, tag: str, assets: list[Path], dry_run: bool) -> None:
    if dry_run:
        return
    try:
        run_command(["gh", "release", "view", tag, "--repo", repo])
    except subprocess.CalledProcessError:
        run_command(
            [
                "gh",
                "release",
                "create",
                tag,
                "--repo",
                repo,
                "--title",
                f"OmarchyInstaller {tag}",
                "--notes",
                "Automated rebuild release pipeline output.",
            ]
        )
    else:
        raise RuntimeError(f"Release tag already exists and is immutable: {tag}")
    upload_command = ["gh", "release", "upload", tag, "--repo", repo, *[str(path) for path in assets]]
    run_command(upload_command)


def load_existing_bundle(artifact_dir: Path, output_dir: Path) -> dict[str, Path]:
    iso_file = find_single_file(artifact_dir, "*-omarchy-auto.iso")
    exe_file = find_single_file(artifact_dir, "OmarchyInstaller.exe")
    release_manifest = output_dir / "release_manifest.json"
    compatibility_manifest = output_dir / "compatibility_manifest.json"
    checksums = output_dir / "sha256sums.txt"
    for path in (release_manifest, compatibility_manifest, checksums):
        if not path.is_file() or path.stat().st_size <= 0:
            raise RuntimeError(f"Existing release bundle is incomplete: {path}")
    ReleaseManifestContract.model_validate(read_json(release_manifest))
    checksum_text = checksums.read_text(encoding="utf-8")
    for path in (iso_file, exe_file, release_manifest, compatibility_manifest):
        expected_line = f"{compute_sha256(path)}  {path.name}"
        if expected_line not in checksum_text:
            raise RuntimeError(f"Existing checksum bundle does not authenticate {path.name}")
    return {
        "iso_file": iso_file,
        "exe_file": exe_file,
        "release_manifest": release_manifest,
        "compatibility_manifest": compatibility_manifest,
        "checksums": checksums,
    }


def run_pipeline(args: argparse.Namespace) -> int:
    workspace = args.workspace.resolve()
    artifact_dir = args.artifact_dir.resolve()
    output_dir = args.output_dir.resolve()

    if not artifact_dir.exists():
        raise RuntimeError(f"Artifact directory does not exist: {artifact_dir}")

    tag = args.tag
    bundle = (
        load_existing_bundle(artifact_dir, output_dir)
        if args.publish_only
        else build_release_payload(workspace, artifact_dir, output_dir, tag)
    )

    if args.publish:
        signing_evidence_path = bundle["exe_file"].parent / "windows-exe-signing.json"
        enforce_signing_gate(signing_evidence_path, args.allow_unsigned)
        repo = args.repo or os.environ.get("GITHUB_REPOSITORY", "")
        if not repo:
            raise RuntimeError("Repository not provided. Set --repo or GITHUB_REPOSITORY.")
        publish_release_assets(
            repo=repo,
            tag=tag,
            assets=[
                bundle["iso_file"],
                bundle["exe_file"],
                bundle["checksums"],
                bundle["release_manifest"],
                bundle["compatibility_manifest"],
            ],
            dry_run=args.dry_run,
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    workspace_default = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Publish rebuild release metadata and assets.")
    parser.add_argument(
        "--workspace",
        type=Path,
        default=workspace_default,
        help="Repository workspace root.",
    )
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        required=True,
        help="Directory containing ISO/EXE artifacts and build manifests.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=workspace_default / "rebuild" / "dist" / "release",
        help="Directory for generated release metadata files.",
    )
    parser.add_argument(
        "--tag",
        required=True,
        help="New immutable semantic release tag.",
    )
    parser.add_argument(
        "--repo",
        default="",
        help="GitHub repository in owner/name format.",
    )
    parser.add_argument(
        "--publish",
        action="store_true",
        help="Upload assets to GitHub Release.",
    )
    parser.add_argument(
        "--publish-only",
        action="store_true",
        help="Publish an already generated and attested metadata bundle without rewriting it.",
    )
    parser.add_argument(
        "--allow-unsigned",
        action="store_true",
        help=(
            "Deliberately permit publishing a Windows EXE that is not signed with a "
            "production Authenticode certificate (the supported $0 open-source path). "
            "Signing evidence must still exist. See docs/windows-code-signing.md."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip external publish side effects.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return run_pipeline(args)
    except Exception as exc:  # pragma: no cover - simple CLI error handling
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
