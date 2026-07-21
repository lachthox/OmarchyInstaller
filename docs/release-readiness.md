# Release readiness

Status: **blocked — do not publish or use on real hardware**.

Release approval requires, at minimum:

- [x] exact pinned archinstall accepts generated config and credentials —
      proven for real against the installed `archinstall 4.4-1` package;
- [x] semantic validation completes before partition changes (ordered negative tests);
- [x] GPT and ESP backups are verified and restore-tested — real
      backup/damage/restore rehearsal passed (`recovery_passed: true`);
- [x] Windows shrink and wrong-device Ventoy tests pass with synthetic devices;
- [x] live ISO contains its locked Python runtime and starts offline —
      proven with a real, non-dry-run ISO booted under real QEMU/OVMF;
- [x] both Textual TUIs remain responsive during worker-backed test operations;
- [ ] disposable QEMU/OVMF install and reboot pass — **install passes for
      real; reboot/login does not** (see below);
- [x] Windows EFI fallback remains intact — verified byte-identical via
      SHA256 before/after a real install;
- [x] target user, sudo, NetworkManager, LUKS/Btrfs, and markers validate —
      verified by remounting the real installed target;
- [x] normal-user pseudo-terminal Omarchy flow passes without auto-retry —
      run for real as a non-root user under a real PTY;
- [ ] ISO/EXE provenance pairing, signatures, and immutable release rules
      pass — provenance logic is implemented and unit-tested, but has not
      yet run in a real, successful CI release job;
- [x] recovery test passes and is documented.

Unit tests alone cannot satisfy this gate. The two remaining open boxes are
now the only two things standing between this branch and release approval.

## Current blockers

1. **Post-install reboot/login is not verified.** A real disposable UEFI
   install (GPT + LUKS2 + Btrfs + archinstall 4.4-1 + Limine + target
   finalization) completed successfully through the real production TUI on
   a KVM-accelerated disposable VM, and the installed target was verified
   correct by remounting it. However, booting that installed disk with the
   ISO detached and unlocking its LUKS2 volume through the serial-console
   automation has not succeeded after six independent fix attempts (see
   `docs/test-evidence.md` Phase 21 for the exact attempts and symptom).
   This blocks CRIT-03, CRIT-05, HIGH-32, and MED-15 from closing.
2. **No successful CI run has been observed yet.** The VM jobs in
   `.github/workflows/rebuild-release.yml` were moved from an unregistered
   `self-hosted` runner label (which could never have produced evidence) to
   `ubuntu-latest`, which does have the `/dev/kvm` access these jobs need on
   this public repository. The branch has been pushed and a
   `workflow_dispatch` run triggered, but a green run — and therefore the
   VM/reboot/recovery evidence artifacts it would produce — had not yet
   completed as of this writing. Re-check the Actions run before treating
   HIGH-32/MED-15 as closed.
3. No managed Authenticode certificate, timestamp configuration, or signing
   secret contract is available for the EXE; `sign_windows_exe.py` falls
   back to a clearly-labeled ephemeral test certificate
   (`production_signing: false`) and `publish_release.py` hard-fails
   publication unless a real, production signing record is present.

Next action: watch the triggered Actions run to completion; if
`vm-install-reboot` still fails at the reboot step, treat that as
independent confirmation of blocker 1 above rather than an environment
problem, and continue investigating the `systemd-ask-password`/serial
console interaction specifically (candidates: a QEMU `-chardev`/`pty`
plumbing issue, or the initramfs reading from a console device the driver
isn't writing to). Do not mark CRIT-03, CRIT-05, HIGH-32, or MED-15
resolved until a real reboot-and-login pass exists.
