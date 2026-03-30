from __future__ import annotations

import argparse
from datetime import UTC, datetime
import os
from typing import Any

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as exc:  # pragma: no cover - exercised only when dependency is missing
    raise SystemExit(
        "Missing dependency 'mcp'. Install project-local dependencies from rebuild/requirements.txt or rebuild/pyproject.toml."
    ) from exc

from tracker_store import DEFAULT_LEASE_MINUTES, StoreError, TrackerStore, normalize_assignee


store = TrackerStore()
mcp = FastMCP("Omarchy Task Orchestrator", json_response=True)


def _wrap(callable_obj: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
    try:
        return {
            "ok": True,
            "result": callable_obj(*args, **kwargs),
            "meta": _freshness_metadata(),
        }
    except StoreError as exc:
        return {
            "ok": False,
            "error": str(exc),
            "meta": _freshness_metadata(),
        }


def _resolve_routing_assignee(
    assingee: str = "",
    assignee: str = "",
    requester: str = "",
    agent_name: str = "",
) -> str | None:
    # Keep backwards compatibility with legacy "assingee" while supporting
    # the correct "assignee" and requester-based routing.
    return normalize_assignee(assignee or assingee or requester or agent_name)


def _path_mtime_utc(path_value: str) -> str:
    try:
        return datetime.fromtimestamp(os.path.getmtime(path_value), tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    except OSError:
        return ""


def _freshness_metadata() -> dict[str, Any]:
    last_event = ""
    try:
        state = store._read_state()
        if state.get("events"):
            last_event = state["events"][-1].get("timestamp", "")
    except StoreError:
        last_event = ""

    return {
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tracker_path": str(store.tracker_path),
        "state_path": str(store.state_path),
        "tracker_mtime_utc": _path_mtime_utc(str(store.tracker_path)),
        "state_mtime_utc": _path_mtime_utc(str(store.state_path)),
        "last_event_utc": last_event,
    }


@mcp.tool()
def server_info() -> dict[str, Any]:
    """Return workspace-local orchestrator metadata and task summary."""
    return _wrap(store.server_info)


@mcp.tool()
def list_tasks(
    section: str = "",
    assingee: str = "",
    assignee: str = "",
    requester: str = "",
    completion_flag: str = "",
    limit: int = 25,
) -> dict[str, Any]:
    """List tasks from the tracker with lease/block/ready metadata."""
    parsed_completion: bool | None
    if completion_flag == "":
        parsed_completion = None
    else:
        parsed_completion = completion_flag.lower() == "true"
    return _wrap(
        store.list_tasks,
        section=section or None,
        assingee=_resolve_routing_assignee(assingee=assingee, assignee=assignee, requester=requester),
        completion_flag=parsed_completion,
        limit=limit,
    )


@mcp.tool()
def get_task(
    task_number: str,
    assingee: str = "",
    assignee: str = "",
    requester: str = "",
    agent_name: str = "",
) -> dict[str, Any]:
    """Return one task by task number."""
    scoped_assignee = _resolve_routing_assignee(
        assingee=assingee,
        assignee=assignee,
        requester=requester,
        agent_name=agent_name,
    )
    if scoped_assignee:
        return _wrap(
            store.get_task,
            task_number=task_number,
            assingee=scoped_assignee,
        )

    response = _wrap(store.get_task, task_number=task_number)
    if not response.get("ok"):
        return response

    queue_views: dict[str, dict[str, Any]] = {}
    for queue_name in ("Codex", "Copilot"):
        queue_task = store.get_task(task_number=task_number, assingee=queue_name)
        queue_views[queue_name] = {
            "ready": queue_task.get("ready"),
            "ready_reason": queue_task.get("ready_reason"),
            "lease": queue_task.get("lease"),
            "blocked": queue_task.get("blocked"),
        }
    response["result"]["queue_views"] = queue_views
    return response


@mcp.tool()
def list_ready_tasks(limit: int = 10, assingee: str = "", assignee: str = "", requester: str = "") -> dict[str, Any]:
    """List the next ready tasks using strict sequential ordering."""
    return _wrap(
        store.list_ready_tasks,
        limit=limit,
        assingee=_resolve_routing_assignee(assingee=assingee, assignee=assignee, requester=requester),
    )


@mcp.tool()
def claim_next_task(
    agent_name: str,
    assingee: str = "",
    assignee: str = "",
    requester: str = "",
    lease_minutes: int = DEFAULT_LEASE_MINUTES,
) -> dict[str, Any]:
    """Claim the next ready task for an agent."""
    return _wrap(
        store.claim_next_task,
        agent_name=agent_name,
        assingee=_resolve_routing_assignee(
            assingee=assingee,
            assignee=assignee,
            requester=requester,
            agent_name=agent_name,
        ),
        lease_minutes=lease_minutes,
    )


@mcp.tool()
def claim_task(task_number: str, agent_name: str, lease_minutes: int = DEFAULT_LEASE_MINUTES) -> dict[str, Any]:
    """Claim a specific task if it is ready."""
    return _wrap(store.claim_task, task_number=task_number, agent_name=agent_name, lease_minutes=lease_minutes)


@mcp.tool()
def release_task(task_number: str, agent_name: str, note: str = "") -> dict[str, Any]:
    """Release a claimed task without completing it."""
    return _wrap(store.release_task, task_number=task_number, agent_name=agent_name, note=note)


@mcp.tool()
def clear_queue(
    agent_name: str,
    assingee: str = "",
    assignee: str = "",
    requester: str = "",
    clear_all: bool = False,
    note: str = "",
) -> dict[str, Any]:
    """Clear active leases by queue scope or agent owner."""
    return _wrap(
        store.clear_queue,
        agent_name=agent_name,
        assingee=_resolve_routing_assignee(assingee=assingee, assignee=assignee, requester=requester),
        clear_all=clear_all,
        note=note,
    )


@mcp.tool()
def block_task(task_number: str, agent_name: str, reason: str) -> dict[str, Any]:
    """Block a task with an explicit reason."""
    return _wrap(store.block_task, task_number=task_number, agent_name=agent_name, reason=reason)


@mcp.tool()
def unblock_task(task_number: str, agent_name: str, note: str = "") -> dict[str, Any]:
    """Remove a block from a task."""
    return _wrap(store.unblock_task, task_number=task_number, agent_name=agent_name, note=note)


@mcp.tool()
def complete_task(task_number: str, agent_name: str, completion_comment: str) -> dict[str, Any]:
    """Mark a task completed and update the tracker comment."""
    return _wrap(
        store.complete_task,
        task_number=task_number,
        agent_name=agent_name,
        completion_comment=completion_comment,
    )


@mcp.tool()
def reopen_task(task_number: str, agent_name: str, note: str = "") -> dict[str, Any]:
    """Reopen a completed task and clear its completion state."""
    return _wrap(store.reopen_task, task_number=task_number, agent_name=agent_name, note=note)


@mcp.tool()
def list_events(limit: int = 20) -> dict[str, Any]:
    """Return recent orchestrator events."""
    return _wrap(store.list_events, limit=limit)


def main() -> None:
    parser = argparse.ArgumentParser(description="Project-local MCP task orchestrator")
    parser.add_argument(
        "--transport",
        default="stdio",
        choices=["stdio"],
        help="MCP transport to use. The current server is configured for stdio only.",
    )
    parser.parse_args()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
