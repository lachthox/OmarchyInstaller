# Issue Hierarchy Plan

This document describes the issue structure that should exist on GitHub for the rebuild.

## Parent domains

1. #11 Rebuild foundation and containment
2. #7 Shared schema and compatibility layer
3. #6 Windows preparation layer
4. #10 Ventoy integration layer
5. #4 Arch live installer layer
6. #3 Omarchy handoff layer
7. #5 Boot guardian layer
8. #9 Build and release automation layer
9. #8 Docs and coordination layer

## Initial child issue sequence

1. #12 Create `rebuild/` containment structure and coordination docs
2. #16 Create shared schema and compatibility foundation inside `rebuild/`
3. #13 Create Windows platform foundation for checks and backups
4. #14 Create Ventoy integration and ISO placement layer for Windows
5. #15 Create Arch live handoff loader and preflight foundation

## Current parent to child links

- #11 Rebuild foundation and containment -> #12 Create `rebuild/` containment structure and coordination docs
- #7 Shared schema and compatibility layer -> #16 Create shared schema and compatibility foundation inside `rebuild/`
- #6 Windows preparation layer -> #13 Create Windows platform foundation for checks and backups
- #10 Ventoy integration layer -> #14 Create Ventoy integration and ISO placement layer for Windows
- #4 Arch live installer layer -> #15 Create Arch live handoff loader and preflight foundation
- #3 Omarchy handoff layer -> #17 Implement Omarchy bootstrap location health check
- #5 Boot guardian layer -> #18 Implement boot guardian expected-state comparison and drift detection
- #9 Build and release automation layer -> #19 Add Windows EXE GitHub Actions workflow
- #8 Docs and coordination layer -> #20 Create docs/coordination stage briefs

## Parent domains awaiting first child slice

- None

## Project placement

- Issues #3 through #20 are added to GitHub project `OmarchyInstaller Rebuild` (`#1`).
- Issues #17 through #20 extend the parent domains that were awaiting their first child slice.
- Issue #16 is the current next priority.
- Issues #13, #14, and #15 are marked as waiting on dependency until the shared contract in #16 exists.

## Issue construction rules

Every implementation issue must include these sections:

- Goal
- Scope
- Allowed files
- Forbidden files
- Inputs
- Outputs
- Rules
- Acceptance criteria
- Out of scope

## Parent issue rules

- Parent issues own domain definition and child issue inventory.
- Parent issues are not implementation dumping grounds.
- Child issues must stay tightly scoped and reviewable.
