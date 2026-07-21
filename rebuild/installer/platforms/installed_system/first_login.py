"""One-time, normal-user, interactive Omarchy installation launcher."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
from typing import Callable, Mapping, Protocol
from urllib.request import Request, urlopen


DEFAULT_PAIRING_PATH = Path("/var/lib/omarchy/firstboot/release-pairing.json")
DEFAULT_INSTALL_MARKER = Path("/var/lib/omarchy/install/install-success.json")


class FirstLoginError(RuntimeError):
    """Raised when first-login cannot proceed safely."""


class Downloader(Protocol):
    def download(self, url: str, destination: Path) -> Mapping[str, str]: ...


class TerminalRunner(Protocol):
    def run(self, command: list[str]) -> subprocess.CompletedProcess[str]: ...


class UrlDownloader:
    def download(self, url: str, destination: Path) -> Mapping[str, str]:
        request = Request(url, headers={"User-Agent": "OmarchyInstaller/1"})
        with urlopen(request, timeout=30) as response:  # noqa: S310 - URL is root-owned policy.
            destination.write_bytes(response.read())
            return {key.lower(): value for key, value in response.headers.items()}


class InheritedTerminalRunner:
    def run(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(command, check=False, text=True)


@dataclass(frozen=True, slots=True)
class ReleasePairing:
    url: str
    expected_sha256: str
    upstream_version: str
    release_tag: str
    build_commit: str

    @classmethod
    def load(cls, path: Path) -> "ReleasePairing":
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            pairing = cls(**payload)
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            raise FirstLoginError(f"Release-pairing metadata is unavailable: {exc}") from exc
        if not pairing.url.startswith("https://"):
            raise FirstLoginError("Upstream installer URL must use HTTPS.")
        if len(pairing.expected_sha256) != 64 or any(c not in "0123456789abcdef" for c in pairing.expected_sha256):
            raise FirstLoginError("Expected upstream SHA256 is invalid.")
        return pairing


@dataclass(frozen=True, slots=True)
class FirstLoginContext:
    username: str
    uid: int
    is_tty: bool
    is_wsl: bool
    is_live_iso: bool
    install_marker_exists: bool


@dataclass(frozen=True, slots=True)
class FirstLoginResult:
    status: str
    exit_code: int
    state_path: str
    transcript_path: str
    downloaded_path: str
    sha256: str = ""


def detect_context(*, env: Mapping[str, str] | None = None) -> FirstLoginContext:
    active_env = os.environ if env is None else env
    release = ""
    for path in (Path("/proc/sys/kernel/osrelease"), Path("/proc/version")):
        try:
            release += path.read_text(encoding="utf-8")
        except OSError:
            pass
    cmdline = ""
    try:
        cmdline = Path("/proc/cmdline").read_text(encoding="utf-8")
    except OSError:
        pass
    username = active_env.get("USER", "").strip()
    uid = os.geteuid() if hasattr(os, "geteuid") else -1
    return FirstLoginContext(
        username=username,
        uid=uid,
        is_tty=sys.stdin.isatty() and sys.stdout.isatty() and sys.stderr.isatty(),
        is_wsl=bool(active_env.get("WSL_DISTRO_NAME") or "microsoft" in release.lower()),
        is_live_iso=Path("/run/archiso").exists() or "archisolabel=" in cmdline.lower(),
        install_marker_exists=DEFAULT_INSTALL_MARKER.is_file(),
    )


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    os.replace(temporary, path)


def _state_root(env: Mapping[str, str]) -> Path:
    configured = env.get("XDG_STATE_HOME", "").strip()
    if configured:
        return Path(configured) / "omarchy-installer"
    return Path(env.get("HOME", str(Path.home()))) / ".local/state/omarchy-installer"


def _validate_context(context: FirstLoginContext) -> None:
    blockers: list[str] = []
    if context.uid == 0 or not context.username or context.username == "root":
        blockers.append("launcher must run as a normal non-root user")
    if not context.is_tty:
        blockers.append("interactive terminal is required")
    if context.is_wsl:
        blockers.append("WSL is not an installed-system target")
    if context.is_live_iso:
        blockers.append("live ISO execution is forbidden")
    if not context.install_marker_exists:
        blockers.append("base install success marker is missing")
    if blockers:
        raise FirstLoginError("; ".join(blockers))


def run_first_login(
    *,
    pairing_path: str | Path = DEFAULT_PAIRING_PATH,
    context: FirstLoginContext | None = None,
    downloader: Downloader | None = None,
    runner: TerminalRunner | None = None,
    env: Mapping[str, str] | None = None,
    retry: bool = False,
    input_func: Callable[[str], str] = input,
    output_func: Callable[[str], None] = print,
) -> FirstLoginResult:
    """Download, verify, and interactively execute the paired upstream installer."""
    active_env = dict(os.environ if env is None else env)
    runtime_context = context or detect_context(env=active_env)
    _validate_context(runtime_context)
    pairing = ReleasePairing.load(Path(pairing_path))
    state_root = _state_root(active_env)
    state_path = state_root / "state.json"
    transcript = state_root / "transcript.log"
    installer_path = state_root / "upstream-install.sh"

    prior: dict[str, object] = {}
    if state_path.is_file():
        try:
            prior = json.loads(state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise FirstLoginError(f"Prior state is invalid and requires manual recovery: {exc}") from exc
        output_func("Prior Omarchy installer state:\n" + json.dumps(prior, indent=2, sort_keys=True))
        if prior.get("status") == "completed":
            return FirstLoginResult("already-completed", 0, str(state_path), str(transcript), str(installer_path), str(prior.get("sha256", "")))
        if not retry:
            raise FirstLoginError("A partial prior attempt exists; rerun explicitly with --retry after review.")

    state_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    _atomic_json(state_path, {
        "schema_version": "1.0.0", "status": "downloading", "started_at_utc": _utc_now(),
        "username": runtime_context.username, "release_pairing": asdict(pairing), "retry": retry,
    })
    headers = (downloader or UrlDownloader()).download(pairing.url, installer_path)
    installer_path.chmod(0o700)
    digest = hashlib.sha256(installer_path.read_bytes()).hexdigest()
    retrieval = {
        "url": pairing.url,
        "retrieved_at_utc": _utc_now(),
        "sha256": digest,
        "upstream_version": pairing.upstream_version,
        "upstream_commit": headers.get("x-upstream-commit", ""),
        "release_tag": pairing.release_tag,
        "build_commit": pairing.build_commit,
    }
    _atomic_json(state_path, {"schema_version": "1.0.0", "status": "verified", **retrieval})
    if digest != pairing.expected_sha256:
        _atomic_json(state_path, {"schema_version": "1.0.0", "status": "failed", "reason": "sha256-mismatch", **retrieval})
        raise FirstLoginError("Downloaded installer SHA256 does not match release-pairing metadata.")

    output_func(f"Source: {pairing.url}\nSHA256: {digest}\nUpstream: {pairing.upstream_version}")
    if input_func("Type RUN OMARCHY to execute the verified installer: ") != "RUN OMARCHY":
        _atomic_json(state_path, {"schema_version": "1.0.0", "status": "cancelled", **retrieval})
        return FirstLoginResult("cancelled", 2, str(state_path), str(transcript), str(installer_path), digest)

    _atomic_json(state_path, {"schema_version": "1.0.0", "status": "running", **retrieval})
    command_text = f"/usr/bin/bash {shlex.quote(str(installer_path))}"
    command = ["script", "--quiet", "--return", "--log-out", str(transcript), "--command", command_text]
    completed = (runner or InheritedTerminalRunner()).run(command)
    if transcript.exists():
        transcript.chmod(0o600)
    if completed.returncode:
        _atomic_json(state_path, {"schema_version": "1.0.0", "status": "failed", "returncode": completed.returncode, **retrieval})
        return FirstLoginResult("failed", completed.returncode, str(state_path), str(transcript), str(installer_path), digest)

    marker_result = (runner or InheritedTerminalRunner()).run(["sudo", "/usr/local/bin/omarchy-stage-marker", "omarchy-complete"])
    if marker_result.returncode:
        _atomic_json(state_path, {"schema_version": "1.0.0", "status": "failed", "reason": "completion-marker", **retrieval})
        return FirstLoginResult("failed", marker_result.returncode, str(state_path), str(transcript), str(installer_path), digest)
    _atomic_json(state_path, {"schema_version": "1.0.0", "status": "completed", "completed_at_utc": _utc_now(), **retrieval})
    return FirstLoginResult("completed", 0, str(state_path), str(transcript), str(installer_path), digest)


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Run the paired Omarchy installer after normal-user login.")
    parser.add_argument("--pairing", default=str(DEFAULT_PAIRING_PATH))
    parser.add_argument("--retry", action="store_true", help="Explicitly retry after displaying prior state.")
    args = parser.parse_args()
    try:
        return run_first_login(pairing_path=args.pairing, retry=args.retry).exit_code
    except FirstLoginError as exc:
        print(f"Omarchy first-login blocked: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
