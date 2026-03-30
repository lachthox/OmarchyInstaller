# File Ownership Map

This map exists to prevent overlapping active work.

## Hard rules

- Only one active implementation issue may own a file boundary at a time.
- Follow-up fixes may touch an existing boundary only when they are explicitly linked to the owning issue or pull request.
- Cross-boundary work requires review approval before implementation begins.

## Ownership boundaries

| Boundary                                          | Primary Workstream                | Default Agent Group | Required Reviewer | Notes                                                                                                        |
| ------------------------------------------------- | --------------------------------- | ------------------- | ----------------- | ------------------------------------------------------------------------------------------------------------ |
| `rebuild/installer/shared/**`                     | Shared schema and compatibility   | Copilot Implement   | Human Review      | Foundational contract used by Windows and Arch live layers                                                   |
| `rebuild/installer/platforms/windows/**`          | Windows preparation               | Copilot Implement   | Human Review      | Safety-critical when touching EFI, BCD, BitLocker, Fast Startup, Secure Boot, partition shrink, or backups   |
| `rebuild/installer/platforms/linux_live/**`       | Arch live installer               | Copilot Implement   | Human Review      | Safety-critical when touching partitioning, bootloader policy, Windows preservation, or live cleanup staging |
| `rebuild/installer/platforms/installed_system/**` | Omarchy handoff and boot guardian | Mixed               | Human Review      | Post-install ownership only                                                                                  |
| `rebuild/installer/ui/**`                         | UI flow                           | Copilot Implement   | Mixed             | Must not invent platform behavior contracts                                                                  |
| `rebuild/tools/**`                                | Build and release automation      | Copilot Scaffold    | Human Review      | GitHub Actions should invoke these tools rather than duplicate logic                                         |
| `rebuild/assets/**`                               | Shared assets                     | Copilot Scaffold    | Mixed             | Ownership follows consumer layer once files are bound to a runtime                                           |
| `rebuild/docs/**`                                 | Docs and coordination             | Copilot Scaffold    | Mixed             | Source of truth for status, ownership, dependency, and planning artifacts                                    |
| `.github/workflows/**`                            | Build and release automation      | Mixed               | Human Review      | Keep runtime logic out of YAML where possible                                                                |
| `.github/ISSUE_TEMPLATE/**`                       | Docs and coordination             | Copilot Scaffold    | Mixed             | Structured issue intake only                                                                                 |
| `.github/PULL_REQUEST_TEMPLATE.md`                | Docs and coordination             | Copilot Scaffold    | Mixed             | Review discipline for rebuild PRs                                                                            |

## Collision management

- Shared contracts must land before Windows and Arch consumers rely on them.
- Build and release work must not be bundled with runtime implementation unless the issue explicitly owns both boundaries.
- Boot guardian work must stay separate from install-time bootloader changes.
- Artifact lifecycle is bucketed as live ISO only, Ventoy USB only, temp staging, or final-system required; temp staging must stay under one directory and be removed after successful install.
