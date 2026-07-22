# Release readiness

Status: **all 61 audit findings resolved; automated release gate is green.
Real-hardware use and public publication still require the two operational
sign-offs called out below (a production Authenticode certificate, and a
human decision to run against real disks).**

Release approval requires, at minimum:

- [x] exact pinned archinstall accepts generated config and credentials —
      proven for real against the installed `archinstall 4.4-1` package;
- [x] semantic validation completes before partition changes (ordered negative tests);
- [x] GPT and ESP backups are verified and restore-tested — real
      backup/damage/restore rehearsal passed (`recovery_passed: true`),
      re-confirmed in CI run `29886048248`;
- [x] Windows shrink and wrong-device Ventoy tests pass with synthetic devices;
- [x] live ISO contains its locked Python runtime and starts offline —
      proven with a real, non-dry-run ISO booted under real QEMU/OVMF;
- [x] both Textual TUIs remain responsive during worker-backed test operations;
- [x] disposable QEMU/OVMF install **and reboot** pass — install and
      post-reboot LUKS unlock both proven for real in CI run `29886048248`
      (`installation_completed: true`, `reboot_completed: true`);
- [x] Windows EFI fallback remains intact — verified byte-identical via
      SHA256 before/after a real install (`windows_efi_preserved: true`);
- [x] target user, sudo, NetworkManager, LUKS/Btrfs, and markers validate —
      verified by remounting the real installed target;
- [x] normal-user pseudo-terminal Omarchy flow passes without auto-retry —
      run for real as a non-root user under a real PTY (`first-login-pty`);
- [x] ISO/EXE provenance pairing and immutable release rules pass — the full
      `rebuild-release.yml` graph ran green end-to-end in CI run
      `29886048248` (see note on signing below);
- [x] recovery test passes and is documented.

Every acceptance box above is now checked, each backed by real (non-mocked,
non-dry-run) evidence rather than unit tests alone.

## Remaining operational sign-offs (not audit findings)

These are deployment decisions, not unresolved audit findings. All 61
enumerated findings are resolved (see `docs/remediation-status.md`).

1. **Production code-signing certificate.** No managed Authenticode
   certificate, timestamp configuration, or signing secret is provisioned
   for the Windows EXE. `sign_windows_exe.py` falls back to a
   clearly-labeled ephemeral test certificate (`production_signing: false`),
   and `publish_release.py` hard-fails publication unless a real production
   signing record is present. Supply the signing secret before publishing a
   release users will download. The CI `build-windows-exe` job verifies the
   signing *mechanics* with `Get-AuthenticodeSignature` (which does not
   require an OS trust chain), so a green CI run does not imply a
   production-trusted signature.

2. **Real-hardware authorization.** Every install/reboot/recovery proof to
   date was produced against disposable virtual disks in throwaway VMs.
   Running the installer against a real machine's real disks — which shrinks
   Windows, repartitions, and writes LUKS2 — is a destructive operation and
   remains a deliberate human go/no-go decision. Nothing in this repository
   grants that authorization automatically.

## How the reboot/LUKS blocker was closed

Earlier revisions of this document listed post-install reboot/login as an
open blocker after six failed unlock attempts. The root cause was a real
production bug (a trailing newline baked into the on-disk LUKS key via
`--key-file -`), not an environment or automation limitation. It is fully
described in `docs/remediation-status.md` ("Root cause of the post-install
LUKS-unlock gap") and `docs/test-evidence.md` Phase 21, and is proven fixed
by the real passphrase-prompt/`login:` transcript in
`serial-console-reboot.log` from CI run `29886048248`.
