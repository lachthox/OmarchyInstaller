"""Fail-closed deployment and validation of installed-system assets."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import py_compile
import shutil
import subprocess
from typing import Any, Protocol

from .boot_guardian_state import BootGuardianExpectedState


INSTALL_SUCCESS_PATH = Path("var/lib/omarchy/install/install-success.json")
EXPECTED_STATE_PATH = Path("var/lib/omarchy/boot/expected-state.json")
RUNTIME_ROOT = Path("opt/omarchy-installer")


class TargetFinalizationError(RuntimeError):
    """Raised when the installed target does not satisfy every invariant."""


class CommandRunner(Protocol):
    def run(self, command: list[str]) -> subprocess.CompletedProcess[str]: ...


class SubprocessCommandRunner:
    def run(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(command, capture_output=True, text=True, check=False)


@dataclass(frozen=True, slots=True)
class TargetMachineState:
    username: str
    disk_guid: str
    root_partuuid: str
    root_fs_uuid: str
    luks_uuid: str
    mapper_name: str = "omarchy-cryptroot"
    efi_mount: str = "/boot"


@dataclass(frozen=True, slots=True)
class TargetFinalizationResult:
    status: str
    target_root: str
    deployed_paths: tuple[str, ...]
    validated_invariants: tuple[str, ...]
    enabled_units: tuple[str, ...]
    stage_markers: tuple[str, ...]
    success_marker: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["deployed_paths"] = list(self.deployed_paths)
        payload["validated_invariants"] = list(self.validated_invariants)
        payload["enabled_units"] = list(self.enabled_units)
        payload["stage_markers"] = list(self.stage_markers)
        return payload


def _target(root: Path, absolute: str | Path) -> Path:
    relative = Path(str(absolute).lstrip("/\\"))
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise TargetFinalizationError(f"Target path escapes mounted root: {absolute}") from exc
    return candidate


def _copy(source: Path, destination: Path, *, executable: bool = False) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    destination.chmod(0o755 if executable else 0o644)


def _write_atomic(path: Path, payload: dict[str, Any], *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.chmod(mode)
    os.replace(temporary, path)


def deploy_target_assets(
    target_root: str | Path,
    machine: TargetMachineState,
    *,
    source_root: str | Path | None = None,
) -> tuple[str, ...]:
    """Install runtime, wrappers, units, state, directories, and help command."""
    root = Path(target_root).resolve()
    if not root.is_dir() or root == Path(root.anchor):
        raise TargetFinalizationError(f"Unsafe or missing target root: {root}")
    rebuild_root = Path(source_root).resolve() if source_root else Path(__file__).resolve().parents[3]
    installer_source = rebuild_root / "installer"
    assets = rebuild_root / "assets"
    if not installer_source.is_dir() or not assets.is_dir():
        raise TargetFinalizationError(f"Installed-system source assets are incomplete: {rebuild_root}")

    runtime = _target(root, RUNTIME_ROOT)
    if runtime.exists():
        shutil.rmtree(runtime)
    shutil.copytree(installer_source, runtime / "installer", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    for path in (runtime, runtime / "installer"):
        path.chmod(0o755)

    mappings = {
        assets / "scripts" / "firstboot-wrapper.sh": ("/usr/local/bin/omarchy-firstboot", True),
        assets / "scripts" / "boot-guardian.sh": ("/usr/local/bin/omarchy-boot-guardian", True),
        assets / "scripts" / "omarchy-boot-check.sh": ("/usr/local/bin/omarchy-boot-check", True),
        assets / "scripts" / "omarchy-boot-repair.sh": ("/usr/local/bin/omarchy-boot-repair", True),
        assets / "services" / "omarchy-firstboot.service": ("/usr/lib/systemd/system/omarchy-firstboot.service", False),
        assets / "services" / "boot-guardian.service": ("/usr/lib/systemd/system/omarchy-boot-guardian.service", False),
    }
    deployed = [str(runtime / "installer")]
    for source, (destination, executable) in mappings.items():
        target = _target(root, destination)
        _copy(source, target, executable=executable)
        deployed.append(str(target))

    help_path = _target(root, "/usr/local/bin/omarchy-install-help")
    help_path.parent.mkdir(parents=True, exist_ok=True)
    help_path.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        "printf '%s\\n' 'Omarchy install status:'\n"
        "for f in /var/lib/omarchy/install/install-success.json "
        "/var/lib/omarchy/firstboot/state.json /var/lib/omarchy/boot/expected-state.json; do\n"
        "  [[ -r \"$f\" ]] && { printf '\\n%s\\n' \"$f\"; sed -n '1,160p' \"$f\"; }\n"
        "done\n",
        encoding="utf-8",
    )
    help_path.chmod(0o755)
    deployed.append(str(help_path))

    for relative in (
        "var/lib/omarchy/install",
        "var/lib/omarchy/firstboot",
        "var/lib/omarchy/boot",
        "var/log/omarchy",
        "var/lib/omarchy/diagnostics",
    ):
        directory = _target(root, relative)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)
        deployed.append(str(directory))

    expected = BootGuardianExpectedState(efi_mount=machine.efi_mount).to_dict()
    expected["machine"] = asdict(machine)
    _write_atomic(_target(root, EXPECTED_STATE_PATH), expected)
    deployed.append(str(_target(root, EXPECTED_STATE_PATH)))
    return tuple(deployed)


def _require(condition: bool, message: str, validated: list[str], label: str) -> None:
    if not condition:
        raise TargetFinalizationError(message)
    validated.append(label)


def _is_executable(path: Path) -> bool:
    if not path.is_file():
        return False
    if os.name == "nt":
        return path.read_bytes().startswith(b"#!")
    return bool(path.stat().st_mode & 0o111)


def validate_target_root(target_root: str | Path, machine: TargetMachineState) -> tuple[str, ...]:
    """Validate target contents without trusting service enablement or marker files."""
    root = Path(target_root).resolve()
    validated: list[str] = []
    _require(any(_target(root, "/boot").glob("vmlinuz-*")), "Target kernel is missing", validated, "kernel")
    _require(any(_target(root, "/boot").glob("initramfs-*.img")), "Target initramfs is missing", validated, "initramfs")

    fstab = _target(root, "/etc/fstab").read_text(encoding="utf-8") if _target(root, "/etc/fstab").is_file() else ""
    _require("btrfs" in fstab and " / " in fstab, "fstab lacks the Btrfs root mount", validated, "fstab-root")
    _require(" /boot " in fstab, "fstab lacks the EFI /boot mount", validated, "fstab-efi")
    crypttab_path = _target(root, "/etc/crypttab.initramfs")
    crypttab = crypttab_path.read_text(encoding="utf-8") if crypttab_path.is_file() else ""
    _require(machine.mapper_name in crypttab and machine.luks_uuid in crypttab, "crypttab.initramfs does not match LUKS state", validated, "crypttab")
    mkinit = "\n".join(path.read_text(encoding="utf-8") for path in _target(root, "/etc/mkinitcpio.conf.d").glob("*.conf"))
    _require("sd-encrypt" in mkinit and "btrfs" in mkinit, "initramfs hooks lack sd-encrypt/Btrfs", validated, "initramfs-config")

    passwd = _target(root, "/etc/passwd").read_text(encoding="utf-8") if _target(root, "/etc/passwd").is_file() else ""
    group = _target(root, "/etc/group").read_text(encoding="utf-8") if _target(root, "/etc/group").is_file() else ""
    _require(any(line.startswith(f"{machine.username}:") and ":/home/" in line for line in passwd.splitlines()), "Planned normal user is missing", validated, "normal-user")
    _require(any(line.startswith("wheel:") and machine.username in line.split(":")[-1].split(",") for line in group.splitlines()), "Planned user is not in wheel", validated, "wheel-membership")
    sudo_text = "\n".join(path.read_text(encoding="utf-8") for path in [_target(root, "/etc/sudoers"), *_target(root, "/etc/sudoers.d").glob("*")] if path.is_file())
    _require("%wheel" in sudo_text, "wheel sudo policy is missing", validated, "sudo-policy")
    _require(_target(root, "/etc/systemd/system/multi-user.target.wants/NetworkManager.service").exists(), "NetworkManager is not enabled", validated, "network-manager")

    _require(_target(root, "/boot/EFI/Microsoft/Boot/bootmgfw.efi").is_file(), "Windows EFI loader was not preserved", validated, "windows-efi")
    _require(any(path.is_file() for path in (_target(root, "/boot/EFI/Limine/BOOTX64.EFI"), _target(root, "/boot/EFI/BOOT/BOOTX64.EFI"))), "Limine EFI loader is missing", validated, "limine-efi")
    _require(any(path.is_file() for path in (_target(root, "/boot/limine.conf"), _target(root, "/boot/limine/limine.conf"))), "Limine configuration is missing", validated, "limine-config")

    runtime = _target(root, RUNTIME_ROOT / "installer")
    required_modules = (runtime / "__init__.py", runtime / "platforms/installed_system/firstboot.py", runtime / "platforms/installed_system/boot_guardian.py")
    _require(all(path.is_file() for path in required_modules), "Installed Python runtime modules are incomplete", validated, "python-runtime")
    try:
        for module in required_modules:
            py_compile.compile(str(module), doraise=True)
    except py_compile.PyCompileError as exc:
        raise TargetFinalizationError(f"Installed Python module does not compile: {exc}") from exc
    validated.append("python-compile")

    executable_paths = tuple(_target(root, path) for path in (
        "/usr/local/bin/omarchy-firstboot", "/usr/local/bin/omarchy-boot-guardian",
        "/usr/local/bin/omarchy-boot-check", "/usr/local/bin/omarchy-boot-repair",
        "/usr/local/bin/omarchy-install-help",
    ))
    _require(all(_is_executable(path) for path in executable_paths), "Installed wrappers are missing or not executable", validated, "executables")
    for unit_name in ("omarchy-firstboot.service", "omarchy-boot-guardian.service"):
        unit = _target(root, f"/usr/lib/systemd/system/{unit_name}")
        text = unit.read_text(encoding="utf-8") if unit.is_file() else ""
        starts = [line.split("=", 1)[1].split()[0] for line in text.splitlines() if line.startswith("ExecStart=")]
        _require(bool(starts) and all(_target(root, item).is_file() for item in starts), f"Unit {unit_name} has no valid ExecStart", validated, f"unit:{unit_name}")

    state_path = _target(root, EXPECTED_STATE_PATH)
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        BootGuardianExpectedState.from_dict(state)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise TargetFinalizationError(f"Expected-state JSON is invalid: {exc}") from exc
    _require(state.get("machine") == asdict(machine), "Expected-state JSON is not machine-specific", validated, "expected-state")
    return tuple(validated)


def _run_checked(runner: CommandRunner, command: list[str]) -> None:
    completed = runner.run(command)
    if completed.returncode:
        detail = completed.stderr.strip() or completed.stdout.strip() or "command failed"
        raise TargetFinalizationError(f"{' '.join(command)}: {detail}")


def finalize_target_system(
    target_root: str | Path,
    machine: TargetMachineState,
    *,
    source_root: str | Path | None = None,
    runner: CommandRunner | None = None,
) -> TargetFinalizationResult:
    """Deploy, validate in chroot, enable services, then atomically mark success."""
    root = Path(target_root).resolve()
    deployed = deploy_target_assets(root, machine, source_root=source_root)
    validated = validate_target_root(root, machine)
    active_runner = runner or SubprocessCommandRunner()
    _run_checked(active_runner, ["arch-chroot", str(root), "/usr/bin/env", "PYTHONPATH=/opt/omarchy-installer", "/usr/bin/python", "-c", "import installer.platforms.installed_system.firstboot; import installer.platforms.installed_system.boot_guardian"])
    _run_checked(active_runner, ["systemd-analyze", "verify", f"--root={root}", "omarchy-firstboot.service", "omarchy-boot-guardian.service"])

    enabled: list[str] = []
    wants = _target(root, "/etc/systemd/system/multi-user.target.wants")
    wants.mkdir(parents=True, exist_ok=True)
    for unit in ("omarchy-firstboot.service", "omarchy-boot-guardian.service"):
        link = wants / unit
        if link.exists() or link.is_symlink():
            link.unlink()
        if os.name == "nt":  # Windows test hosts cannot create symlinks without elevation.
            link.write_text(f"/usr/lib/systemd/system/{unit}\n", encoding="utf-8")
        else:
            link.symlink_to(Path("/usr/lib/systemd/system") / unit)
        enabled.append(unit)

    marker = _target(root, INSTALL_SUCCESS_PATH)
    marker_payload = {
        "schema_version": "1.0.0",
        "status": "success",
        "completed_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "machine": asdict(machine),
        "validated_invariants": list(validated),
        "enabled_units": enabled,
    }
    stage_markers: list[str] = []
    for name in ("base-install-complete.json", "target-finalization-complete.json"):
        stage_marker = _target(root, Path("var/lib/omarchy/install") / name)
        _write_atomic(stage_marker, {**marker_payload, "stage": name.removesuffix(".json")})
        stage_markers.append(str(stage_marker))
    # Omarchy, boot-policy, and overall markers are deliberately owned by later stages.
    _write_atomic(marker, marker_payload)
    return TargetFinalizationResult(
        "completed", str(root), deployed, validated, tuple(enabled), tuple(stage_markers), str(marker)
    )
