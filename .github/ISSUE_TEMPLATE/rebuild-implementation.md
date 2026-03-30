---
name: Rebuild Implementation Slice
about: Create a tightly scoped rebuild implementation issue
title: "[Rebuild] "
assignees: ""
---

## Goal

State one concrete objective.

## Scope

List exactly what this issue is allowed to build or modify.

## Allowed files

- `rebuild/...`

## Forbidden files

- `setup.sh`
- `windows-prep.ps1`
- unrelated workstream boundaries

## Inputs

List the existing contracts, modules, or docs this issue may rely on.

## Outputs

List the files, modules, workflows, or documents that must exist when the issue is complete.

## Rules

- Keep the change inside one workstream when possible.
- Do not invent missing upstream contracts.
- Mark the issue blocked if a dependency is incomplete.

## Acceptance criteria

- [ ] Scoped files exist
- [ ] Acceptance behavior is validated
- [ ] Forbidden areas were not touched
- [ ] Required docs or status updates were made

## Out of scope

List what this issue must not attempt to solve.
