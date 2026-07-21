from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from rebuild.installer.platforms.installed_system.first_login import (
    FirstLoginContext,
    FirstLoginError,
    run_first_login,
)


SCRIPT = b"#!/usr/bin/env bash\nset -euo pipefail\nprintf 'interactive upstream output\\n'\n"
GET_EUID = getattr(os, "geteuid", lambda: -1)


class StaticDownloader:
    def __init__(self, content: bytes = SCRIPT) -> None:
        self.content = content

    def download(self, url: str, destination: Path) -> dict[str, str]:
        destination.write_bytes(self.content)
        return {"x-upstream-commit": "abc1234"}


class RecordingRunner:
    def __init__(self, *, installer_returncode: int = 0) -> None:
        self.installer_returncode = installer_returncode
        self.commands: list[list[str]] = []

    def run(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        returncode = self.installer_returncode if command[0] == "script" else 0
        if command[0] == "script":
            transcript = Path(command[command.index("--log-out") + 1])
            transcript.write_text("interactive upstream output\n", encoding="utf-8")
        return subprocess.CompletedProcess(command, returncode, "", "")


class PtyThenMarkerRunner:
    def run(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        if command[0] == "script":
            return subprocess.run(command, check=False, text=True)
        return subprocess.CompletedProcess(command, 0, "", "")


def context(**overrides: object) -> FirstLoginContext:
    values: dict[str, object] = {
        "username": "alice", "uid": 1000, "is_tty": True,
        "is_wsl": False, "is_live_iso": False, "install_marker_exists": True,
    }
    values.update(overrides)
    return FirstLoginContext(**values)  # type: ignore[arg-type]


def pairing(path: Path, *, digest: str | None = None) -> Path:
    payload = {
        "url": "https://omarchy.org/install",
        "expected_sha256": digest or hashlib.sha256(SCRIPT).hexdigest(),
        "upstream_version": "paired-version",
        "release_tag": "v1.0.0",
        "build_commit": "0123456789abcdef",
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_normal_user_flow_downloads_verifies_transcripts_and_marks(tmp_path: Path) -> None:
    runner = RecordingRunner()
    messages: list[str] = []
    result = run_first_login(
        pairing_path=pairing(tmp_path / "pairing.json"),
        context=context(),
        downloader=StaticDownloader(),
        runner=runner,
        env={"HOME": str(tmp_path)},
        input_func=lambda _prompt: "RUN OMARCHY",
        output_func=messages.append,
    )
    assert result.status == "completed"
    state = json.loads(Path(result.state_path).read_text(encoding="utf-8"))
    assert state["status"] == "completed"
    assert state["upstream_commit"] == "abc1234"
    assert state["sha256"] == hashlib.sha256(SCRIPT).hexdigest()
    assert runner.commands[0][0] == "script"
    assert runner.commands[1] == ["sudo", "/usr/local/bin/omarchy-stage-marker", "omarchy-complete"]
    assert "Source: https://omarchy.org/install" in messages[-1]


def test_partial_attempt_never_retries_without_explicit_flag(tmp_path: Path) -> None:
    state_root = tmp_path / ".local/state/omarchy-installer"
    state_root.mkdir(parents=True)
    (state_root / "state.json").write_text('{"status":"failed","reason":"prior"}', encoding="utf-8")
    runner = RecordingRunner()
    messages: list[str] = []
    with pytest.raises(FirstLoginError, match="--retry"):
        run_first_login(
            pairing_path=pairing(tmp_path / "pairing.json"), context=context(),
            downloader=StaticDownloader(), runner=runner, env={"HOME": str(tmp_path)},
            input_func=lambda _prompt: "RUN OMARCHY", output_func=messages.append,
        )
    assert runner.commands == []
    assert "prior" in messages[0]


def test_explicit_retry_displays_prior_state_then_runs_once(tmp_path: Path) -> None:
    state_root = tmp_path / ".local/state/omarchy-installer"
    state_root.mkdir(parents=True)
    (state_root / "state.json").write_text('{"status":"failed","reason":"prior"}', encoding="utf-8")
    runner = RecordingRunner()
    messages: list[str] = []
    result = run_first_login(
        pairing_path=pairing(tmp_path / "pairing.json"), context=context(),
        downloader=StaticDownloader(), runner=runner, env={"HOME": str(tmp_path)},
        retry=True, input_func=lambda _prompt: "RUN OMARCHY", output_func=messages.append,
    )
    assert result.status == "completed"
    assert "prior" in messages[0]
    assert sum(command[0] == "script" for command in runner.commands) == 1
    combined = Path(result.state_path).read_text() + Path(result.transcript_path).read_text()
    assert "RUN OMARCHY" not in combined


@pytest.mark.parametrize("override", [
    {"uid": 0}, {"is_tty": False}, {"is_wsl": True},
    {"is_live_iso": True}, {"install_marker_exists": False},
])
def test_context_policy_fails_closed(tmp_path: Path, override: dict[str, object]) -> None:
    with pytest.raises(FirstLoginError):
        run_first_login(pairing_path=pairing(tmp_path / "pairing.json"), context=context(**override), env={"HOME": str(tmp_path)})


def test_hash_mismatch_records_failure_without_execution(tmp_path: Path) -> None:
    runner = RecordingRunner()
    with pytest.raises(FirstLoginError, match="SHA256"):
        run_first_login(
            pairing_path=pairing(tmp_path / "pairing.json", digest="f" * 64),
            context=context(), downloader=StaticDownloader(), runner=runner,
            env={"HOME": str(tmp_path)}, input_func=lambda _prompt: "RUN OMARCHY",
        )
    state = json.loads((tmp_path / ".local/state/omarchy-installer/state.json").read_text())
    assert state["reason"] == "sha256-mismatch"
    assert runner.commands == []


@pytest.mark.skipif(os.name == "nt" or shutil.which("script") is None or GET_EUID() == 0, reason="requires a non-root Unix PTY host")
def test_pseudo_terminal_preserves_installer_output(tmp_path: Path) -> None:
    result = run_first_login(
        pairing_path=pairing(tmp_path / "pairing.json"), context=context(uid=GET_EUID()),
        downloader=StaticDownloader(), runner=PtyThenMarkerRunner(),
        env={"HOME": str(tmp_path), "USER": os.environ.get("USER", "tester")},
        input_func=lambda _prompt: "RUN OMARCHY",
    )
    assert "interactive upstream output" in Path(result.transcript_path).read_text(encoding="utf-8")
