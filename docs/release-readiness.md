# Release readiness

Status: **blocked — do not publish or use on real hardware**.

Release approval requires, at minimum:

- [ ] exact pinned archinstall accepts generated config and credentials;
- [x] semantic validation completes before partition changes (ordered negative tests);
- [ ] GPT and ESP backups are verified and restore-tested;
- [x] Windows shrink and wrong-device Ventoy tests pass with synthetic devices;
- [ ] live ISO contains its locked Python runtime and starts offline;
- [x] both Textual TUIs remain responsive during worker-backed test operations;
- [ ] disposable QEMU/OVMF install and reboot pass;
- [ ] Windows EFI fallback remains intact;
- [ ] target user, sudo, NetworkManager, LUKS/Btrfs, and markers validate;
- [ ] normal-user pseudo-terminal Omarchy flow passes without auto-retry;
- [ ] ISO/EXE provenance pairing, signatures, and immutable release rules pass;
- [ ] recovery test passes and is documented.

Unit tests alone cannot satisfy this gate.

## Current blockers

- This host has no QEMU, `qemu-img`, OVMF, Docker, Bats, or installed Linux
  distribution and contains no non-dry-run ISO artifact.
- The isolated runner has not supplied an approved `OMARCHY_ISOLATED_VM_DRIVER`,
  so no install/reboot/recovery evidence exists.
- The exact installed archinstall 4.4 parser and Unix pseudo-terminal tests are
  CI-only and have not executed in this session.
- No managed Authenticode certificate, timestamp configuration, or signing
  secret contract is available for the EXE.

Next action: run the manual release workflow on the isolated Linux UEFI runner,
retain `vm-evidence.json` and `vm-gate-result.json`, verify the signed EXE, and
update this checklist only from those artifacts.
