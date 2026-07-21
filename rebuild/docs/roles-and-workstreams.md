# Roles And Workstreams

This rebuild is organized by ownership boundaries, not by convenience.

## Workstreams

### Shared

Owns schema, versioning, compatibility, common validation contracts, and shared constants.

### Windows Preparation

Owns Windows validation, BitLocker and Fast Startup handling, EFI and BCD backups, partition shrink, Ventoy integration, ISO placement, plan generation, and Windows-side version checks.

### Arch Live Installer

Owns Ventoy handoff discovery, plan validation, disk matching, networking, partition creation, `archinstall`, bootloader policy, Windows preservation validation, and live cleanup staging.

### Omarchy Handoff

Owns normal-user first-login logic, verified Omarchy launch control, and post-Omarchy completion.

### Boot Guardian

Owns once-per-boot health checks, expected-state comparisons, drift detection, and repair helpers.

### Build And Release Automation

Owns GitHub Actions workflows, Python build scripts, release manifests, checksums, and artifact publication.

### Docs And Coordination

Owns status reporting, dependency mapping, ownership mapping, issue templates, stage briefs, and coordination rules.

## Agent groups

### Copilot Scaffold

Used for directory scaffolding, templates, docs, and low-risk build support setup.

### Copilot Implement

Used for tightly scoped module implementation inside an already owned boundary.

### Human Review

Required for safety-critical work and for approving boundary changes, boot policy, partitioning, or Windows protection decisions.

### Codex Follow-up

Reserved for targeted follow-up slices that extend or harden an already established module.

### Mixed

Used when a slice combines a low-risk implementation step with human review or documentation updates.

## Section placement rules

- Shared contracts stay separate from Windows and Arch implementation directories.
- Build and CI work stays separate from runtime modules.
- Omarchy handoff stays separate from raw Arch install orchestration.
- Boot guardian stays separate from install-time and Omarchy-time logic.

## Review routing

- EFI, BCD, partitioning, BitLocker, Fast Startup, Secure Boot, boot policy, and Omarchy bootstrap assumptions require Human Review.
- Shared schema changes should be reviewed before consumer work is allowed to proceed.
