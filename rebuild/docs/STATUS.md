# Rebuild Status Ledger

## Completed

- Created the `rebuild/` containment area on branch `Python-Rebuild`.
- Added coordination documents for ownership, dependencies, roles, project setup, and review discipline.
- Added GitHub issue and pull request templates to enforce structured work items.
- Added `rebuild/docs/stage-briefs.md` to define the mandatory Stage 0 through Stage 12 execution order.
- Added `rebuild/docs/boot-protection.md`, `rebuild/docs/plan-schema.md`, `rebuild/docs/release-process.md`, and `rebuild/docs/development-notes.md` as the remaining core project documentation files.
- Documented the rebuild trigger matrix and freshness policy in `rebuild/docs/release-process.md` and aligned the EXE and release workflow path filters with shared-contract changes.
- Created the parent issue hierarchy on GitHub: #11, #7, #6, #10, #4, #3, #5, #9, and #8.
- Created and linked the initial child issue sequence on GitHub: #12 under #11, #16 under #7, #13 under #6, #14 under #10, and #15 under #4.
- Created and linked the next child issue wave on GitHub: #17 under #3, #18 under #5, #19 under #9, and #20 under #8.
- Created GitHub Project `OmarchyInstaller Rebuild` as project #1 and linked `lachthox/OmarchyInstaller` to it.
- Created the custom project fields: `Rebuild Status`, `Layer`, `Workstream`, `Priority`, `Risk`, `Dependency State`, and `Agent Group`.
- Created the rebuild label set and the eight milestone entries from the buildout plan.
- Added issues #3 through #20 to project #1 and stamped their milestone, labels, and custom project field values.
- Added a project-local MCP task orchestrator scaffold under `rebuild/tools/task_orchestrator_mcp/`.
- Added a workspace-scoped `.vscode/mcp.json` so the task orchestrator is configured in this repo only, not at user profile level.
- Codified the containment boundary in `rebuild/docs/containment-boundary.md` so early rebuild work stays inside `rebuild/` until explicit promotion gates are met.
- Added `rebuild/docs/architecture.md` with the four-layer model, preserved legacy concepts, runtime boundaries, and target repo structure/ownership contracts.
- Created the concrete containment tree under `rebuild/installer/` with shared, platform-specific, and UI package families.
- Added scaffold assets for templates, systemd unit files, helper shell wrappers, ISO payload assets, and startup assets under `rebuild/assets/`.
- Added `rebuild/requirements-dev.txt` and synchronized dev dependencies in `rebuild/pyproject.toml`.
- Added a rebuild-owned Arch ISO CI slice with `.github/workflows/rebuild-iso.yml` and `rebuild/tools/build_iso_pipeline.py`, including payload staging for Python runtime files, startup hook references, required package manifest, and ISO build metadata output.
- Added a rebuild-owned Windows EXE CI slice with `.github/workflows/rebuild-windows-exe.yml` and `rebuild/tools/build_windows_exe.py`, including PyInstaller packaging inputs, version stamping, and executable build metadata output.
- Added a rebuild-owned release pipeline slice with `.github/workflows/rebuild-release.yml` and `rebuild/tools/publish_release.py`, generating release manifest, compatibility manifest, and release checksum bundle with optional GitHub release upload.
- Implemented strict shared contracts in `rebuild/installer/shared/` using Pydantic models, version parsing/comparison helpers, strict plan/compat validation, and fail-closed compatibility evaluation for Windows producer and Arch consumer alignment.

## In Progress

- None.

## Blocked

- None.

## Changed Assumptions

- The rebuild coordination layer is being established before any runtime Python modules are implemented.
- All rebuild PRs should target the `Python-Rebuild` branch until a later promotion decision is made.
- GitHub Project operations were completed through GitHub CLI after granting the local token the `project` scope, because the available MCP surface still does not expose Project creation commands.

## Current Next Priority

- Keep tracker and status docs synchronized as new maintenance or follow-up hardening tasks are opened.
