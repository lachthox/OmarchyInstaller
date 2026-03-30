# Task Orchestrator MCP

This is a project-local MCP server for `OmarchyInstaller`.

It is intentionally scoped to this repository only:

- tracker source of truth: `omarchy_todo_tracker.json`
- runtime lease/block state: `rebuild/tools/task_orchestrator_mcp/runtime/task_state.json`
- workspace integration: `.vscode/mcp.json`

It does not depend on user-profile MCP configuration.

## Purpose

The server provides a thin orchestration layer over the task tracker so agents can:

- list tasks
- list the next ready task in strict sequence (global or assignee-scoped)
- claim and release tasks
- clear queued leases when a queue is stuck
- block and unblock tasks
- complete and reopen tasks
- inspect recent orchestration events

All tool responses include a `meta` block with freshness data:

- `generated_at_utc`
- `tracker_mtime_utc`
- `state_mtime_utc`
- `last_event_utc`

Use this metadata to detect stale reads before reporting queue status.

## Current scheduling model

The default readiness strategy is `strict-sequential`.

Without an assignee filter:

- tasks are evaluated in tracker order
- a task is only ready when every earlier task is completed
- blocked or leased predecessor tasks prevent downstream tasks from being ready

With `claim_next_task` / `list_ready_tasks` assignee routing (`assignee`, legacy `assingee`, or `requester`):

- tasks are still evaluated in tracker order
- readiness only considers predecessors assigned to that same assignee
- this allows `Codex` and `Copilot` queues to progress independently while preserving per-assignee ordering

This remains conservative and deterministic until explicit task dependencies are added.

## Anti-stale usage rule

Always scope queue reads by assignee/requester when working in a multi-agent flow.

- Good: `list_ready_tasks(assignee="Copilot")`
- Good: `claim_next_task(agent_name="copilot", assignee="Copilot", requester="Copilot")`
- Good: `get_task(task_number="WIN-007", assignee="Copilot")`
- Risky: unscoped `get_task` or `list_ready_tasks` in a mixed Codex+Copilot run

`get_task` supports scoped reads (`assignee` / `requester`). When called unscoped, it now returns:

- global readiness fields (`ready`, `ready_reason`)
- `queue_views.Codex`
- `queue_views.Copilot`

This makes it explicit when a task is globally blocked but ready in an assignee-specific queue.

## Project-local setup

Install dependencies inside the project, not at user level. One option:

```powershell
python -m venv rebuild/.venv
rebuild/.venv/Scripts/python -m pip install -r rebuild/requirements.txt
```

Then VS Code can start the server from `.vscode/mcp.json`, or you can run it directly:

```powershell
python rebuild/tools/task_orchestrator_mcp/server.py
```

## Tracked files

- `.vscode/mcp.json`
- `rebuild/tools/task_orchestrator_mcp/server.py`
- `rebuild/tools/task_orchestrator_mcp/tracker_store.py`

## Untracked runtime state

The runtime state file is intentionally local to this repo and should not be promoted as the source of truth:

- `rebuild/tools/task_orchestrator_mcp/runtime/task_state.json`
