# Stage Briefs

This document turns the mandatory implementation order into concise coordination briefs. The rebuild must proceed in sequence; later stages should not assume earlier contracts exist until they are published.

## Stage 0 - Create `rebuild/` containment area

Purpose: establish the mandatory containment zone for the rebuild.
Owns: `rebuild/` boundaries, coordination docs, and the decision to keep legacy runtime files untouched.
Depends on: none.
Exit criteria: the rebuild lives under `rebuild/` and the coordination layer can track work without ambiguity.

## Stage 1 - Repo scaffold inside `rebuild/`

Purpose: create the initial directory and metadata scaffold for the new architecture.
Owns: package layout, tooling skeleton, and initial rebuild metadata.
Depends on: Stage 0.
Exit criteria: shared directories for docs, installer code, tools, and assets exist.

## Stage 2 - Shared schema and models

Purpose: define the shared contract used by Windows and Arch live layers.
Owns: `plan_schema.py`, shared models, versioning logic, and compatibility logic.
Depends on: Stage 1.
Exit criteria: the handoff contract is explicit enough for consumer layers to validate without guessing.

## Stage 3 - Windows platform layer

Purpose: implement Windows-side safety checks and prep logic.
Owns: system checks, disk probe, backup logic, BitLocker and Fast Startup checks, partition prep, Ventoy detection and preparation, ISO placement, and Omarchy bootstrap health-check metadata handling.
Depends on: Stage 2.
Exit criteria: Windows can safely prepare a Ventoy USB handoff without inventing missing contracts.

## Stage 4 - Windows TUI

Purpose: present the Windows preparation flow to the user.
Owns: screens, flow, summary and confirmation, and error handling.
Depends on: Stage 3.
Exit criteria: the Windows workflow is user-facing and deterministic.

## Stage 5 - Ventoy handoff generation

Purpose: materialize the handoff files that bridge Windows prep to Arch live.
Owns: ISO placement, `plan.json`, backup destination logic, and Wi-Fi handoff.
Depends on: Stages 2 and 3.
Exit criteria: the Ventoy USB contains all machine-specific handoff data in a predictable layout.

## Stage 6 - Arch live platform layer

Purpose: implement the live-environment platform logic that validates the prepared target.
Owns: Ventoy handoff discovery, disk matcher, Linux preflight, and network layer.
Depends on: Stage 5.
Exit criteria: the live environment can locate and validate the Windows-produced handoff.

## Stage 7 - Arch live TUI

Purpose: expose the Arch live workflow in an interactive interface.
Owns: preflight UI, network UI, install confirmation UI, and install progress UI.
Depends on: Stage 6.
Exit criteria: the live installer can drive the user through the validated install path.

## Stage 8 - Arch install orchestration

Purpose: perform the actual installation steps in the live environment.
Owns: partition creation, `archinstall` runner, encryption handling, and bootloader handling.
Depends on: Stages 6 and 7.
Exit criteria: the target system installs cleanly while preserving the required Windows and boot guarantees.

## Stage 9 - Omarchy handoff

Purpose: transition from installed Arch into the Omarchy post-install flow.
Owns: first-boot wrapper, pre and post checks, Omarchy launch flow, and Omarchy install-location health-check enforcement.
Depends on: Stage 8.
Exit criteria: Omarchy only runs after install completion and the bootstrap assumptions are validated.

## Stage 10 - Boot guardian

Purpose: provide ongoing boot-state validation and repair guidance.
Owns: health check logic, repair command behavior, and expected-state logic.
Depends on: Stage 9.
Exit criteria: boot drift can be detected against a defined target state.

## Stage 11 - Cleanup logic

Purpose: remove temporary artifacts and normalize the system after the install completes.
Owns: temp artifact cleanup and post-install normalization.
Depends on: Stage 9 and Stage 10 where applicable.
Exit criteria: the final installed system is clean and free of installer-only debris.

## Stage 12 - CI/CD

Purpose: automate packaging and release delivery.
Owns: Windows EXE build, ISO build, release automation, and rebuild triggers on relevant source and packaging changes.
Depends on: the stage contracts above being published and stable.
Exit criteria: the rebuild can be produced and released through repeatable automation.

## Execution rule

The stage order is mandatory. If a later stage needs a contract that is not yet available, the dependent work must be blocked rather than guessed into existence.
