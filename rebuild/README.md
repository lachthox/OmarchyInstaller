# OmarchyInstaller Rebuild Containment

This directory is the mandatory containment zone for the Python rebuild.

The goal is to stage the new architecture without rewriting the legacy runtime in place. Until a slice is coherent, reviewed, and explicitly promoted, legacy files such as `setup.sh` and `windows-prep.ps1` remain the production path.

## Current scope

- Stage 0: containment and coordination scaffold
- Stage 1: repo scaffold for the Python rebuild
- No runtime replacement work has been promoted yet

## Directory intent

- `docs/`: ownership, dependencies, issue hierarchy, project setup, and status ledger
- `installer/`: future Python runtime packages and platform modules
- `tools/`: future build and release scripts invoked by CI
- `tools/task_orchestrator_mcp/`: project-local MCP server for task claiming, state tracking, and task dispatch
- `assets/`: future templates, service units, and packaged runtime assets
- `requirements.txt`: initial Python runtime dependency contract for the rebuild
- `requirements-dev.txt`: lint, test, and type-check tooling for rebuild development
- `pyproject.toml`: initial package metadata for the rebuild area

## Working rules

- Keep workstream ownership separated by directory boundary.
- Keep safety-critical work small and reviewable.
- Update `rebuild/docs/STATUS.md` whenever the rebuild coordination state changes.
- Do not modify legacy production flows from inside this directory until replacement slices are ready.

## Coordination documents

- `rebuild/docs/STATUS.md`
- `rebuild/docs/ownership-map.md`
- `rebuild/docs/dependency-map.md`
- `rebuild/docs/roles-and-workstreams.md`
- `rebuild/docs/github-project-setup.md`
- `rebuild/docs/coordination-rules.md`
- `rebuild/docs/issue-hierarchy.md`
- `rebuild/docs/containment-boundary.md`
- `rebuild/docs/architecture.md`
- `rebuild/tools/task_orchestrator_mcp/README.md`
