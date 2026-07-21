# Rebuild Architecture

This document defines the architecture contract for the Python rebuild inside `rebuild/`.

It is the source of truth for:

- layer boundaries
- ownership boundaries
- preserved transport and safety concepts
- core design and runtime rules
- target repository structure

## Scope

- Applies to the supported Python product, its assets, build tooling, and workflows.
- Archived source under `legacy/unsupported/` is outside the executable architecture.

## Four-Layer Model

| Layer | Name | Primary Responsibility | Inputs | Outputs | Must Not Do |
| --- | --- | --- | --- | --- | --- |
| Layer 0 | Build/Release | Build, package, and publish artifacts and metadata | Repo source, build scripts, templates | ISO/EXE artifacts, checksums, release metadata, compatibility metadata | Embed runtime installer behavior in workflow YAML |
| Layer 1 | Windows Preparation | Validate Windows state and prepare transport + handoff payload | User intent, system checks, shared schema contracts, release metadata | Deterministic handoff package and bootable transport | Perform Linux install operations |
| Layer 2 | Arch Live Installer | Execute install from live environment using validated handoff | Handoff payload, disk model contracts, compatibility contract | Installed system, boot configuration, persisted first-login inputs | Launch Omarchy directly from live install phase |
| Layer 3 | Installed-System Protections | Run normal-user first-login and post-install boot safety checks | Release pairing, install markers, expected boot state | Controlled Omarchy bootstrap and ongoing boot health guardrails | Re-run install-time partitioning or Windows preparation steps |

## Ownership Boundaries

| Boundary | Owning Workstream | Purpose |
| --- | --- | --- |
| `rebuild/installer/shared/**` | Shared | Shared schema, models, validation contracts, compatibility checks |
| `rebuild/installer/platforms/windows/**` | Windows Preparation | Windows checks, backups, partition prep, Ventoy + handoff generation |
| `rebuild/installer/platforms/linux_live/**` | Arch Live Installer | Live handoff validation, install orchestration, bootloader policy enforcement |
| `rebuild/installer/platforms/installed_system/**` | Omarchy Handoff + Boot Guardian | First-login flow, Omarchy timing control, boot drift detection |
| `rebuild/installer/ui/**` | UI Flow | User interaction flow and UX contracts only |
| `rebuild/tools/**` | Build/Release Automation | Build, packaging, release metadata, CI-invoked tooling |
| `rebuild/assets/**` | Shared Assets | Templates, service/unit assets, payload static files |
| `rebuild/docs/**` | Docs/Coordination | Architecture, status, ownership, dependencies, rules |
| `.github/workflows/**` | Build/Release Automation | CI orchestration only, no hidden runtime logic |

Authoritative coordination rules remain in:

- `rebuild/docs/ownership-map.md`
- `rebuild/docs/coordination-rules.md`

## Preserved Proven Concepts

The rebuild must preserve the following proven behaviors:

1. GitHub ISO model: release artifacts are built and published from repository automation.
2. Ventoy transport model: Windows preparation uses Ventoy flow to carry the ISO and handoff.
3. Live auto-start concept: the live environment auto-starts installer orchestration instead of manual shell sequencing.
4. Post-reboot Omarchy timing: Omarchy bootstrap occurs only after install completion and normal-user login.

These are preserved as architectural invariants while implementation details are rebuilt in Python modules.

## Core Design Principles

1. Python orchestrates; native OS tools execute system operations.
2. Deterministic and safety-first behavior takes precedence over convenience.
3. Fail closed on missing or incompatible contracts.
4. Preserve Windows safety boundaries during preparation and install.
5. Keep install-time responsibilities separate from post-install responsibilities.
6. Keep build/release logic separate from runtime logic.

## Command and transaction framework

All new platform operations use the shared framework in
`installer/shared/execution.py`, `atomic_io.py`, and `transactions.py`:

- commands are argv sequences, never shell strings;
- captured and inherited-terminal modes are explicit;
- allowlists, stable error codes, timeouts, pre-start cancellation, redacted
  progress events, and simulated state are first-class;
- simulation is not a succeeded execution;
- state is written through temporary files, file fsync, atomic replacement, and
  directory fsync where supported;
- disk, mount, and release transactions maintain durable journals and LIFO
  cleanup stacks;
- cleanup failure is an explicit failed state;
- unsafe cancellation boundaries are durable journal events.

## Runtime Boundaries

- Omarchy is post-install only and must never run from Windows preparation or Arch live install phases.
- Ventoy is transport only and not the source of install policy.
- Boot guardian logic is isolated from install-time partitioning and handoff generation.
- Platform modules may call native tools, but policy decisions and sequencing remain in Python orchestration.
- Shared schema and compatibility contracts are mandatory inputs for platform implementations.

## Target Repository Structure

```text
rebuild/
  installer/
    shared/
    platforms/
      windows/
      linux_live/
      installed_system/
    ui/
  tools/
  assets/
  docs/
.github/
  workflows/
```

### Structure Intent

- `installer/shared/` defines contracts consumed by platform layers.
- `installer/platforms/windows/` owns Layer 1 logic.
- `installer/platforms/linux_live/` owns Layer 2 logic.
- `installer/platforms/installed_system/` owns Layer 3 logic.
- `tools/` owns Layer 0 tooling consumed by CI.
- `assets/` stores templates and payload assets referenced by tools/runtime modules.
- `docs/` holds architecture and coordination contracts that gate implementation behavior.

## Enforcement

- PRs that cross boundaries without explicit ownership must be split or blocked.
- Safety-critical boundary changes require human review.
- Task tracker sequencing and status updates must reflect boundary-affecting changes.
