# Windows preparation safety contract

Status: implemented with deterministic fixtures; not approved for real hardware
until the isolated Windows/VM and recovery gates pass.

## Identity

- The Windows system partition selects the target disk.
- The disk must be GPT and expose a GPT disk GUID.
- The disk number is recorded only as a runtime operation handle; it is not the
  durable identity.
- A missing serial remains empty and never becomes `disk-0` or similar.
- The ESP must have the EFI System Partition GPT type. FAT32 alone is rejected.
- ESP, Windows, and free-space observations come from the same selected disk.

## Verified backup

Apply mode creates and verifies:

- BCD export;
- JSON disk/partition snapshot;
- raw first and last 1 MiB GPT regions;
- the selected disk's ESP tree, mounted by disk and partition number;
- deterministic per-file ESP SHA256 entries and an aggregate hash;
- artifact hashes, source identities, tool version, and restore warning.

Apply mode requires an explicit backup destination off the Windows system disk;
the simulation-only working-directory default cannot authorize a resize.

The manifest is atomically written with `verification.status=verified`. A
simulation is explicitly `simulated` and cannot authorize resize.

## Contiguous shrink planning

Only the aligned free extent immediately after C: counts. A larger gap elsewhere
on the disk is irrelevant. The shrink request is the exact missing contiguous
space plus a documented 16 MiB alignment/measurement margin, bounded by
`Get-PartitionSupportedSize`.

Before resize, an atomic journal records source identities, backup manifest,
before geometry, intended size, and the fact that automatic rollback is not
supported. The disk is re-probed afterward. Identity drift or insufficient final
adjacent space is reported as `resize-applied-validation-failed`, not rollback or
success.

## Ventoy and handoff completion

The release EXE carries its immutable release tag and plan template. In a normal
run, the TUI downloads the paired ISO, release manifest, compatibility manifest,
and checksums from that tag, verifies their SHA256 values, caches them under
LocalAppData, and generates the paired base plan. Explicit local paths remain
available as development/test overrides.

The USB step re-enumerates removable disks, excludes read-only and protected
system/boot devices, auto-selects a sole candidate, and provides an Up/Down
picker when several safe USB disks are attached. It revalidates the target disk
after shrink, checks the ISO and release-manifest hashes against plan provenance,
then requires a second guided erase confirmation bound to Ventoy's exact
`ERASE <stable-id>` challenge. If Ventoy is absent, its official GitHub Windows
release and `sha256.txt` are downloaded, cross-checked against GitHub's asset
digest, verified, safely extracted, and cached. Apply mode performs two USB
identity checks around the write, validates the resulting data partition, copies
and re-hashes the ISO, and writes the authenticated plan bundle.

The TUI displays a newly generated 32-byte one-time key only after the handoff
stage. Record its 64 hexadecimal characters and enter them in the live TUI using
`H`; the key is never written to removable media. Network credentials are
entered interactively only in the live environment.
