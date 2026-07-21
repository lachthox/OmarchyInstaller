# Plan Schema

This document defines the `plan.json` handoff contract used by the Windows preparation layer and the Arch live layer.

## Purpose

`plan.json` is the strict, versioned contract that tells the live installer what the Windows preparation step already validated and staged.

## Contract goals

- Validate the handoff rather than guessing.
- Keep the Windows producer and Arch consumer aligned.
- Prevent downstream work from inventing missing fields or implicit behavior.

## Required blocks

A valid plan must explicitly include the following information:

- `meta`
- `provenance`
- `disk_identity`
- `efi_identity`
- `windows_partition_identity`
- `prepared_free_space_range`
- `user_choices`
- `network`
- `omarchy_assumptions`
- `compatibility`

## Versioning rules

- The current schema is `1.0.0`.
- Producers and consumers reject incompatible versions.
- Safety-critical `0.1.0` plans are not auto-migrated. They must be regenerated
  by a current Windows producer so missing identity, geometry, and provenance
  fields are measured rather than guessed.
- Compatibility decisions must be explicit, not inferred from field presence alone.

## Validation rules

- Required fields must be present.
- Field types must be deterministic and strict.
- Unknown compatibility assumptions must fail closed.
- The consumer must validate the plan before using it for disk or boot operations.
- GPT is mandatory and the GPT disk GUID is the primary cross-boot identity.
- GPT partition GUID/PARTUUID and filesystem UUID occupy distinct fields.
- Every partition/free-space range carries its logical sector size and its byte
  size must equal the inclusive sector span.
- Disk and range sector sizes must agree.
- `user_choices` is a strict model covering hostname, username, locale, timezone,
  keyboard layout, free-space policy, LUKS2, Btrfs subvolumes, and boot policy.
- `omarchy_assumptions` permits only a pinned, normal-user interactive handoff
  with an expected bootstrap SHA256 and no automatic retry.
- Artifact provenance binds release tag, commit, workflow run, producer, ISO, and
  release-manifest hashes.

## Ownership

Primary boundary:

- `rebuild/installer/shared/**`

Producer boundary:

- `rebuild/installer/platforms/windows/**`

Consumer boundary:

- `rebuild/installer/platforms/linux_live/**`

## Inputs

- Windows safety checks
- Disk and partition probe data
- Backup destination metadata
- Ventoy and ISO placement data
- Network mode and non-secret Wi-Fi metadata; plaintext credentials are forbidden

## Outputs

- Versioned `plan.json`
- Compatibility check result
- Validation errors when the contract is incomplete or stale

## Implemented modules

- `rebuild/installer/shared/models.py`: strict Pydantic models for meta, disk identity, EFI identity, Windows partition identity, free-space range, user choices, network, and compatibility blocks.
- `rebuild/installer/shared/validation.py`: strict `PlanContract` and `CompatibilityContract` validators used by producer and consumer layers.
- `rebuild/installer/shared/compatibility.py`: compatibility evaluation and fail-closed enforcement helpers.
- `rebuild/installer/shared/versioning.py`: PEP 440 parsing and comparison through
  `packaging.version.Version`.

## Rules

- Do not add fields silently.
- Do not let the live installer fabricate missing handoff data.
- Keep shared contract changes ahead of producer and consumer changes.

## Coordination note

Any change to this schema must be reflected in the shared contract docs and the relevant issue hierarchy before dependent work proceeds.
