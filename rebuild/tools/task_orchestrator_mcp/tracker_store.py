from __future__ import annotations

import json
import importlib
import os
import socket
import tempfile
import threading
import time
import calendar
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

_locking: Any = importlib.import_module("msvcrt" if os.name == "nt" else "fcntl")


STATE_SCHEMA_VERSION = "1.0.0"
DEFAULT_LEASE_MINUTES = 60
EVENT_LIMIT = 200
ASSIGNEE_ALIASES = {
    "codex": "Codex",
    "copilot": "Copilot",
}


class StoreError(RuntimeError):
    """Raised when tracker operations cannot complete safely."""


@dataclass
class FileLock:
    path: Path
    timeout_seconds: float = 10.0
    poll_interval_seconds: float = 0.1

    def __post_init__(self) -> None:
        self.lock_path = self.path
        self._fd: int | None = None
        self._thread_lock = _thread_lock_for(self.lock_path)

    def __enter__(self) -> "FileLock":
        deadline = time.monotonic() + self.timeout_seconds
        if not self._thread_lock.acquire(timeout=self.timeout_seconds):
            raise StoreError(f"Timed out acquiring in-process lock: {self.lock_path}")
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._fd = os.open(str(self.lock_path), os.O_CREAT | os.O_RDWR, 0o600)
        if os.fstat(self._fd).st_size == 0:
            os.write(self._fd, b"\0")
            os.fsync(self._fd)
        while True:
            try:
                if os.name == "nt":
                    os.lseek(self._fd, 0, os.SEEK_SET)
                    _locking.locking(self._fd, _locking.LK_NBLCK, 1)
                else:  # pragma: no cover - exercised on Linux CI
                    _locking.flock(self._fd, _locking.LOCK_EX | _locking.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    os.close(self._fd)
                    self._fd = None
                    self._thread_lock.release()
                    raise StoreError(f"Timed out acquiring OS lock: {self.lock_path}")
                time.sleep(self.poll_interval_seconds)
        payload = {
            "host": socket.gethostname(),
            "pid": os.getpid(),
            "process_start_identity": _process_start_identity(os.getpid()),
            "lock_created_at": _utc_now(),
        }
        os.ftruncate(self._fd, 0)
        os.lseek(self._fd, 0, os.SEEK_SET)
        os.write(self._fd, json.dumps(payload, sort_keys=True).encode("utf-8"))
        os.fsync(self._fd)
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self._fd is not None:
            if os.name == "nt":
                os.lseek(self._fd, 0, os.SEEK_SET)
                _locking.locking(self._fd, _locking.LK_UNLCK, 1)
            else:  # pragma: no cover - exercised on Linux CI
                _locking.flock(self._fd, _locking.LOCK_UN)
            os.close(self._fd)
            self._fd = None
        self._thread_lock.release()


_THREAD_LOCKS: dict[str, threading.Lock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()


def _thread_lock_for(path: Path) -> threading.Lock:
    key = str(path.resolve())
    with _THREAD_LOCKS_GUARD:
        return _THREAD_LOCKS.setdefault(key, threading.Lock())


def _process_start_identity(pid: int) -> str:
    proc_stat = Path(f"/proc/{pid}/stat")
    try:
        return f"proc:{proc_stat.read_text(encoding='utf-8').split()[21]}"
    except (OSError, IndexError):
        return f"pid:{pid}:host:{socket.gethostname()}"


class TrackerStore:
    def __init__(
        self,
        workspace_root: Path | None = None,
        tracker_path: Path | None = None,
        state_path: Path | None = None,
    ) -> None:
        self.workspace_root = (workspace_root or _discover_workspace_root()).resolve()
        self.tracker_path = (
            Path(os.environ.get("OMARCHY_TRACKER_PATH", tracker_path or self.workspace_root / "omarchy_todo_tracker.json"))
            .resolve()
        )
        self.state_path = (
            Path(
                os.environ.get(
                    "OMARCHY_RUNTIME_STATE_PATH",
                    state_path
                    or self.workspace_root / "rebuild" / "tools" / "task_orchestrator_mcp" / "runtime" / "task_state.json",
                )
            ).resolve()
        )
        self.lock_path = self.state_path.with_suffix(".lock")
        self.journal_path = self.state_path.with_suffix(".transaction.json")
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(self.lock_path):
            self._recover_transaction()
            self._ensure_state_file()
            self._read_tracker()
            self._read_state()

    def server_info(self) -> dict[str, Any]:
        tracker, state = self._read_consistent()
        return {
            "workspace_root": str(self.workspace_root),
            "tracker_path": str(self.tracker_path),
            "state_path": str(self.state_path),
            "task_count": len(tracker["tasks"]),
            "completed_count": sum(1 for task in tracker["tasks"] if task["Completion Flag"]),
            "blocked_count": len(state["blocked"]),
            "leased_count": len(state["leases"]),
            "strategy": "strict-sequential",
        }

    def list_tasks(
        self,
        section: str | None = None,
        assingee: str | None = None,
        completion_flag: bool | None = None,
        limit: int = 25,
    ) -> list[dict[str, Any]]:
        tracker, state = self._read_consistent()
        normalized_assignee = normalize_assignee(assingee)

        tasks: list[dict[str, Any]] = []
        for index, task in enumerate(tracker["tasks"]):
            if section and task["Section"] != section:
                continue
            if normalized_assignee and normalize_assignee(task["Assingee"]) != normalized_assignee:
                continue
            if completion_flag is not None and task["Completion Flag"] != completion_flag:
                continue
            tasks.append(
                self._augment_task(
                    task,
                    index,
                    tracker["tasks"],
                    state,
                    queue_assignee=normalized_assignee,
                )
            )
            if len(tasks) >= limit:
                break
        return tasks

    def get_task(self, task_number: str, assingee: str | None = None) -> dict[str, Any]:
        tracker, state = self._read_consistent()
        normalized_assignee = normalize_assignee(assingee)
        task, index = self._find_task(tracker["tasks"], task_number)
        return self._augment_task(
            task,
            index,
            tracker["tasks"],
            state,
            queue_assignee=normalized_assignee,
        )

    def list_ready_tasks(self, limit: int = 10, assingee: str | None = None) -> list[dict[str, Any]]:
        tracker, state = self._read_consistent()
        normalized_assignee = normalize_assignee(assingee)
        ready: list[dict[str, Any]] = []
        for index, task in enumerate(tracker["tasks"]):
            if normalized_assignee and normalize_assignee(task["Assingee"]) != normalized_assignee:
                continue
            augmented = self._augment_task(
                task,
                index,
                tracker["tasks"],
                state,
                queue_assignee=normalized_assignee,
            )
            if augmented["ready"]:
                ready.append(augmented)
            if len(ready) >= limit:
                break
        return ready

    def claim_next_task(self, agent_name: str, assingee: str | None = None, lease_minutes: int = DEFAULT_LEASE_MINUTES) -> dict[str, Any]:
        normalized_assignee = normalize_assignee(assingee)
        with self._locked_state() as state:
            tracker = self._read_tracker()
            self._purge_expired_leases(state)
            for index, task in enumerate(tracker["tasks"]):
                if normalized_assignee and normalize_assignee(task["Assingee"]) != normalized_assignee:
                    continue
                augmented = self._augment_task(
                    task,
                    index,
                    tracker["tasks"],
                    state,
                    queue_assignee=normalized_assignee,
                )
                if augmented["ready"]:
                    self._set_lease(state, task["Task Number"], agent_name, lease_minutes)
                    self._record_event(state, "claim", task["Task Number"], agent_name, "")
                    self._write_state(state)
                    return self._augment_task(task, index, tracker["tasks"], state)
        raise StoreError("No ready task is available to claim.")

    def claim_task(self, task_number: str, agent_name: str, lease_minutes: int = DEFAULT_LEASE_MINUTES) -> dict[str, Any]:
        with self._locked_state() as state:
            tracker = self._read_tracker()
            task, index = self._find_task(tracker["tasks"], task_number)
            self._purge_expired_leases(state)
            augmented = self._augment_task(task, index, tracker["tasks"], state)
            if not augmented["ready"]:
                raise StoreError(f"Task {task_number} is not ready to claim: {augmented['ready_reason']}")
            self._set_lease(state, task_number, agent_name, lease_minutes)
            self._record_event(state, "claim", task_number, agent_name, "")
            self._write_state(state)
            return self._augment_task(task, index, tracker["tasks"], state)

    def release_task(self, task_number: str, agent_name: str, note: str = "") -> dict[str, Any]:
        with self._locked_state() as state:
            tracker = self._read_tracker()
            task, index = self._find_task(tracker["tasks"], task_number)
            self._purge_expired_leases(state)
            lease = state["leases"].get(task_number)
            if not lease:
                raise StoreError(f"Task {task_number} does not have an active lease.")
            if lease["agent_name"] != agent_name:
                raise StoreError(f"Task {task_number} is leased by {lease['agent_name']}, not {agent_name}.")
            del state["leases"][task_number]
            self._record_event(state, "release", task_number, agent_name, note)
            self._write_state(state)
            return self._augment_task(task, index, tracker["tasks"], state)

    def clear_queue(
        self,
        agent_name: str,
        assingee: str | None = None,
        clear_all: bool = False,
        note: str = "",
    ) -> dict[str, Any]:
        normalized_assignee = normalize_assignee(assingee)
        cleared: list[str] = []
        with self._locked_state() as state:
            tracker = self._read_tracker()
            self._purge_expired_leases(state)
            task_assignee_by_number = {
                task["Task Number"]: normalize_assignee(task["Assingee"]) for task in tracker["tasks"]
            }
            for task_number, lease in list(state["leases"].items()):
                if clear_all:
                    pass
                elif normalized_assignee:
                    if task_assignee_by_number.get(task_number) != normalized_assignee:
                        continue
                elif lease.get("agent_name") != agent_name:
                    continue
                del state["leases"][task_number]
                detail = note.strip() or "queue clear"
                self._record_event(state, "release", task_number, agent_name, detail)
                cleared.append(task_number)
            self._write_state(state)
        return {
            "cleared_count": len(cleared),
            "cleared_task_numbers": cleared,
            "scope_assingee": normalized_assignee,
            "clear_all": clear_all,
        }

    def block_task(self, task_number: str, agent_name: str, reason: str) -> dict[str, Any]:
        with self._locked_state() as state:
            tracker = self._read_tracker()
            task, index = self._find_task(tracker["tasks"], task_number)
            self._purge_expired_leases(state)
            state["blocked"][task_number] = {
                "blocked_by": agent_name,
                "reason": reason.strip(),
                "blocked_at": _utc_now(),
            }
            state["leases"].pop(task_number, None)
            self._record_event(state, "block", task_number, agent_name, reason)
            self._write_state(state)
            return self._augment_task(task, index, tracker["tasks"], state)

    def unblock_task(self, task_number: str, agent_name: str, note: str = "") -> dict[str, Any]:
        with self._locked_state() as state:
            tracker = self._read_tracker()
            task, index = self._find_task(tracker["tasks"], task_number)
            self._purge_expired_leases(state)
            blocked = state["blocked"].get(task_number)
            if not blocked:
                raise StoreError(f"Task {task_number} is not blocked.")
            del state["blocked"][task_number]
            self._record_event(state, "unblock", task_number, agent_name, note)
            self._write_state(state)
            return self._augment_task(task, index, tracker["tasks"], state)

    def complete_task(self, task_number: str, agent_name: str, completion_comment: str) -> dict[str, Any]:
        with self._locked_state():
            tracker = self._read_tracker()
            task, index = self._find_task(tracker["tasks"], task_number)
            state = self._read_state()
            self._purge_expired_leases(state)

            lease = state["leases"].get(task_number)
            if lease and lease["agent_name"] != agent_name:
                raise StoreError(f"Task {task_number} is leased by {lease['agent_name']}, not {agent_name}.")

            task["Completion Flag"] = True
            task["Completion Comment"] = completion_comment.strip() or f"Completed by {agent_name} at {_utc_now()}."
            state["leases"].pop(task_number, None)
            state["blocked"].pop(task_number, None)
            self._record_event(state, "complete", task_number, agent_name, task["Completion Comment"])
            self._commit_pair(tracker, state)
            return self._augment_task(task, index, tracker["tasks"], state)

    def reopen_task(self, task_number: str, agent_name: str, note: str = "") -> dict[str, Any]:
        with self._locked_state():
            tracker = self._read_tracker()
            task, index = self._find_task(tracker["tasks"], task_number)
            state = self._read_state()
            self._purge_expired_leases(state)

            task["Completion Flag"] = False
            task["Completion Comment"] = note.strip()
            self._record_event(state, "reopen", task_number, agent_name, note)
            self._commit_pair(tracker, state)
            return self._augment_task(task, index, tracker["tasks"], state)

    def list_events(self, limit: int = 20) -> list[dict[str, Any]]:
        _, state = self._read_consistent()
        return list(reversed(state["events"][-limit:]))

    @contextmanager
    def _locked_state(self) -> Iterator[dict[str, Any]]:
        with FileLock(self.lock_path):
            self._recover_transaction()
            state = self._read_state()
            yield state

    def _read_consistent(self) -> tuple[dict[str, Any], dict[str, Any]]:
        with FileLock(self.lock_path):
            self._recover_transaction()
            tracker = self._read_tracker()
            state = self._read_state()
            if self._purge_expired_leases(state):
                self._write_state(state)
            return tracker, state

    def _ensure_state_file(self) -> None:
        if self.state_path.exists():
            return
        initial_state = {
            "schema_version": STATE_SCHEMA_VERSION,
            "tracker_path": os.path.relpath(self.tracker_path, self.workspace_root),
            "strategy": "strict-sequential",
            "leases": {},
            "blocked": {},
            "events": [],
        }
        self._write_json(self.state_path, initial_state)

    def _read_tracker(self) -> dict[str, Any]:
        tracker = self._read_json(self.tracker_path)
        required = {"schema_version", "schema", "tasks"}
        missing = required - set(tracker)
        if missing:
            raise StoreError(f"Tracker file is missing keys: {sorted(missing)}")
        self._validate_tracker(tracker)
        return tracker

    def _write_tracker(self, payload: dict[str, Any]) -> None:
        self._write_json(self.tracker_path, payload)

    def _read_state(self) -> dict[str, Any]:
        state = self._read_json(self.state_path)
        for key in ("leases", "blocked", "events"):
            state.setdefault(key, {} if key != "events" else [])
        state.setdefault("strategy", "strict-sequential")
        self._validate_state(state)
        return state

    def _write_state(self, payload: dict[str, Any]) -> None:
        self._write_json(self.state_path, payload)

    def _read_json(self, path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise StoreError(f"Missing required file: {path}") from exc
        except json.JSONDecodeError as exc:
            raise StoreError(f"Invalid JSON in {path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise StoreError(f"JSON root in {path} must be an object.")
        return payload

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(payload, handle, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def _commit_pair(self, tracker: dict[str, Any], state: dict[str, Any]) -> None:
        transaction = {
            "schema_version": STATE_SCHEMA_VERSION,
            "created_at": _utc_now(),
            "tracker": tracker,
            "state": state,
        }
        self._write_json(self.journal_path, transaction)
        self._write_tracker(tracker)
        self._write_state(state)
        self.journal_path.unlink(missing_ok=True)

    def _recover_transaction(self) -> None:
        if not self.journal_path.exists():
            return
        journal = self._read_json(self.journal_path)
        tracker = journal.get("tracker")
        state = journal.get("state")
        if not isinstance(tracker, dict) or not isinstance(state, dict):
            raise StoreError(f"Invalid transaction journal: {self.journal_path}")
        self._validate_tracker(tracker)
        self._validate_state(state)
        self._write_tracker(tracker)
        self._write_state(state)
        self.journal_path.unlink(missing_ok=True)

    def _validate_tracker(self, tracker: dict[str, Any]) -> None:
        tasks = tracker.get("tasks")
        if not isinstance(tasks, list):
            raise StoreError("Tracker tasks must be a list.")
        required = {"Task Number", "Section", "Assingee", "Completion Flag", "Completion Comment"}
        numbers: list[str] = []
        for index, task in enumerate(tasks):
            if not isinstance(task, dict):
                raise StoreError(f"Tracker task at index {index} must be an object.")
            missing = required - set(task)
            if missing:
                raise StoreError(f"Tracker task at index {index} is missing keys: {sorted(missing)}")
            if not isinstance(task["Task Number"], str) or not task["Task Number"].strip():
                raise StoreError(f"Tracker task at index {index} has an invalid Task Number.")
            if not isinstance(task["Completion Flag"], bool):
                raise StoreError(f"Tracker task {task['Task Number']} has a non-boolean Completion Flag.")
            numbers.append(task["Task Number"])
        duplicates = [number for number, count in Counter(numbers).items() if count > 1]
        if duplicates:
            raise StoreError(f"Duplicate task numbers detected: {duplicates}")

    def _validate_state(self, state: dict[str, Any]) -> None:
        if not isinstance(state.get("leases"), dict) or not isinstance(state.get("blocked"), dict):
            raise StoreError("Runtime state leases and blocked fields must be objects.")
        if not isinstance(state.get("events"), list):
            raise StoreError("Runtime state events must be a list.")

    def _find_task(self, tasks: list[dict[str, Any]], task_number: str) -> tuple[dict[str, Any], int]:
        for index, task in enumerate(tasks):
            if task["Task Number"] == task_number:
                return task, index
        raise StoreError(f"Unknown task number: {task_number}")

    def _augment_task(
        self,
        task: dict[str, Any],
        index: int,
        tasks: list[dict[str, Any]],
        state: dict[str, Any],
        queue_assignee: str | None = None,
    ) -> dict[str, Any]:
        task_number = task["Task Number"]
        blocked = state["blocked"].get(task_number)
        lease = state["leases"].get(task_number)
        ready, reason = self._task_ready(index, tasks, state, queue_assignee=queue_assignee)
        if task["Completion Flag"]:
            ready = False
            reason = "task already completed"
        if blocked:
            ready = False
            reason = "task is blocked"
        if lease:
            ready = False
            reason = f"task is leased by {lease['agent_name']}"

        augmented = dict(task)
        augmented["ready"] = ready
        augmented["ready_reason"] = reason
        augmented["lease"] = lease
        augmented["blocked"] = blocked
        return augmented

    def _task_ready(
        self,
        index: int,
        tasks: list[dict[str, Any]],
        state: dict[str, Any],
        queue_assignee: str | None = None,
    ) -> tuple[bool, str]:
        normalized_assignee = normalize_assignee(queue_assignee)
        for predecessor in tasks[:index]:
            if normalized_assignee and normalize_assignee(predecessor["Assingee"]) != normalized_assignee:
                continue
            predecessor_number = predecessor["Task Number"]
            if predecessor["Completion Flag"]:
                continue
            if predecessor_number in state["blocked"]:
                return False, f"predecessor {predecessor_number} is blocked"
            if predecessor_number in state["leases"]:
                return False, f"predecessor {predecessor_number} is leased"
            return False, f"predecessor {predecessor_number} is incomplete"
        return True, "task is next in sequence"

    def _set_lease(self, state: dict[str, Any], task_number: str, agent_name: str, lease_minutes: int) -> None:
        lease_seconds = max(1, lease_minutes) * 60
        state["leases"][task_number] = {
            "agent_name": agent_name,
            "claimed_at": _utc_now(),
            "lease_expires_at": _utc_now(offset_seconds=lease_seconds),
        }

    def _purge_expired_leases(self, state: dict[str, Any]) -> bool:
        now = time.time()
        expired = []
        for task_number, lease in state["leases"].items():
            try:
                expires_at = _parse_utc_timestamp(lease["lease_expires_at"])
            except (KeyError, ValueError):
                expired.append(task_number)
                continue
            if expires_at <= now:
                expired.append(task_number)
        for task_number in expired:
            del state["leases"][task_number]
            self._record_event(state, "lease-expired", task_number, "system", "")
        return bool(expired)

    def _record_event(self, state: dict[str, Any], event_type: str, task_number: str, agent_name: str, detail: str) -> None:
        state["events"].append(
            {
                "event_type": event_type,
                "task_number": task_number,
                "agent_name": agent_name,
                "detail": detail,
                "timestamp": _utc_now(),
            }
        )
        state["events"] = state["events"][-EVENT_LIMIT:]


def _discover_workspace_root() -> Path:
    env_root = os.environ.get("CODEX_WORKSPACE_ROOT")
    if env_root:
        return Path(env_root)
    return Path(__file__).resolve().parents[3]


def _utc_now(offset_seconds: int = 0) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + offset_seconds))


def _parse_utc_timestamp(value: str) -> float:
    return calendar.timegm(time.strptime(value, "%Y-%m-%dT%H:%M:%SZ"))


def normalize_assignee(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return ASSIGNEE_ALIASES.get(normalized.casefold(), normalized)
