# Release readiness

Status: **blocked — do not publish or use on real hardware**.

Release approval requires, at minimum:

- [ ] exact pinned archinstall accepts generated config and credentials;
- [ ] semantic validation completes before partition changes;
- [ ] GPT and ESP backups are verified and restore-tested;
- [ ] Windows shrink and wrong-device Ventoy tests pass;
- [ ] live ISO contains its locked Python runtime and starts offline;
- [ ] both Textual TUIs remain responsive during long-running work;
- [ ] disposable QEMU/OVMF install and reboot pass;
- [ ] Windows EFI fallback remains intact;
- [ ] target user, sudo, NetworkManager, LUKS/Btrfs, and markers validate;
- [ ] normal-user pseudo-terminal Omarchy flow passes without auto-retry;
- [ ] ISO/EXE provenance pairing, signatures, and immutable release rules pass;
- [ ] recovery test passes and is documented.

Unit tests alone cannot satisfy this gate.
