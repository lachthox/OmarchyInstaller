# Release readiness

Status: **all 61 audit findings resolved; automated release gate is green and
can publish an unsigned open-source release now.** Real-hardware use still
requires a deliberate human decision to run against real disks (below), and
code signing is available as an optional upgrade (`docs/windows-code-signing.md`)
rather than a publication blocker.**

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

1. **Code signing (optional; unsigned is the current default).** No managed
   Authenticode certificate is provisioned, so the release workflow publishes
   an **unsigned** Windows EXE: `sign_windows_exe.py` records
   `production_signing: false` / `signed: false`, and the publish step runs
   with `--allow-unsigned`, which permits that instead of failing closed.
   Users will see a Windows SmartScreen warning; origin/integrity are covered
   by `sha256sums.txt` and GitHub build-provenance attestation. To ship a
   real trusted signature instead (including the free SignPath Foundation OSS
   option), follow `docs/windows-code-signing.md`: add the signing secrets and
   drop `--allow-unsigned` to restore the fail-closed gate. This is an
   optional upgrade, not a publication blocker.

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
