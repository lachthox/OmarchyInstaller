#!/usr/bin/env python3
"""Build the rebuild Arch ISO artifact and metadata.

This script keeps ISO orchestration logic in Python so workflow YAML stays thin.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


SUPPORTED_ARCH_ISO = "2026.07.01"
SUPPORTED_ARCHINSTALL = "4.4-1"
ARCH_MIRROR_DEFAULT = f"https://geo.mirror.pkgbuild.com/iso/{SUPPORTED_ARCH_ISO}"
LIVE_ENTRYPOINT = "/opt/omarchy-venv/bin/python -m installer.main"


@dataclass(slots=True)
class IsoDescriptor:
    name: str
    date: str
    iso_url: str
    sha_url: str
    expected_sha256: str


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def validate_release_version(value: str) -> str:
    normalized = value.strip()
    if not re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", normalized):
        raise ValueError("release version must be explicit semantic X.Y.Z")
    return normalized


def fetch_text(url: str) -> str:
    with urllib.request.urlopen(url) as response:
        return response.read().decode("utf-8")


def pinned_iso() -> tuple[str, str]:
    return f"archlinux-{SUPPORTED_ARCH_ISO}-x86_64.iso", SUPPORTED_ARCH_ISO


def compute_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_expected_sha256(sha_file: Path, iso_name: str) -> str:
    for raw_line in sha_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or iso_name not in line:
            continue
        parts = line.split()
        if not parts:
            continue
        return parts[0]
    raise RuntimeError(f"Checksum entry for {iso_name} not found in {sha_file}")


def download_file(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url) as response, dest.open("wb") as output:
        shutil.copyfileobj(response, output)


def run_command(command: list[str], cwd: Path | None = None) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def detect_git_commit(workspace: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(workspace), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError:
        return "unknown"
    return completed.stdout.strip() or "unknown"


def ensure_workspace_layout(workspace: Path) -> None:
    required_paths = [
        workspace / "build-custom-iso.sh",
        workspace / "rebuild" / "installer",
        workspace / "rebuild" / "requirements.txt",
        workspace / "rebuild" / "requirements.lock",
        workspace / "rebuild" / "pyproject.toml",
        workspace / "rebuild" / "assets" / "scripts" / "live-autostart.sh",
        workspace / "rebuild" / "assets" / "scripts" / "first-login.sh",
    ]
    missing = [str(path) for path in required_paths if not path.exists()]
    if missing:
        raise RuntimeError(f"Workspace is missing required paths: {missing}")


def write_live_launcher(path: Path) -> None:
    path.write_text(
        "#!/usr/bin/env bash\n"
        "set -Eeuo pipefail\n\n"
        f"exec {LIVE_ENTRYPOINT} \"$@\"\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


def prepare_payload(
    workspace: Path,
    payload_dir: Path,
    iso: IsoDescriptor,
    commit_sha: str,
    release_version: str,
    release_tag: str,
) -> dict[str, Any]:
    if payload_dir.exists():
        shutil.rmtree(payload_dir)
    payload_dir.mkdir(parents=True, exist_ok=True)

    installer_src = workspace / "rebuild" / "installer"
    installer_dest = payload_dir / "installer"
    shutil.copytree(
        installer_src,
        installer_dest,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    shutil.copytree(workspace / "rebuild" / "assets", payload_dir / "assets")

    for src_rel, dst_rel in [
        ("rebuild/requirements.txt", "requirements.txt"),
        ("rebuild/requirements.lock", "requirements.lock"),
        ("rebuild/requirements-dev.txt", "requirements-dev.txt"),
        ("rebuild/pyproject.toml", "pyproject.toml"),
        ("rebuild/README.md", "README.md"),
        ("rebuild/assets/scripts/live-autostart.sh", "hooks/live-autostart.sh"),
    ]:
        src = workspace / src_rel
        dst = payload_dir / dst_rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    live_launcher = payload_dir / "launch-installer"
    write_live_launcher(live_launcher)

    runtime_packages = payload_dir / "runtime-packages.txt"
    runtime_packages.write_text(
        "python\n"
        "python-pip\n"
        "networkmanager\n"
        "archinstall\n"
        "gptfdisk\n"
        "cryptsetup\n"
        "btrfs-progs\n"
        "util-linux\n"
        "systemd\n"
        "efibootmgr\n"
        "git\n"
        "curl\n",
        encoding="utf-8",
    )

    metadata = {
        "schema_version": "1.0.0",
        "generated_at_utc": utc_now(),
        "git_commit": commit_sha,
        "release_version": release_version,
        "release_tag": release_tag,
        "base_iso": {
            "name": iso.name,
            "date": iso.date,
            "sha256": iso.expected_sha256,
            "url": iso.iso_url,
        },
        "runtime": {
            "entrypoint": LIVE_ENTRYPOINT,
            "live_launcher": "/opt/omarchy-installer/launch-installer",
            "installer_package_root": "/opt/omarchy-installer/installer",
            "python_requirements_file": "/opt/omarchy-installer/requirements.lock",
            "python_requirements_sha256": compute_sha256(payload_dir / "requirements.lock"),
            "python_venv": "/opt/omarchy-venv",
            "archinstall_version": SUPPORTED_ARCHINSTALL,
            "required_system_packages_file": "/opt/omarchy-installer/runtime-packages.txt",
            "required_system_packages_sha256": compute_sha256(runtime_packages),
            "required_runtime_binaries": [
                "python3",
                "nmcli",
                "archinstall",
                "cryptsetup",
                "mkfs.btrfs",
                "mount",
                "umount",
                "findmnt",
                "lsblk",
                "blkid",
                "udevadm",
                "partprobe",
                "sgdisk",
                "efibootmgr",
            ],
        },
        "startup_hooks": {
            "live_tty_hook": "/usr/local/bin/omarchy-live-autostart",
            "payload_hook_reference": "/opt/omarchy-installer/hooks/live-autostart.sh",
            "payload_hook_sha256": compute_sha256(payload_dir / "hooks" / "live-autostart.sh"),
        },
    }
    metadata_path = payload_dir / "build-metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    return metadata


def build_iso(
    workspace: Path,
    source_iso: Path,
    payload_dir: Path,
    output_iso: Path,
) -> None:
    build_script = workspace / "build-custom-iso.sh"
    build_script.chmod(0o755)
    output_iso.parent.mkdir(parents=True, exist_ok=True)

    command = [
        "sudo",
        str(build_script),
        str(source_iso),
        str(payload_dir),
        str(output_iso),
    ]
    run_command(command, cwd=workspace)


def write_manifest(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def run_pipeline(args: argparse.Namespace) -> int:
    workspace = args.workspace.resolve()
    output_dir = args.output_dir.resolve()
    work_dir = args.work_dir.resolve()
    ensure_workspace_layout(workspace)
    args.release_version = validate_release_version(args.release_version)
    if not args.release_tag.strip():
        raise ValueError("release tag cannot be empty")

    output_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    commit_sha = detect_git_commit(workspace)

    if args.dry_run:
        iso_name, iso_date = pinned_iso()
        iso = IsoDescriptor(
            name=iso_name,
            date=iso_date,
            iso_url="dry-run://archlinux",
            sha_url="dry-run://sha256sums",
            expected_sha256="dry-run",
        )
        source_iso_path = work_dir / iso.name
        source_iso_path.write_text("dry-run", encoding="utf-8")
    else:
        iso_name, iso_date = pinned_iso()
        iso = IsoDescriptor(
            name=iso_name,
            date=iso_date,
            iso_url=f"{args.mirror_url}/{iso_name}",
            sha_url=f"{args.mirror_url}/sha256sums.txt",
            expected_sha256="",
        )
        source_iso_path = work_dir / iso.name
        sha_path = work_dir / "sha256sums.txt"
        download_file(iso.iso_url, source_iso_path)
        download_file(iso.sha_url, sha_path)
        expected = parse_expected_sha256(sha_path, iso.name)
        actual = compute_sha256(source_iso_path)
        if expected != actual:
            raise RuntimeError(f"ISO checksum mismatch expected={expected} actual={actual}")
        iso.expected_sha256 = expected

    payload_dir = work_dir / "payload"
    runtime_metadata = prepare_payload(
        workspace, payload_dir, iso, commit_sha, args.release_version, args.release_tag
    )

    output_iso = output_dir / f"{args.artifact_prefix}-{iso.date}-x86_64-omarchy-auto.iso"
    if not args.dry_run:
        build_iso(workspace, source_iso_path, payload_dir, output_iso)
        output_sha = compute_sha256(output_iso)
        (output_dir / f"{output_iso.name}.sha256").write_text(
            f"{output_sha}  {output_iso.name}\n",
            encoding="utf-8",
        )
    else:
        output_iso.write_text("dry-run-iso", encoding="utf-8")
        output_sha = compute_sha256(output_iso)
        (output_dir / f"{output_iso.name}.sha256").write_text(
            f"{output_sha}  {output_iso.name}\n",
            encoding="utf-8",
        )

    manifest = {
        "schema_version": "1.0.0",
        "generated_at_utc": utc_now(),
        "artifact_prefix": args.artifact_prefix,
        "dry_run": args.dry_run,
        "git_commit": commit_sha,
        "release_version": args.release_version,
        "release_tag": args.release_tag,
        "github_run_id": os.environ.get("GITHUB_RUN_ID", "local"),
        "github_ref": os.environ.get("GITHUB_REF", f"refs/tags/{args.release_tag}"),
        "source_iso": {
            "name": iso.name,
            "date": iso.date,
            "url": iso.iso_url,
            "sha_url": iso.sha_url,
            "sha256": iso.expected_sha256,
        },
        "output_iso": {
            "path": str(output_iso),
            "name": output_iso.name,
            "sha256": output_sha,
        },
        "runtime_metadata": runtime_metadata,
    }
    write_manifest(output_dir / "iso-build-manifest.json", manifest)
    return 0


def build_parser() -> argparse.ArgumentParser:
    workspace_default = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Build the rebuild Arch ISO pipeline artifact.")
    parser.add_argument(
        "--workspace",
        type=Path,
        default=workspace_default,
        help="Repository workspace root.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=workspace_default / "rebuild" / "dist" / "iso",
        help="Directory for final ISO artifacts and manifest.",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=workspace_default / "rebuild" / "dist" / "tmp-iso-build",
        help="Working directory for downloaded ISO and payload staging.",
    )
    parser.add_argument(
        "--artifact-prefix",
        default="omarchy-rebuild",
        help="Prefix used for output ISO naming.",
    )
    parser.add_argument(
        "--mirror-url",
        default=ARCH_MIRROR_DEFAULT,
        help="Arch mirror directory for the pinned supported source ISO.",
    )
    parser.add_argument(
        "--release-version",
        required=True,
        help="Explicit semantic product version in X.Y.Z form.",
    )
    parser.add_argument(
        "--release-tag",
        required=True,
        help="Immutable release tag paired with this artifact.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate payload and manifest without downloading/building a real ISO.",
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
