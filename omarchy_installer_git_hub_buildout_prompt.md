# OmarchyInstaller GitHub Buildout Prompt
## Use this document as the GitHub-side execution prompt for planning, structuring, and building out the project on GitHub

> **Purpose of this document**  
> This document is intended to be used as the **GitHub-side prompt/instruction set** for building out the `OmarchyInstaller` project on GitHub itself.  
> It is specifically aimed at GitHub-native execution, including:
>
> - repository structuring
> - GitHub Project setup
> - issue hierarchy
> - labels
> - milestones
> - role boundaries
> - branch and PR discipline
> - safe implementation sequencing
> - build and release workflow setup
> - assigning work to the correct sections
>
> This document is not just a coding prompt. It is a **project setup and execution control prompt**.
>
> Treat this document as the source of truth for:
>
> - how the work should be organized on GitHub
> - how the rebuild should be staged
> - how responsibilities should be split
> - how Copilot should create and structure work items
> - how GitHub-native coordination should operate
>
> This must align with the main architecture spec already created for the project.
>
> Do not flatten this into one giant coding task.  
> Do not improvise around safety-critical workflow boundaries.  
> Do not merge unrelated work streams for convenience.

---

# 0. High-Level Intent

This rebuild is large enough that GitHub must be treated as the **project coordination layer**, not just a code host.

The correct GitHub-native approach is:
- one master GitHub Project
- one clear issue hierarchy
- strict workstream separation
- isolated rebuild area inside the repo
- controlled sequencing
- many small, reviewable pull requests
- explicit ownership boundaries

The rebuild must be managed like a controlled engineering program, not a casual refactor.

---

# 1. Mandatory First Principle

## Work begins inside `rebuild/`
The first implementation step must be to create a:

```text
rebuild/
```

folder in the repository root.

This is mandatory.

### Why
This rebuild is too large and too safety-sensitive to begin by rewriting the legacy repository in place.

`rebuild/` must be the safe containment zone for the new architecture.

### Hard rule
Do not plan the first phase as:
- “rewrite the old files directly”
- “refactor everything at once”
- “merge old and new flows immediately”

Instead:
- scaffold the new system inside `rebuild/`
- develop the new architecture there first
- keep legacy implementation separate until the new system becomes coherent enough to replace it deliberately

---

# 2. What GitHub Should Be Used For

GitHub should be used as the main coordination layer for this rebuild.

Use GitHub for:
- project tracking
- issue planning
- task decomposition
- dependency tracking
- review workflow
- milestones
- release automation
- branch/PR discipline
- status visibility

The repository itself remains the implementation source of truth, but GitHub is the orchestration surface.

---

# 3. Mandatory GitHub Project Setup

Create a GitHub Project for this rebuild.

## Project name
Recommended name:

```text
OmarchyInstaller Rebuild
```

## Project purpose
This project is the master board for tracking the full rebuild.

It must contain all major workstreams and their dependencies.

## Required status columns or equivalent fields
At minimum create statuses such as:
- Backlog
- Ready
- In Progress
- Blocked
- In Review
- Done

Optional but useful:
- Scaffolded
- Waiting on Dependency
- Needs Human Decision

## Recommended project fields
Add fields that allow grouping/filtering by:
- Layer
- Workstream
- Priority
- Risk level
- Dependency state
- Agent group

### Recommended field values

#### Layer
- Build/CI
- Shared
- Windows
- Arch Live
- Omarchy Handoff
- Boot Guardian
- Docs/Coordination

#### Workstream
- Schema
- UI
- Platform
- Ventoy
- Backup
- Partitioning
- Network
- Boot
- Packaging
- Release
- Security

#### Priority
- Critical
- High
- Normal
- Low

#### Risk
- Safety Critical
- High Risk
- Standard

#### Agent Group
- Copilot Scaffold
- Copilot Implement
- Human Review
- Codex Follow-up
- Mixed

---

# 4. Mandatory Issue Hierarchy

Do not create a flat pile of issues.

Use a hierarchy.

## 4.1 Create parent issues for major domains
Create parent issues for these domains:
- Rebuild foundation and containment
- Shared schema and compatibility layer
- Windows preparation layer
- Ventoy integration layer
- Arch live installer layer
- Omarchy handoff layer
- Boot guardian layer
- Build and release automation layer
- Docs and coordination layer

## 4.2 Parent issues are organizational, not dumping grounds
A parent issue should describe:
- what the domain owns
- why it exists
- what it depends on
- what child issues belong under it

Do not try to complete the entire parent issue in one PR.

## 4.3 Child issues must be tightly scoped
Examples of good child issues:
- Create `rebuild/` containment structure
- Create shared `plan_schema.py`
- Create shared version compatibility module
- Implement Windows EFI backup module
- Implement Windows Ventoy CLI wrapper
- Implement Windows ISO placement logic
- Implement Arch live `plan.json` loader
- Implement Arch disk matcher
- Implement Arch network fallback flow
- Implement Omarchy bootstrap location health check
- Add Windows EXE GitHub Actions workflow
- Add ISO rebuild trigger rules

Examples of bad child issues:
- Build Windows installer
- Build Arch installer
- Do boot stuff
- Finish whole rebuild

---

# 5. Mandatory Issue Template Structure

Every implementation issue should use a structured format.

The purpose is to make work digestible and deterministic.

## Every issue should contain these sections

### Goal
A single clear objective.

### Scope
Exactly what this issue is allowed to build or modify.

### Allowed files
Specific files or directories that this issue may touch.

### Forbidden files
Specific files or domains that this issue must not touch.

### Inputs
What already exists that this issue is allowed to assume.

### Outputs
What files, functions, modules, workflows, or docs must exist when this issue is complete.

### Rules
Special safety rules, naming rules, sequencing rules, or architectural constraints.

### Acceptance criteria
How to know this issue is complete.

### Out of scope
What this issue must explicitly not attempt to solve.

---

# 6. Required Workstream Separation

Work must be separated by ownership, not just by programming language or convenience.

## 6.1 Shared workstream
This workstream owns:
- shared models
- schema
- compatibility rules
- versioning
- common validation contracts
- shared constants

This workstream must be created early and treated as foundational.

## 6.2 Windows workstream
This workstream owns:
- Windows safety checks
- Secure Boot / BitLocker / Fast Startup logic
- EFI / BCD backup logic
- partition shrink logic
- Ventoy CLI integration
- ISO copy logic
- `plan.json` generation
- Windows-side update and version checks
- packaged EXE behavior

## 6.3 Arch live workstream
This workstream owns:
- Ventoy handoff discovery
- disk and partition matching
- network setup
- partition creation
- `archinstall`
- Limine and Windows preservation logic
- live cleanup staging

## 6.4 Omarchy handoff workstream
This workstream owns:
- first-boot wrapper
- upstream bootstrap location health checks
- Omarchy launch control
- post-Omarchy normalization

## 6.5 Boot guardian workstream
This workstream owns:
- once-per-boot health checks
- boot repair helpers
- expected state comparisons
- drift detection

## 6.6 Build/release workstream
This workstream owns:
- GitHub Actions workflows
- ISO build automation
- Windows EXE build automation
- rebuild triggers
- release manifests
- checksums
- release artifacts

## 6.7 Docs/coordination workstream
This workstream owns:
- status documents
- dependency maps
- ownership maps
- issue templates
- coordination rules
- stage briefs

---

# 7. Explicit Section Placement Rules

This is important.

## 7.1 Windows TUI section must include only Windows-side ownership
Put these under the Windows section:
- Windows platform checks
- backups
- Secure Boot / BitLocker / Fast Startup handling
- partition prep
- Ventoy CLI creation/preparation
- ISO placement
- `plan.json` generation
- Windows update/version logic
- Windows EXE packaging behavior

## 7.2 Arch TUI section must include only Arch live ownership
Put these under the Arch section:
- live preflight
- Ventoy handoff discovery
- disk matcher
- network setup
- partitioning
- `archinstall` runner
- bootloader logic
- Windows preservation validation
- cleanup staging

## 7.3 Keep Shared separate from both Windows and Arch
Do not bury shared schema/contracts under Windows or Arch.

## 7.4 Keep Build/CI separate from runtime work
Do not bury GitHub Actions, release workflows, or packaging logic inside Windows or Arch runtime issue groups.

## 7.5 Keep Omarchy handoff separate from raw Arch installation
Do not mix:
- live install orchestration
with
- post-install Omarchy wrapper logic

## 7.6 Keep Boot Guardian separate from both install-time and Omarchy-time logic
It is a long-term maintenance layer and should be organized as such.

---

# 8. Mandatory File Ownership Rules

GitHub Copilot must organize work to avoid overlapping edits.

## 8.1 Hard rule
No two active implementation issues should knowingly target the same file unless one is explicitly a follow-up or review fix for the other.

## 8.2 Required ownership map
Create a file ownership map under `rebuild/docs/`.

It should identify ownership boundaries for areas such as:
- `rebuild/installer/shared/**`
- `rebuild/installer/platforms/windows/**`
- `rebuild/installer/platforms/linux_live/**`
- `rebuild/installer/platforms/installed_system/**`
- `rebuild/tools/**`
- `.github/workflows/**`

## 8.3 Role assignment must follow file boundaries
Do not assign work in a way that causes uncontrolled file collisions.

---

# 9. Mandatory Dependency Mapping

This rebuild has real dependencies and GitHub work must reflect them.

## 9.1 Create a dependency map document
Create a dependency map in `rebuild/docs/`.

Examples of dependency relationships:
- Windows plan writer depends on shared schema
- Arch plan loader depends on shared schema
- Arch disk matcher depends on shared models
- Omarchy handoff depends on Arch install completion
- Boot guardian depends on boot policy implementation
- Windows EXE workflow depends on packaging config
- ISO workflow depends on payload structure

## 9.2 Hard rule
Do not let downstream issues invent missing layers.

If a dependency is not complete:
- mark downstream work blocked
- do not guess
- do not fake the missing layer

---

# 10. Labels

GitHub Copilot should help define labels that make work easy to filter.

Recommended labels:
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

---

# 11. PR Discipline Rules

GitHub Copilot must plan work so PRs remain reviewable.

## 11.1 Prefer one PR per issue or tightly related slice
Do not create giant PRs spanning many domains.

## 11.2 Keep PRs within a single workstream whenever possible
Examples of good PR scopes:
- shared schema layer
- Windows Ventoy integration
- Arch handoff loader
- Omarchy location health check
- EXE build workflow

## 11.3 Safety-critical PRs need extra review care
Any PR touching:
- EFI handling
- boot policy
- partitioning
- BitLocker / Fast Startup / Secure Boot
- Omarchy bootstrap assumptions

must be treated as higher scrutiny work.

---

# 12. Mandatory Initial GitHub Setup Tasks

Before broad coding begins, GitHub Copilot should create the project structure.

## 12.1 First issue
Create an issue like:

```text
Create rebuild/ containment structure and coordination docs
```

This issue should:
- create `rebuild/`
- create `rebuild/docs/`
- create `STATUS.md`
- create ownership/dependency docs
- not touch legacy production logic yet

## 12.2 Second issue
Create:

```text
Create shared schema and compatibility foundation inside rebuild/
```

This should be the first real implementation layer.

## 12.3 Third issue
Create:

```text
Create Windows platform foundation for checks and backups
```

## 12.4 Fourth issue
Create:

```text
Create Ventoy integration and ISO placement layer for Windows
```

## 12.5 Fifth issue
Create:

```text
Create Arch live handoff loader and preflight foundation
```

This ordering is intentional.

---

# 13. Status Ledger Requirement

Create a running truth file under `rebuild/docs/`, such as:

```text
STATUS.md
```

It should track:
- completed work
- in-progress work
- blocked work
- changed assumptions
- current next priority

GitHub issues and PRs should reference it where useful.

---

# 14. Safety and Blocking Policy

GitHub Copilot must organize work so safety-critical ambiguity does not propagate.

## 14.1 If a dependency is not solved, mark downstream work blocked
Do not ask agents to guess.

## 14.2 Keep safety-critical issues small
Do not batch too much boot, partitioning, or supply-chain logic together.

## 14.3 If a domain is incomplete, another domain must not fake it
Examples:
- Arch loader must not invent schema fields if shared schema is unfinished
- Windows plan writer must not invent boot assumptions if boot policy is unfinished
- Omarchy wrapper must not guess bootstrap assumptions if the location health-check contract is unfinished

---

# 15. Milestone Recommendations

GitHub Copilot should group work into milestones or equivalent parent issue groupings.

Recommended milestones:

## Milestone 1
Rebuild containment and shared foundation

## Milestone 2
Windows preparation foundation

## Milestone 3
Ventoy integration and handoff generation

## Milestone 4
Arch live preflight and install foundation

## Milestone 5
Boot policy and Windows preservation

## Milestone 6
Omarchy handoff and guardrails

## Milestone 7
Boot guardian and long-term stability

## Milestone 8
Release automation and polish

---

# 16. Acceptance Culture

GitHub Copilot must not treat “code exists” as “task done.”

A task is only done when:
- the scoped files exist
- the acceptance criteria are satisfied
- the task stayed inside its boundaries
- the PR is reviewable
- required docs/status files are updated

---

# 17. What GitHub Copilot Must Not Do

Do not:
- create one giant issue for the whole rebuild
- casually assign overlapping file ownership
- treat legacy files and rebuild files as the same working area early on
- create huge PRs spanning multiple unrelated domains
- hide safety-critical work in mixed refactors
- leave active implementation tasks under-specified
- skip the `rebuild/` containment step

---

# 18. Final Instruction to GitHub Copilot

When using GitHub to build out this project:
- treat GitHub as the coordination layer
- keep implementation work sliced and reviewable
- enforce ownership boundaries
- keep safety-critical work explicit
- make `rebuild/` the mandatory starting containment zone
- ensure every issue contains enough detail to be implemented without guessing
- ensure dependencies are represented honestly
- keep build/release work separate from runtime work
- protect the Windows safety guarantees in both planning and execution

If there is a choice between:
- fewer issues with more ambiguity
- or more issues with cleaner execution

choose more issues with cleaner execution.

This rebuild must be managed like a controlled engineering program, not a casual refactor.

