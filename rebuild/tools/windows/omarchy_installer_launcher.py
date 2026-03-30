"""Windows launcher entrypoint packaged into OmarchyInstaller.exe."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def bundled_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS"))  # type: ignore[arg-type]
    return Path(__file__).resolve().parents[3]


def powershell_script() -> Path:
    return bundled_root() / "windows-prep.ps1"


def build_command(script_path: Path, passthrough_args: list[str]) -> list[str]:
    return [
        "powershell.exe",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(script_path),
        *passthrough_args,
    ]


def main() -> int:
    script_path = powershell_script()
    if not script_path.exists():
        print(f"Missing bundled script: {script_path}", file=sys.stderr)
        return 2

    command = build_command(script_path, sys.argv[1:])
    env = dict(os.environ)
    env.setdefault("OMARCHY_INSTALLER_WRAPPED", "1")

    completed = subprocess.run(command, env=env)
    return int(completed.returncode)


if __name__ == "__main__":
    raise SystemExit(main())

