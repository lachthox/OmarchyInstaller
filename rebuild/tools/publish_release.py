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


def default_tag() -> str:
    return f"v{datetime.now(UTC).strftime('%Y.%m.%d')}"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def find_single_file(artifact_dir: Path, pattern: str) -> Path:
    matches = sorted(artifact_dir.rglob(pattern))
    if not matches:
        raise RuntimeError(f"Missing required artifact matching pattern: {pattern}")
    return matches[0]


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

    iso_sha = compute_sha256(iso_file)
    exe_sha = compute_sha256(exe_file)

    release_manifest = {
        "schema_version": "1.0.0",
        "generated_at_utc": utc_now(),
        "tag": tag,
        "build": {
            "git_commit": commit_sha,
            "github_run_id": os.environ.get("GITHUB_RUN_ID", ""),
            "github_ref": os.environ.get("GITHUB_REF", ""),
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
            "plan_schema_version": "0.1.0",
            "compatibility_schema_version": "1.0.0",
            "iso_pipeline_manifest_schema": iso_manifest.get("schema_version", ""),
            "exe_pipeline_manifest_schema": exe_manifest.get("schema_version", ""),
        },
    }

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
            "live_runtime_plan_schema_version": "0.1.0",
        },
        "compatibility_rules": [
            "Windows EXE and Arch ISO artifacts must come from the same release tag.",
            "Plan schema compatibility must be validated before destructive operations.",
            "Consumers must fail closed on missing or incompatible compatibility metadata.",
        ],
        "bootstrap_expectations": {
            "live_entrypoint": "python3 /opt/omarchy-installer/main.py",
            "live_setup_wrapper": "/opt/omarchy-setup/setup.sh",
            "live_entrypoint_compat_alias": "python3 /opt/omarchy-setup/main.py",
            "firstboot_wrapper_target": "/usr/local/bin/omarchy-firstboot-wrapper.sh",
            "omarchy_timing_contract": "post-install-only",
        },
        "transport_contract": {
            "model": "Ventoy",
            "handoff_plan_path": "omarchy/plan.json",
            "optional_network_path": "omarchy/wifi.json",
        },
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "release_manifest.json", release_manifest)
    write_json(output_dir / "compatibility_manifest.json", compatibility_manifest)

    checksums_path = output_dir / "sha256sums.txt"
    checksums_path.write_text(
        "".join(
            [
                f"{iso_sha}  {iso_file.name}\n",
                f"{exe_sha}  {exe_file.name}\n",
                f"{compute_sha256(output_dir / 'release_manifest.json')}  release_manifest.json\n",
                f"{compute_sha256(output_dir / 'compatibility_manifest.json')}  compatibility_manifest.json\n",
            ]
        ),
        encoding="utf-8",
    )

    bundle = {
        "iso_file": iso_file,
        "exe_file": exe_file,
        "release_manifest": output_dir / "release_manifest.json",
        "compatibility_manifest": output_dir / "compatibility_manifest.json",
        "checksums": checksums_path,
    }
    return bundle


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
    upload_command = ["gh", "release", "upload", tag, "--repo", repo, "--clobber", *[str(path) for path in assets]]
    run_command(upload_command)


def run_pipeline(args: argparse.Namespace) -> int:
    workspace = args.workspace.resolve()
    artifact_dir = args.artifact_dir.resolve()
    output_dir = args.output_dir.resolve()

    if not artifact_dir.exists():
        raise RuntimeError(f"Artifact directory does not exist: {artifact_dir}")

    tag = args.tag or default_tag()
    bundle = build_release_payload(workspace, artifact_dir, output_dir, tag)

    if args.publish:
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
        default="",
        help="Release tag to publish. Defaults to date tag.",
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
