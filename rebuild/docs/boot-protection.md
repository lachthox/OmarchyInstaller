# Boot Protection

This document defines the boot guardian contract for the rebuild. It is the coordination reference for post-install boot health checks and repair guidance.

## Purpose

Boot protection exists to keep the installed system bootable after installation and after Omarchy handoff. It measures the observed boot state against an expected state and surfaces drift clearly.

## Scope

- Post-install only.
- Applies after the live installer has completed and control has moved to the installed system.
- Covers health checks, expected-state comparison, drift detection, and repair guidance.

## Ownership

Primary boundary:

- `rebuild/installer/platforms/installed_system/**`

Supporting coordination files:

- `rebuild/docs/STATUS.md`
- `rebuild/docs/dependency-map.md`
- `rebuild/docs/issue-hierarchy.md`

## Rules

- Do not re-run install-time partitioning or Windows prep from the boot guardian layer.
- Do not invent repair behavior without a defined expected-state contract.
- Keep Omarchy launch control separate from generic boot drift detection.
- Treat EFI, BCD, Secure Boot, and Windows-preservation issues as safety-sensitive.

## Inputs

- Expected boot state definition.
- First-boot and post-install markers.
- Installation results from the live environment.
- Observed boot measurements from the installed system.

## Outputs

- Boot health result.
- Drift report when the observed state differs from the expected state.
- Repair guidance or abort status when the state is unsafe.

## Safety guidance

The boot guardian should fail closed when:

- the expected state is missing or incompatible
- the observed boot state cannot be measured reliably
- a repair would cross back into install-time responsibilities
- a repair would weaken Windows preservation guarantees

## Coordination note

The boot guardian is a long-term protection layer, not part of the live installer or the Windows preparation flow.
