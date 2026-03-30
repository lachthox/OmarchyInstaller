"""First-boot Omarchy wrapper and timing policy for installed systems."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping, Protocol

from .post_install import (
    BootstrapHealthResult,
    BootstrapContract,
    PostInstallNormalizationResult,
    build_bootstrap_contract,
    evaluate_bootstrap_health,
    normalize_boot_policy,
)

DEFAULT_INSTALL_SUCCESS_MARKER = Path("/var/lib/omarchy/install/install-success.json")
DEFAULT_FIRSTBOOT_COMPLETION_MARKER = Path("/var/lib/omarchy/firstboot/completed.json")
DEFAULT_FIRSTBOOT_ATTEMPT_LOG = Path("/var/lib/omarchy/firstboot/attempt.log.jsonl")
DEFAULT_OMARCHY_INSTALL_COMMAND = "curl -fsSL https://omarchy.org/install | bash"
DEFAULT_BOOTSTRAP_URL = "https://omarchy.org/install"
DEFAULT_BOOTSTRAP_REPO = "lachthox/OmarchyInstaller"
DEFAULT_BOOTSTRAP_ROOT = Path("/opt/omarchy-setup")


class FirstBootPolicyError(RuntimeError):
    """Raised when first-boot gating or execution cannot complete safely."""


class CommandRunner(Protocol):
    """Command runner interface for deterministic command execution in tests."""

    def run(self, command: list[str]) -> subprocess.CompletedProcess[str]: ...


class SubprocessCommandRunner:
    """Command runner backed by subprocess without shell interpolation."""

    def run(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )


@dataclass(frozen=True, slots=True)
class FirstBootRuntimeContext:
    platform: str
    is_linux: bool
    os_release_id: str
    is_wsl: bool
    is_live_iso: bool
    pid1_comm: str
    login_users: tuple[str, ...]
    install_marker_exists: bool
    completion_marker_exists: bool

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["login_users"] = list(self.login_users)
        return payload


@dataclass(frozen=True, slots=True)
class FirstBootExecutionResult:
    status: str
    generated_at_utc: str
    command: tuple[str, ...]
    runtime_context: FirstBootRuntimeContext
    can_proceed: bool
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    executed: bool
    exit_code: int
    install_marker_path: str
    completion_marker_path: str
    attempt_log_path: str
    bootstrap_health: BootstrapHealthResult
    post_install_normalization: PostInstallNormalizationResult | None

    def to_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["command"] = list(self.command)
        payload["blockers"] = list(self.blockers)
        payload["warnings"] = list(self.warnings)
        payload["runtime_context"] = self.runtime_context.to_dict()
        payload["bootstrap_health"] = self.bootstrap_health.to_dict()
        payload["post_install_normalization"] = (
            self.post_install_normalization.to_dict() if self.post_install_normalization is not None else None
        )
        return payload


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _read_json_dict(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _marker_username(install_marker_path: Path) -> str:
    payload = _read_json_dict(install_marker_path)
    username = str(payload.get("username", "")).strip()
    if username and username.lower() != "root":
        return username
    return ""


def _read_os_release_id(path: Path) -> str:
    content = _read_text(path)
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() != "ID":
            continue
        return value.strip().strip('"').strip("'").lower()
    return ""


def _is_live_iso_environment(proc_cmdline: str) -> bool:
    if Path("/run/archiso").exists():
        return True
    haystack = proc_cmdline.lower()
    return any(marker in haystack for marker in ("archisobasedir=", "archisolabel=", "boot=live"))


def _is_wsl_environment(env: Mapping[str, str], proc_osrelease: str, proc_version: str) -> bool:
    if env.get("WSL_DISTRO_NAME") or env.get("WSL_INTEROP"):
        return True
    text = f"{proc_osrelease}\n{proc_version}".lower()
    return "microsoft" in text or "wsl" in text


def _discover_login_users(runner: CommandRunner, env: Mapping[str, str]) -> tuple[str, ...]:
    users: list[str] = []
    try:
        completed = runner.run(["loginctl", "list-users", "--no-legend"])
    except OSError:
        completed = subprocess.CompletedProcess(args=["loginctl"], returncode=127, stdout="", stderr="")

    if completed.returncode == 0:
        for raw in completed.stdout.splitlines():
            parts = raw.split()
            if len(parts) < 2:
                continue
            try:
                uid = int(parts[0])
            except ValueError:
                continue
            user = parts[1].strip()
            if uid >= 1000 and user and user != "nobody":
                users.append(user)
    if users:
        return tuple(sorted(set(users)))

    # Fallback for constrained environments where logind isn't available.
    fallback_user = env.get("SUDO_USER") or env.get("USER") or env.get("USERNAME") or ""
    fallback_user = fallback_user.strip()
    if fallback_user and fallback_user.lower() != "root":
        return (fallback_user,)
    return tuple()


def detect_runtime_context(
    *,
    runner: CommandRunner | None = None,
    install_marker_path: str | Path = DEFAULT_INSTALL_SUCCESS_MARKER,
    completion_marker_path: str | Path = DEFAULT_FIRSTBOOT_COMPLETION_MARKER,
    env: Mapping[str, str] | None = None,
) -> FirstBootRuntimeContext:
    """Discover local runtime context for first-boot timing policy decisions."""
    active_runner = runner or SubprocessCommandRunner()
    active_env = dict(os.environ if env is None else env)

    platform = sys.platform.lower()
    is_linux = platform.startswith("linux")
    os_release_id = _read_os_release_id(Path("/etc/os-release")) if is_linux else ""
    proc_cmdline = _read_text(Path("/proc/cmdline")) if is_linux else ""
    proc_osrelease = _read_text(Path("/proc/sys/kernel/osrelease")) if is_linux else ""
    proc_version = _read_text(Path("/proc/version")) if is_linux else ""
    pid1_comm = _read_text(Path("/proc/1/comm")).lower() if is_linux else ""

    return FirstBootRuntimeContext(
        platform=platform,
        is_linux=is_linux,
        os_release_id=os_release_id,
        is_wsl=_is_wsl_environment(active_env, proc_osrelease, proc_version) if is_linux else False,
        is_live_iso=_is_live_iso_environment(proc_cmdline) if is_linux else False,
        pid1_comm=pid1_comm,
        login_users=_discover_login_users(active_runner, active_env) if is_linux else tuple(),
        install_marker_exists=Path(install_marker_path).exists(),
        completion_marker_exists=Path(completion_marker_path).exists(),
    )


def evaluate_firstboot_timing_policy(context: FirstBootRuntimeContext) -> tuple[bool, tuple[str, ...], tuple[str, ...]]:
    """Evaluate mandatory post-install timing constraints for Omarchy first boot."""
    blockers: list[str] = []
    warnings: list[str] = []

    if not context.is_linux:
        blockers.append(f"unsupported platform '{context.platform}'")
    if context.os_release_id and context.os_release_id != "arch":
        blockers.append(f"unsupported installed OS id '{context.os_release_id}'")
    if context.is_wsl:
        blockers.append("WSL environment detected")
    if context.is_live_iso:
        blockers.append("live ISO environment detected")
    if context.pid1_comm != "systemd":
        blockers.append("system is not booted under systemd PID 1")
    if not context.install_marker_exists:
        blockers.append("install-success marker is missing")
    if not context.login_users:
        blockers.append("no logged-in non-root user session detected")
    if context.completion_marker_exists:
        warnings.append("first-boot completion marker already exists")

    return (len(blockers) == 0, tuple(blockers), tuple(warnings))


def assert_firstboot_ready(context: FirstBootRuntimeContext) -> None:
    """Fail closed when first-boot timing policy requirements are not satisfied."""
    can_proceed, blockers, _ = evaluate_firstboot_timing_policy(context)
    if can_proceed:
        return
    raise FirstBootPolicyError("; ".join(blockers))


def _append_attempt_event(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
    except OSError as exc:
        raise FirstBootPolicyError(f"Unable to write firstboot attempt log: {path}") from exc


def _write_completion_marker(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        raise FirstBootPolicyError(f"Unable to write firstboot completion marker: {path}") from exc


def run_firstboot_handoff(
    *,
    command: str = DEFAULT_OMARCHY_INSTALL_COMMAND,
    bootstrap_url: str = DEFAULT_BOOTSTRAP_URL,
    bootstrap_repo: str = DEFAULT_BOOTSTRAP_REPO,
    bootstrap_root: str | Path = DEFAULT_BOOTSTRAP_ROOT,
    install_marker_path: str | Path = DEFAULT_INSTALL_SUCCESS_MARKER,
    completion_marker_path: str | Path = DEFAULT_FIRSTBOOT_COMPLETION_MARKER,
    attempt_log_path: str | Path = DEFAULT_FIRSTBOOT_ATTEMPT_LOG,
    efi_mount: str | Path | None = None,
    runner: CommandRunner | None = None,
    context: FirstBootRuntimeContext | None = None,
) -> FirstBootExecutionResult:
    """Run Omarchy first-boot handoff when timing policy constraints are satisfied."""
    if not command.strip():
        raise ValueError("command must not be empty")

    active_runner = runner or SubprocessCommandRunner()
    install_marker = Path(install_marker_path)
    completion_marker = Path(completion_marker_path)
    attempt_log = Path(attempt_log_path)
    bootstrap_contract = build_bootstrap_contract(
        bootstrap_url=bootstrap_url,
        bootstrap_repo=bootstrap_repo,
        bootstrap_root=bootstrap_root,
    )

    runtime_context = context or detect_runtime_context(
        runner=active_runner,
        install_marker_path=install_marker,
        completion_marker_path=completion_marker,
    )
    marker_username = _marker_username(install_marker)
    can_proceed, blockers, warnings = evaluate_firstboot_timing_policy(runtime_context)
    blockers_list = list(blockers)
    warnings_list = list(warnings)
    no_login_blocker = "no logged-in non-root user session detected"
    if marker_username and no_login_blocker in blockers_list:
        blockers_list = [blocker for blocker in blockers_list if blocker != no_login_blocker]
        warnings_list.append(
            f"no logged-in session detected; falling back to install marker username '{marker_username}'"
        )
    blockers = tuple(blockers_list)
    warnings = tuple(warnings_list)
    can_proceed = len(blockers) == 0
    bootstrap_health = evaluate_bootstrap_health(bootstrap_contract)
    can_proceed = can_proceed and bootstrap_health.can_proceed
    blockers = tuple([*blockers, *bootstrap_health.blockers])
    warnings = tuple([*warnings, *bootstrap_health.warnings])

    execution_user = runtime_context.login_users[0] if runtime_context.login_users else marker_username
    if execution_user:
        command_list = ("su", "-l", execution_user, "-c", command)
    else:
        command_list = ("bash", "-lc", command)
    if runtime_context.completion_marker_exists:
        return FirstBootExecutionResult(
            status="already-completed",
            generated_at_utc=_utc_now(),
            command=command_list,
            runtime_context=runtime_context,
            can_proceed=False,
            blockers=tuple(),
            warnings=warnings,
            executed=False,
            exit_code=0,
            install_marker_path=str(install_marker),
            completion_marker_path=str(completion_marker),
            attempt_log_path=str(attempt_log),
            bootstrap_health=bootstrap_health,
            post_install_normalization=None,
        )

    if not can_proceed:
        _append_attempt_event(
            attempt_log,
            {
                "event": "bootstrap_check_failed",
                "timestamp_utc": _utc_now(),
                "blockers": list(blockers),
                "warnings": list(warnings),
                "contract": bootstrap_contract.to_dict(),
            },
        )
        return FirstBootExecutionResult(
            status="blocked",
            generated_at_utc=_utc_now(),
            command=command_list,
            runtime_context=runtime_context,
            can_proceed=False,
            blockers=blockers,
            warnings=warnings,
            executed=False,
            exit_code=3,
            install_marker_path=str(install_marker),
            completion_marker_path=str(completion_marker),
            attempt_log_path=str(attempt_log),
            bootstrap_health=bootstrap_health,
            post_install_normalization=None,
        )

    started_at = _utc_now()
    _append_attempt_event(
        attempt_log,
        {
            "event": "firstboot_start",
            "timestamp_utc": started_at,
            "command": command,
            "execution_user": execution_user,
            "login_users": list(runtime_context.login_users),
            "install_marker_path": str(install_marker),
            "bootstrap_health": bootstrap_health.to_dict(),
        },
    )

    completed = active_runner.run(list(command_list))
    if completed.returncode != 0:
        _append_attempt_event(
            attempt_log,
            {
                "event": "firstboot_failed",
                "timestamp_utc": _utc_now(),
                "returncode": completed.returncode,
                "stderr": completed.stderr.strip(),
                "stdout": completed.stdout.strip(),
            },
        )
        return FirstBootExecutionResult(
            status="failed",
            generated_at_utc=_utc_now(),
            command=command_list,
            runtime_context=runtime_context,
            can_proceed=True,
            blockers=tuple(),
            warnings=warnings,
            executed=True,
            exit_code=completed.returncode,
            install_marker_path=str(install_marker),
            completion_marker_path=str(completion_marker),
            attempt_log_path=str(attempt_log),
            bootstrap_health=bootstrap_health,
            post_install_normalization=None,
        )

    post_install_normalization = normalize_boot_policy(
        efi_mount=efi_mount,
        runner=active_runner,
    )
    _append_attempt_event(
        attempt_log,
        {
            "event": "post_install_normalization",
            "timestamp_utc": _utc_now(),
            "result": post_install_normalization.to_dict(),
        },
    )
    if not post_install_normalization.can_proceed:
        _append_attempt_event(
            attempt_log,
            {
                "event": "firstboot_failed",
                "timestamp_utc": _utc_now(),
                "reason": "post-install normalization blocked",
                "blockers": list(post_install_normalization.blockers),
            },
        )
        return FirstBootExecutionResult(
            status="failed",
            generated_at_utc=_utc_now(),
            command=command_list,
            runtime_context=runtime_context,
            can_proceed=False,
            blockers=post_install_normalization.blockers,
            warnings=warnings,
            executed=True,
            exit_code=4,
            install_marker_path=str(install_marker),
            completion_marker_path=str(completion_marker),
            attempt_log_path=str(attempt_log),
            bootstrap_health=bootstrap_health,
            post_install_normalization=post_install_normalization,
        )

    completion_payload: dict[str, object] = {
        "schema_version": "1.0.0",
        "completed_at_utc": _utc_now(),
        "omarchy_timing_contract": "post-install-only",
        "command": command,
        "execution_user": execution_user,
        "login_users": list(runtime_context.login_users),
        "install_marker_path": str(install_marker),
        "bootstrap_contract": bootstrap_contract.to_dict(),
        "post_install_normalization": post_install_normalization.to_dict(),
    }
    _write_completion_marker(completion_marker, completion_payload)
    _append_attempt_event(
        attempt_log,
        {
            "event": "firstboot_completed",
            "timestamp_utc": _utc_now(),
            "completion_marker_path": str(completion_marker),
            "post_install_normalization": post_install_normalization.to_dict(),
        },
    )

    return FirstBootExecutionResult(
        status="completed",
        generated_at_utc=_utc_now(),
        command=command_list,
        runtime_context=runtime_context,
        can_proceed=True,
        blockers=tuple(),
        warnings=warnings,
        executed=True,
        exit_code=0,
        install_marker_path=str(install_marker),
        completion_marker_path=str(completion_marker),
        attempt_log_path=str(attempt_log),
        bootstrap_health=bootstrap_health,
        post_install_normalization=post_install_normalization,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Omarchy first-boot timing policy handoff.")
    parser.add_argument(
        "--bootstrap-url",
        default=DEFAULT_BOOTSTRAP_URL,
        help="Bootstrap URL contract used to validate launch provenance.",
    )
    parser.add_argument(
        "--bootstrap-repo",
        default=DEFAULT_BOOTSTRAP_REPO,
        help="Bootstrap repository contract used to validate launch provenance.",
    )
    parser.add_argument(
        "--bootstrap-root",
        default=str(DEFAULT_BOOTSTRAP_ROOT),
        help="Bootstrap install root used to validate expected handoff files.",
    )
    parser.add_argument(
        "--install-marker",
        default=str(DEFAULT_INSTALL_SUCCESS_MARKER),
        help="Path to install-success marker generated by the install layer.",
    )
    parser.add_argument(
        "--completion-marker",
        default=str(DEFAULT_FIRSTBOOT_COMPLETION_MARKER),
        help="Path to write once Omarchy first-boot handoff succeeds.",
    )
    parser.add_argument(
        "--attempt-log",
        default=str(DEFAULT_FIRSTBOOT_ATTEMPT_LOG),
        help="JSONL log path for first-boot wrapper events.",
    )
    parser.add_argument(
        "--efi-mount",
        default="",
        help="EFI mount point used for post-install boot policy normalization.",
    )
    parser.add_argument(
        "--command",
        default=DEFAULT_OMARCHY_INSTALL_COMMAND,
        help="Shell command to launch Omarchy bootstrap.",
    )
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    result = run_firstboot_handoff(
        command=args.command,
        bootstrap_url=args.bootstrap_url,
        bootstrap_repo=args.bootstrap_repo,
        bootstrap_root=args.bootstrap_root,
        install_marker_path=args.install_marker,
        completion_marker_path=args.completion_marker,
        attempt_log_path=args.attempt_log,
        efi_mount=args.efi_mount or None,
    )
    print(json.dumps(result.to_dict(), indent=2))
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
