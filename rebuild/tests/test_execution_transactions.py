from __future__ import annotations

import json
from pathlib import Path
import sys
import threading

import pytest

from rebuild.installer.shared.atomic_io import atomic_write_json, atomic_write_text
from rebuild.installer.shared.execution import (
    CommandMode,
    CommandRequest,
    CommandState,
    ExecutionError,
    InteractiveCommandRunner,
    SubprocessCommandRunner,
)
from rebuild.installer.shared.transactions import (
    DiskTransaction,
    TransactionCancelled,
    TransactionError,
    TransactionJournal,
)


def make_transaction(tmp_path: Path, **kwargs: object) -> DiskTransaction:
    journal = TransactionJournal(tmp_path / "journal.json", transaction_id="test-1", kind="disk")
    return DiskTransaction(journal, **kwargs)  # type: ignore[arg-type]


def test_atomic_writes_replace_complete_content_and_leave_no_temp(tmp_path: Path) -> None:
    destination = tmp_path / "state" / "state.json"
    atomic_write_json(destination, {"generation": 1})
    atomic_write_json(destination, {"generation": 2})

    assert json.loads(destination.read_text(encoding="utf-8")) == {"generation": 2}
    assert not list(destination.parent.glob("*.tmp"))


def test_atomic_write_cleans_temp_after_replace_failure(tmp_path: Path, monkeypatch) -> None:
    import rebuild.installer.shared.atomic_io as atomic_io

    destination = tmp_path / "state.json"

    def fail_replace(_source: object, _destination: object) -> None:
        raise OSError("simulated crash")

    monkeypatch.setattr(atomic_io.os, "replace", fail_replace)

    with pytest.raises(OSError, match="simulated crash"):
        atomic_write_text(destination, "new")
    assert not destination.exists()
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("outcome", ["success", "failure", "exception", "cancellation"])
def test_cleanup_runs_lifo_for_every_exit_path(tmp_path: Path, outcome: str) -> None:
    events: list[str] = []
    cancellation = threading.Event()
    transaction = make_transaction(tmp_path, cancellation=cancellation)

    with pytest.raises((RuntimeError, TransactionCancelled)) if outcome in {
        "exception",
        "cancellation",
    } else _does_not_raise():
        with transaction as active:
            active.add_cleanup("first", lambda: events.append("first"))
            active.add_cleanup("second", lambda: events.append("second"))
            if outcome == "failure":
                active.fail("handled failure")
            elif outcome == "exception":
                raise RuntimeError("boom")
            elif outcome == "cancellation":
                cancellation.set()
                active.check_cancelled()

    assert events == ["second", "first"]
    payload = json.loads((tmp_path / "journal.json").read_text(encoding="utf-8"))
    expected_status = {
        "success": "succeeded",
        "failure": "failed",
        "exception": "failed",
        "cancellation": "cancelled",
    }[outcome]
    assert payload["status"] == expected_status


class _does_not_raise:
    def __enter__(self) -> None:
        return None

    def __exit__(self, *_args: object) -> bool:
        return False


def test_cleanup_failure_is_not_reported_as_success(tmp_path: Path) -> None:
    transaction = make_transaction(tmp_path)

    with pytest.raises(TransactionError, match="cleanup failed"):
        with transaction as active:
            active.add_cleanup("broken", lambda: (_ for _ in ()).throw(OSError("busy")))

    payload = json.loads((tmp_path / "journal.json").read_text(encoding="utf-8"))
    assert payload["status"] == "cleanup-failed"


def test_interrupted_journal_is_recovered_atomically(tmp_path: Path) -> None:
    path = tmp_path / "journal.json"
    original = TransactionJournal(path, transaction_id="dead-process", kind="mount")
    original.record("running", "before simulated process termination")

    recovered = TransactionJournal(path, transaction_id="new-process", kind="mount")
    assert recovered.recover_interrupted() is True
    assert json.loads(path.read_text(encoding="utf-8"))["status"] == "interrupted"


def test_command_simulation_is_never_success_state() -> None:
    runner = SubprocessCommandRunner(dry_run=True, allowed_commands=["safe-tool"])
    result = runner.run(CommandRequest(("safe-tool", "--apply")))

    assert result.state == CommandState.SIMULATED
    assert result.returncode is None


def test_command_allowlist_blocks_before_execution() -> None:
    runner = SubprocessCommandRunner(allowed_commands=["allowed"])

    with pytest.raises(ExecutionError) as error:
        runner.run(CommandRequest(("forbidden",)))
    assert error.value.code == "command-not-allowed"


def test_secret_is_redacted_from_progress_messages() -> None:
    events: list[str] = []
    secret = "super-secret"
    runner = SubprocessCommandRunner(dry_run=True, allowed_commands=["safe-tool"])
    request = CommandRequest(("safe-tool", "--password", secret), redacted_values=(secret,))

    runner.run(request, progress=lambda event: events.append(event.message))

    assert events
    assert all(secret not in event for event in events)
    assert "<redacted>" in events[0]


def test_interactive_runner_requires_inherited_terminal() -> None:
    runner = InteractiveCommandRunner(dry_run=True)

    with pytest.raises(ExecutionError) as error:
        runner.run(CommandRequest((sys.executable, "-V"), mode=CommandMode.CAPTURED))
    assert error.value.code == "terminal-required"


def test_pre_start_cancellation_never_spawns_process() -> None:
    cancellation = threading.Event()
    cancellation.set()
    runner = SubprocessCommandRunner(allowed_commands=["definitely-not-installed"])

    result = runner.run(CommandRequest(("definitely-not-installed",)), cancellation=cancellation)

    assert result.state == CommandState.CANCELLED
