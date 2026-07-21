"""Structured, redacted command execution for installer platform adapters."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import os
import subprocess
import threading
import time
from typing import Callable, Mapping, Protocol, Sequence


class ExecutionError(RuntimeError):
    def __init__(self, code: str, message: str, *, result: "CommandResult | None" = None) -> None:
        super().__init__(message)
        self.code = code
        self.result = result


class CommandMode(StrEnum):
    CAPTURED = "captured"
    INHERITED = "inherited"


class CommandState(StrEnum):
    SIMULATED = "simulated"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed-out"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class ProgressEvent:
    event: str
    message: str
    elapsed_seconds: float = 0.0


@dataclass(frozen=True, slots=True)
class CommandRequest:
    argv: tuple[str, ...]
    mode: CommandMode = CommandMode.CAPTURED
    timeout_seconds: float | None = None
    input_text: str | None = None
    environment: Mapping[str, str] | None = None
    cwd: str | None = None
    redacted_values: tuple[str, ...] = ()
    stable_error_code: str = "command-failed"

    def __post_init__(self) -> None:
        if not self.argv or not self.argv[0].strip():
            raise ValueError("command argv cannot be empty")
        if self.timeout_seconds is not None and self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.mode == CommandMode.INHERITED and self.input_text is not None:
            raise ValueError("interactive commands must inherit terminal input")

    def display_argv(self) -> tuple[str, ...]:
        redactions = tuple(value for value in self.redacted_values if value)
        return tuple(
            "<redacted>" if any(secret in argument for secret in redactions) else argument
            for argument in self.argv
        )


@dataclass(frozen=True, slots=True)
class CommandResult:
    request: CommandRequest
    state: CommandState
    returncode: int | None
    stdout: str
    stderr: str
    elapsed_seconds: float

    @property
    def ok(self) -> bool:
        return self.state in {CommandState.SIMULATED, CommandState.SUCCEEDED}


class CommandRunner(Protocol):
    def run(
        self,
        request: CommandRequest,
        *,
        progress: Callable[[ProgressEvent], None] | None = None,
        cancellation: threading.Event | None = None,
    ) -> CommandResult: ...


class SubprocessCommandRunner:
    def __init__(
        self,
        *,
        dry_run: bool = False,
        allowed_commands: Sequence[str] | None = None,
    ) -> None:
        self.dry_run = dry_run
        self.allowed_commands = frozenset(allowed_commands or ())

    def _validate_command(self, request: CommandRequest) -> None:
        executable = os.path.basename(request.argv[0]).casefold()
        allowed = {os.path.basename(item).casefold() for item in self.allowed_commands}
        if allowed and executable not in allowed:
            raise ExecutionError("command-not-allowed", f"command is not allowlisted: {executable}")

    def run(
        self,
        request: CommandRequest,
        *,
        progress: Callable[[ProgressEvent], None] | None = None,
        cancellation: threading.Event | None = None,
    ) -> CommandResult:
        self._validate_command(request)
        started = time.monotonic()
        emit = progress or (lambda _event: None)
        display = " ".join(request.display_argv())

        if cancellation is not None and cancellation.is_set():
            emit(ProgressEvent("cancelled", f"Cancelled before start: {display}"))
            return CommandResult(request, CommandState.CANCELLED, None, "", "", 0.0)
        if self.dry_run:
            emit(ProgressEvent("simulated", f"SIMULATED: {display}"))
            return CommandResult(request, CommandState.SIMULATED, None, "", "", 0.0)

        emit(ProgressEvent("started", f"Started: {display}"))
        captured = request.mode == CommandMode.CAPTURED
        try:
            completed = subprocess.run(
                list(request.argv),
                cwd=request.cwd,
                env=dict(request.environment) if request.environment is not None else None,
                input=request.input_text,
                text=True,
                capture_output=captured,
                timeout=request.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            elapsed = time.monotonic() - started
            emit(ProgressEvent("timed-out", f"Timed out: {display}", elapsed))
            return CommandResult(
                request,
                CommandState.TIMED_OUT,
                None,
                str(exc.stdout or ""),
                str(exc.stderr or ""),
                elapsed,
            )

        elapsed = time.monotonic() - started
        state = CommandState.SUCCEEDED if completed.returncode == 0 else CommandState.FAILED
        emit(ProgressEvent(state.value, f"{state.value}: {display}", elapsed))
        return CommandResult(
            request,
            state,
            completed.returncode,
            completed.stdout or "",
            completed.stderr or "",
            elapsed,
        )


class WindowsCommandRunner(SubprocessCommandRunner):
    pass


class LinuxCommandRunner(SubprocessCommandRunner):
    pass


class InteractiveCommandRunner(SubprocessCommandRunner):
    def run(
        self,
        request: CommandRequest,
        *,
        progress: Callable[[ProgressEvent], None] | None = None,
        cancellation: threading.Event | None = None,
    ) -> CommandResult:
        if request.mode != CommandMode.INHERITED:
            raise ExecutionError("terminal-required", "interactive commands must inherit the terminal")
        return super().run(request, progress=progress, cancellation=cancellation)


def require_success(result: CommandResult) -> CommandResult:
    if result.ok:
        return result
    raise ExecutionError(
        result.request.stable_error_code,
        f"command ended in state {result.state.value}: {' '.join(result.request.display_argv())}",
        result=result,
    )
