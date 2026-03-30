# Rebuild Containment Boundary

This document defines the hard boundary for early rebuild work under `rebuild/`.

## Objective

- Keep all rebuild implementation work inside `rebuild/` until specific slices are promoted.
- Avoid in-place rewrites of legacy production flows during foundational architecture work.

## Allowed During Containment

- Add or modify files under `rebuild/**`.
- Add coordination-only files under `.github/ISSUE_TEMPLATE/**` and `.github/PULL_REQUEST_TEMPLATE.md`.
- Update `.vscode/mcp.json` for repository-local tooling only.

## Forbidden During Containment

- Editing legacy runtime execution paths for feature delivery:
  - `setup.sh`
  - `windows-prep.ps1`
  - `build-custom-iso.sh`
- Moving rebuild runtime logic directly into legacy shell or PowerShell flows.
- Merging Windows/Arch runtime behavior changes before shared rebuild contracts are established.

## Promotion Gate

A rebuild slice can only be promoted outside `rebuild/` when all conditions are true:

1. The scoped rebuild module is complete and reviewed.
2. Required shared contracts are versioned and documented.
3. Safety review has been completed for affected domains.
4. The tracker task and status ledger are updated with promotion rationale.

Until this gate is met, `rebuild/` remains the exclusive implementation area.

## PR Review Checklist For This Boundary

- Changed file set is inside `rebuild/**` (plus approved coordination exceptions).
- No production behavior change was made in legacy runtime entrypoints.
- Status and ownership docs are updated when boundaries change.
- Task tracker status reflects claimed/completed state accurately.
