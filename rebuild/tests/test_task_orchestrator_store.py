from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import threading

import pytest

from rebuild.tools.task_orchestrator_mcp.tracker_store import StoreError, TrackerStore
from rebuild.tools.task_orchestrator_mcp.tracker_store import FileLock


def tracker_payload(*, completed: bool = False) -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "schema": {},
        "tasks": [{
            "Task Number": "TASK-001", "Section": "Test", "Assingee": "Codex",
            "Completion Flag": completed, "Completion Comment": "done" if completed else "",
        }],
    }


def make_store(tmp_path: Path) -> TrackerStore:
    tracker = tmp_path / "tracker.json"
    tracker.write_text(json.dumps(tracker_payload()), encoding="utf-8")
    return TrackerStore(workspace_root=tmp_path, tracker_path=tracker, state_path=tmp_path / "state.json")


def test_stale_lock_file_is_safely_reclaimed_with_process_identity(tmp_path: Path) -> None:
    tracker = tmp_path / "tracker.json"
    tracker.write_text(json.dumps(tracker_payload()), encoding="utf-8")
    lock = tmp_path / "state.lock"
    lock.write_text('{"host":"dead","pid":999999,"process_start_identity":"old","lock_created_at":"2000-01-01T00:00:00Z"}', encoding="utf-8")
    store = TrackerStore(workspace_root=tmp_path, tracker_path=tracker, state_path=tmp_path / "state.json")
    assert store.server_info()["task_count"] == 1
    metadata = json.loads(lock.read_text(encoding="utf-8"))
    assert metadata["pid"] == os.getpid()
    assert metadata["host"]
    assert metadata["process_start_identity"]


def test_killed_lock_owner_does_not_wedge_next_process(tmp_path: Path) -> None:
    lock = tmp_path / "killed.lock"
    code = (
        "import time; from pathlib import Path; "
        "from rebuild.tools.task_orchestrator_mcp.tracker_store import FileLock; "
        f"lock=FileLock(Path({str(lock)!r})); lock.__enter__(); print('locked', flush=True); time.sleep(60)"
    )
    child = subprocess.Popen(
        [sys.executable, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    try:
        assert child.stdout is not None
        assert child.stdout.readline().strip() == "locked"
    finally:
        child.terminate()
        child.wait(timeout=10)
    with FileLock(lock, timeout_seconds=2):
        assert True


def test_concurrent_claim_has_exactly_one_winner(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    winners: list[str] = []
    failures: list[str] = []

    def claim(agent: str) -> None:
        try:
            store.claim_task("TASK-001", agent)
            winners.append(agent)
        except StoreError as exc:
            failures.append(str(exc))

    threads = [threading.Thread(target=claim, args=(f"agent-{index}",)) for index in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(winners) == 1
    assert len(failures) == 5


def test_expired_lease_purge_is_persisted_under_lock(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    state = json.loads(store.state_path.read_text(encoding="utf-8"))
    state["leases"]["TASK-001"] = {
        "agent_name": "dead", "claimed_at": "2000-01-01T00:00:00Z",
        "lease_expires_at": "2000-01-01T00:01:00Z",
    }
    store.state_path.write_text(json.dumps(state), encoding="utf-8")
    store.list_tasks()
    persisted = json.loads(store.state_path.read_text(encoding="utf-8"))
    assert persisted["leases"] == {}
    assert persisted["events"][-1]["event_type"] == "lease-expired"


def test_interrupted_pair_commit_recovers_from_journal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = make_store(tmp_path)
    original_write_state = store._write_state

    def crash(_payload: dict[str, object]) -> None:
        raise OSError("simulated process interruption")

    monkeypatch.setattr(store, "_write_state", crash)
    with pytest.raises(OSError, match="interruption"):
        store.complete_task("TASK-001", "agent", "complete")
    assert store.journal_path.is_file()
    monkeypatch.setattr(store, "_write_state", original_write_state)

    recovered = TrackerStore(
        workspace_root=tmp_path, tracker_path=store.tracker_path, state_path=store.state_path
    )
    assert recovered.get_task("TASK-001")["Completion Flag"] is True
    assert recovered.list_events()[0]["event_type"] == "complete"
    assert not recovered.journal_path.exists()


@pytest.mark.parametrize("bad_task", [None, {}, {"Task Number": "TASK-001"}, {"Task Number": 7, "Section": "X", "Assingee": "Codex", "Completion Flag": False, "Completion Comment": ""}])
def test_malformed_task_records_are_rejected_before_indexing(tmp_path: Path, bad_task: object) -> None:
    payload = tracker_payload()
    payload["tasks"] = [bad_task]  # type: ignore[index]
    tracker = tmp_path / "tracker.json"
    tracker.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(StoreError, match="task"):
        TrackerStore(workspace_root=tmp_path, tracker_path=tracker, state_path=tmp_path / "state.json")


def test_corrupt_state_fails_without_overwriting_evidence(tmp_path: Path) -> None:
    tracker = tmp_path / "tracker.json"
    tracker.write_text(json.dumps(tracker_payload()), encoding="utf-8")
    state = tmp_path / "state.json"
    state.write_text("{broken", encoding="utf-8")
    with pytest.raises(StoreError, match="Invalid JSON"):
        TrackerStore(workspace_root=tmp_path, tracker_path=tracker, state_path=state)
    assert state.read_text(encoding="utf-8") == "{broken"
