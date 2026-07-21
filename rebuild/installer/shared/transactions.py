"""Durable transaction journals and deterministic cleanup stacks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
import threading
from typing import Callable, Literal

from .atomic_io import atomic_write_json


class TransactionError(RuntimeError):
    pass


class TransactionCancelled(TransactionError):
    pass


@dataclass(slots=True)
class CleanupAction:
    name: str
    callback: Callable[[], None]


class CleanupStack:
    def __init__(self) -> None:
        self._actions: list[CleanupAction] = []
        self.executed: list[str] = []

    def push(self, name: str, callback: Callable[[], None]) -> None:
        self._actions.append(CleanupAction(name, callback))

    def run(self) -> tuple[Exception, ...]:
        failures: list[Exception] = []
        while self._actions:
            action = self._actions.pop()
            try:
                action.callback()
                self.executed.append(action.name)
            except Exception as exc:
                failures.append(exc)
        return tuple(failures)


class TransactionJournal:
    def __init__(self, path: str | Path, *, transaction_id: str, kind: str) -> None:
        self.path = Path(path)
        self.payload: dict[str, object] = {
            "schema_version": "1.0.0",
            "transaction_id": transaction_id,
            "kind": kind,
            "status": "created",
            "created_at_utc": datetime.now(UTC).isoformat(),
            "updated_at_utc": datetime.now(UTC).isoformat(),
            "events": [],
        }

    def record(self, status: str, message: str) -> None:
        now = datetime.now(UTC).isoformat()
        events = self.payload["events"]
        assert isinstance(events, list)
        events.append({"at_utc": now, "status": status, "message": message})
        self.payload["status"] = status
        self.payload["updated_at_utc"] = now
        atomic_write_json(self.path, self.payload)

    def recover_interrupted(self) -> bool:
        if not self.path.exists():
            return False
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if payload.get("status") not in {"running", "cleaning"}:
            return False
        self.payload = payload
        self.record("interrupted", "Recovered an incomplete transaction journal")
        return True


class BaseTransaction:
    kind = "base"

    def __init__(
        self,
        journal: TransactionJournal,
        *,
        cancellation: threading.Event | None = None,
        dry_run: bool = False,
    ) -> None:
        self.journal = journal
        self.cancellation = cancellation or threading.Event()
        self.dry_run = dry_run
        self.cleanup = CleanupStack()
        self._cancellable = True
        self._handled_failure = ""

    def add_cleanup(self, name: str, callback: Callable[[], None]) -> None:
        self.cleanup.push(name, callback)

    def mark_unsafe_to_cancel(self, reason: str) -> None:
        self._cancellable = False
        self.journal.record("running", f"Cancellation disabled: {reason}")

    def fail(self, message: str) -> None:
        if not message.strip():
            raise ValueError("failure message cannot be empty")
        self._handled_failure = message.strip()

    def check_cancelled(self) -> None:
        if not self.cancellation.is_set():
            return
        if not self._cancellable:
            raise TransactionError("cancellation requested after the safe cancellation boundary")
        raise TransactionCancelled("transaction cancelled")

    def __enter__(self) -> "BaseTransaction":
        status = "simulated" if self.dry_run else "running"
        self.journal.record(status, "Transaction entered")
        self.check_cancelled()
        return self

    def __exit__(self, exc_type, exc, _traceback) -> Literal[False]:
        self.journal.record("cleaning", "Running cleanup stack")
        cleanup_failures = self.cleanup.run()
        if cleanup_failures:
            self.journal.record("cleanup-failed", f"{len(cleanup_failures)} cleanup action(s) failed")
            if exc is None:
                raise TransactionError("cleanup failed") from cleanup_failures[0]
        elif isinstance(exc, TransactionCancelled):
            self.journal.record("cancelled", str(exc))
        elif exc is not None:
            self.journal.record("failed", f"{type(exc).__name__}: {exc}")
        elif self._handled_failure:
            self.journal.record("failed", self._handled_failure)
        elif self.dry_run:
            self.journal.record("simulated", "Simulation completed; no changes applied")
        else:
            self.journal.record("succeeded", "Postconditions and cleanup completed")
        return False


class DiskTransaction(BaseTransaction):
    kind = "disk"


class MountTransaction(BaseTransaction):
    kind = "mount"


class ReleaseTransaction(BaseTransaction):
    kind = "release"
