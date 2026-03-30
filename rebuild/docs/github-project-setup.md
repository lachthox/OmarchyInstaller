# GitHub Project Setup

This document translates the buildout prompt into concrete GitHub configuration.

## Project

- Name: `OmarchyInstaller Rebuild`
- Purpose: track the full rebuild as a controlled engineering program rather than a flat code backlog
- Branch target for rebuild PRs: `Python-Rebuild`
- Live project: `#1`
- URL: `https://github.com/users/lachthox/projects/1`

## Required status field

- `Backlog`
- `Ready`
- `In Progress`
- `Blocked`
- `In Review`
- `Done`

## Optional status values

- `Scaffolded`
- `Waiting on Dependency`
- `Needs Human Decision`

## Recommended custom fields

### Layer

- `Build/CI`
- `Shared`
- `Windows`
- `Arch Live`
- `Omarchy Handoff`
- `Boot Guardian`
- `Docs/Coordination`

### Workstream

- `Schema`
- `UI`
- `Platform`
- `Ventoy`
- `Backup`
- `Partitioning`
- `Network`
- `Boot`
- `Packaging`
- `Release`
- `Security`

### Priority

- `Critical`
- `High`
- `Normal`
- `Low`

### Risk

- `Safety Critical`
- `High Risk`
- `Standard`

### Dependency State

- `Unblocked`
- `Waiting on Dependency`
- `Blocked`

### Agent Group

- `Copilot Scaffold`
- `Copilot Implement`
- `Human Review`
- `Codex Follow-up`
- `Mixed`

## Labels created

- `layer:build-ci`
- `layer:shared`
- `layer:windows`
- `layer:arch-live`
- `layer:omarchy`
- `layer:boot-guardian`
- `layer:docs`
- `type:scaffold`
- `type:implementation`
- `type:review`
- `type:security`
- `risk:safety-critical`
- `risk:high`
- `risk:normal`
- `blocked`
- `ready`

## Milestones created

1. `Rebuild containment and shared foundation`
2. `Windows preparation foundation`
3. `Ventoy integration and handoff generation`
4. `Arch live preflight and install foundation`
5. `Boot policy and Windows preservation`
6. `Omarchy handoff and guardrails`
7. `Boot guardian and long-term stability`
8. `Release automation and polish`

## GitHub setup notes

- Parent issues should be added to the project first.
- Child issues should inherit the correct milestone, layer, and risk settings.
- Safety-critical issues should be filtered into a dedicated review queue.
- Because GitHub's default `Status` field only supports `Todo`, `In Progress`, and `Done`, the project uses a custom `Rebuild Status` single-select field for the full workflow state model.
- Issues `#3` through `#16` are already added to project `#1` and stamped with milestone, labels, and custom field values.

## MCP coverage and manual follow-up

The available GitHub MCP tools support branches and issues, but they do not expose first-class operations for creating Projects, labels, or milestones. Those operations were completed through GitHub CLI after granting the local token the `project` scope. Future project administration can continue through GitHub CLI unless a Project-capable MCP surface becomes available.
