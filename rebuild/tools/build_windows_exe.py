#!/usr/bin/env python3
"""Build OmarchyInstaller.exe via PyInstaller with version stamping."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class VersionStamp:
    file_version: str
    product_version: str
    dotted_quad: str


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


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


def detect_git_tag(workspace: Path) -> str:
    try:
        return run_capture(["git", "-C", str(workspace), "describe", "--tags", "--always", "--dirty"])
    except subprocess.CalledProcessError:
        return "0.0.0-dev"


def normalize_version(raw: str) -> VersionStamp:
    digits = [int(part) for part in re.findall(r"\d+", raw)]
    # Windows VERSIONINFO fields are 16-bit components.
    digits = [max(0, min(part, 65535)) for part in digits]
    while len(digits) < 4:
        digits.append(0)
    digits = digits[:4]
    dotted = ".".join(str(part) for part in digits)
    return VersionStamp(file_version=dotted, product_version=dotted, dotted_quad=dotted)


def compute_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_paths(workspace: Path) -> tuple[Path, Path]:
    launcher = workspace / "rebuild" / "tools" / "windows" / "omarchy_installer_launcher.py"
    windows_prep = workspace / "windows-prep.ps1"
    missing = [str(path) for path in (launcher, windows_prep) if not path.exists()]
    if missing:
        raise RuntimeError(f"Missing required packaging input paths: {missing}")
    return launcher, windows_prep


def write_version_file(path: Path, stamp: VersionStamp) -> None:
    content = (
        "VSVersionInfo(\n"
        "  ffi=FixedFileInfo(\n"
        f"    filevers=({stamp.file_version.replace('.', ', ')}),\n"
        f"    prodvers=({stamp.product_version.replace('.', ', ')}),\n"
        "    mask=0x3f,\n"
        "    flags=0x0,\n"
        "    OS=0x40004,\n"
        "    fileType=0x1,\n"
        "    subtype=0x0,\n"
        "    date=(0, 0)\n"
        "  ),\n"
        "  kids=[\n"
        "    StringFileInfo([\n"
        "      StringTable('040904B0', [\n"
        "        StringStruct('CompanyName', 'OmarchyInstaller'),\n"
        "        StringStruct('FileDescription', 'Omarchy Installer Windows Launcher'),\n"
        "        StringStruct('FileVersion', '"
        + stamp.file_version
        + "'),\n"
        "        StringStruct('InternalName', 'OmarchyInstaller'),\n"
        "        StringStruct('OriginalFilename', 'OmarchyInstaller.exe'),\n"
        "        StringStruct('ProductName', 'OmarchyInstaller'),\n"
        "        StringStruct('ProductVersion', '"
        + stamp.product_version
        + "')\n"
        "      ])\n"
        "    ]),\n"
        "    VarFileInfo([VarStruct('Translation', [1033, 1200])])\n"
        "  ]\n"
        ")\n"
    )
    path.write_text(content, encoding="utf-8")


def write_manifest(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def run_pipeline(args: argparse.Namespace) -> int:
    workspace = args.workspace.resolve()
    output_dir = args.output_dir.resolve()
    work_dir = args.work_dir.resolve()
    launcher, windows_prep = ensure_paths(workspace)

    output_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    commit_sha = detect_git_commit(workspace)
    tag_value = detect_git_tag(workspace)
    stamp = normalize_version(tag_value)

    payload_dir = work_dir / "payload"
    build_dir = work_dir / "build"
    spec_dir = work_dir / "spec"
    if payload_dir.exists():
        shutil.rmtree(payload_dir)
    payload_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(windows_prep, payload_dir / "windows-prep.ps1")

    version_file = work_dir / "version_info.txt"
    write_version_file(version_file, stamp)

    output_exe = output_dir / "OmarchyInstaller.exe"
    if args.dry_run:
        output_exe.write_bytes(b"dry-run-exe")
    else:
        run_command(
            [
                sys.executable,
                "-m",
                "PyInstaller",
                "--noconfirm",
                "--clean",
                "--onefile",
                "--name",
                "OmarchyInstaller",
                "--distpath",
                str(output_dir),
                "--workpath",
                str(build_dir),
                "--specpath",
                str(spec_dir),
                "--paths",
                str(workspace / "rebuild"),
                "--version-file",
                str(version_file),
                "--add-data",
                f"{payload_dir / 'windows-prep.ps1'};.",
                str(launcher),
            ],
            cwd=workspace,
        )

    if not output_exe.exists():
        raise RuntimeError(f"PyInstaller did not produce expected executable: {output_exe}")

    sha256_value = compute_sha256(output_exe)
    (output_dir / "OmarchyInstaller.exe.sha256").write_text(
        f"{sha256_value}  OmarchyInstaller.exe\n",
        encoding="utf-8",
    )

    manifest = {
        "schema_version": "1.0.0",
        "generated_at_utc": utc_now(),
        "dry_run": args.dry_run,
        "git_commit": commit_sha,
        "git_tag_source": tag_value,
        "version_stamp": {
            "file_version": stamp.file_version,
            "product_version": stamp.product_version,
            "dotted_quad": stamp.dotted_quad,
        },
        "packaging_inputs": {
            "launcher": str(launcher),
            "windows_prep_script": str(windows_prep),
            "version_file": str(version_file),
        },
        "output": {
            "exe_path": str(output_exe),
            "exe_name": output_exe.name,
            "sha256": sha256_value,
        },
    }
    write_manifest(output_dir / "windows-exe-build-manifest.json", manifest)
    return 0


def build_parser() -> argparse.ArgumentParser:
    workspace_default = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Build OmarchyInstaller.exe with PyInstaller.")
    parser.add_argument(
        "--workspace",
        type=Path,
        default=workspace_default,
        help="Repository workspace root.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=workspace_default / "rebuild" / "dist" / "windows-exe",
        help="Directory for executable artifact outputs.",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=workspace_default / "rebuild" / "dist" / "tmp-windows-exe",
        help="Directory for build intermediates.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate manifests and placeholder outputs without invoking PyInstaller.",
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
