# Recovery guide

Recovery is fail-closed and must be rehearsed in a disposable UEFI VM before a
release can be approved.

## Before installation

- Keep the verified Windows BCD export, GPT primary/secondary backup, ESP file
  backup, BitLocker recovery information, and release manifests off the target
  disk.
- Record the target GPT disk GUID and ESP PARTUUID from the signed handoff.
- Confirm ordinary Windows recovery media boots independently.

## If installation stops

Do not rerun destructive stages blindly. Save the redacted journal and
diagnostics bundle, power down, and boot trusted recovery media. Match the disk
by GPT GUID and geometry before using any backup. Refuse recovery if identity is
ambiguous or backup verification fails.

## Boot recovery

The installed guardian may repair only an unambiguous firmware boot-order drift.
It must never repartition disks or replace Windows EFI files. For filesystem,
GPT, ESP, BitLocker, or BCD damage, use the verified pre-install backups and the
platform's native recovery tools. Recovery is not complete until both Windows
and Linux boot in UEFI mode and the measured boot state matches the expected
machine-state record.

## Evidence

Record VM firmware, disk fixture hashes, release artifact hashes, command logs,
reboot results, Windows EFI preservation, and restore verification in
`docs/test-evidence.md`. A unit test or dry run is not recovery evidence.
