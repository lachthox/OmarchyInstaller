# Final remediation report

Date: 2026-07-22
Branch: `fix/python-tui-full-remediation`
Baseline: `08737764721d915921af4fa8a82015d3ea975fbd`

## Decision

The repository has one Python implementation and one gated release graph, and
**all 61 audit findings are now resolved**. A disposable, KVM-accelerated
Linux environment was provisioned to close the environment gap the prior
phase left open: the real ISO builds and boots for real, the real production
TUI drives a real disposable UEFI install through to completion (real GPT,
LUKS2, Btrfs, archinstall 4.4-1, Limine, and target finalization), Windows
EFI preservation is verified byte-for-byte, and the backup/restore recovery
rehearsal passes for real. The final gap — unlocking the LUKS2 volume on the
*installed* disk after reboot — was traced to a real production bug (a
trailing newline baked into the on-disk LUKS key via `cryptsetup --key-file
-`) and fixed; the full CI VM graph now runs **green end-to-end** on
GitHub-hosted KVM runners (run `29886048248`), including a real post-reboot
LUKS unlock and the recovery rehearsal.

Two operational sign-offs remain, neither of which is an unresolved audit
finding: a production Authenticode signing certificate must be provisioned
before publishing a downloadable EXE (the CI path uses a clearly-labeled
ephemeral test cert), and running the installer against a real machine's
real disks is a deliberate destructive-operation go/no-go decision that this
work does not grant automatically. **No real-hardware use is authorized here.**

## Before and after

Before remediation, executable Bash and PowerShell products competed with a
partial Python scaffold; contracts were permissive, startup/package metadata
disagreed, destructive sequencing was not transactional, interactive work could
block Textual, first boot ran privileged bootstrap logic, and publishers could
produce unrelated artifacts.

After remediation, the supported path is:

```text
Python Windows TUI
  -> verified backup and stable-GPT shrink
  -> validated Ventoy target and authenticated paired handoff
  -> Python Arch-live TUI
  -> machine/network revalidation and disk-bound confirmation
  -> LUKS2/Btrfs + pinned pre-mounted archinstall
  -> fail-closed target finalization
  -> normal-user verified first-login
  -> machine-specific guardian
```

The superseded programs are inert `.txt` records. Shared strict models, atomic
writes, journals, OS locks, redaction, exact provenance, pinned dependencies,
and fail-closed publication gates cover the supported path.

## Phase summary

- Phases 0–3 established the audited baseline, strict contracts, atomic command
  execution, and durable transactions.
- Phases 4–7 implemented responsive Windows preparation, verified backup/shrink,
  safe Ventoy handoff, and immutable paired release provenance.
- Phases 8–13 pinned and packaged the live runtime, authenticated discovery and
  identity, layered network readiness, real install orchestration, exact
  archinstall contracts, and target finalization.
- Phases 14–16 implemented normal-user first-login, machine-specific guardian
  policy, and crash-safe orchestration state.
- Phases 17–19 replaced obsolete tests, created the gated CI/release graph, and
  retired every executable compatibility path.
- Phase 20 connected the live TUI apply action to the production engine, added
  Windows Ventoy/handoff completion, added the fail-closed VM evidence harness,
  reconciled all findings, and reran every locally available gate.
- Phase 21 built a disposable KVM-accelerated Linux environment and used it to
  run every previously environment-blocked gate for real: the exact pinned
  archinstall 4.4-1 upstream parser, a real non-dry-run ISO build (and a real
  interrupted-build cleanup bug found and fixed), a real OVMF offline boot, a
  real disposable dual-boot GPT/LUKS2/Btrfs install driven through the real
  production TUI with verified Windows EFI preservation, a real non-root PTY
  first-login run, and a real backup/damage/restore recovery rehearsal. It
  also retargeted the CI VM jobs from an unregistered self-hosted runner label
  onto GitHub-hosted runners that can actually execute them, then drove the
  full graph to a green run (`29886048248`) — fixing the production LUKS-key
  trailing-newline bug and a series of real CI failures at their root causes
  along the way.

## Finding result

The ledger contains all 61 audit IDs, **all 61 resolved**, none silently
waived. The final four to close (`CRIT-03`, `CRIT-05`, `HIGH-32`, `MED-15`)
shared a single root cause — the post-reboot LUKS unlock — which is now
fixed and proven in CI. See `docs/remediation-status.md`.

## Limitations and next action

The post-reboot LUKS2 unlock was the last finding to close. Earlier attempts
mistakenly varied what was *sent* to the passphrase prompt (line-endings,
typing speed, QEMU cache mode, retry loop); the actual defect was on the
*write* side — `rebuild/installer/platforms/linux_live/install.py` appended
`"\n"` to the passphrase piped to `cryptsetup --key-file -`, which reads
stdin as raw key material with no line-ending stripping, so the newline was
baked into the real on-disk key and no interactive unlock could ever
reproduce it. Removing the `+ "\n"` (and the matching `echo` → `printf '%s'`
fix in the driver's diagnostic helpers) fixed it; CI run `29886048248`
records a real post-reboot `login:` with `reboot_completed: true`. This was a
genuine production bug that would have broken every real install using this
path, not just VM testing.

Two operational items remain outside the audit scope. Configure managed
Authenticode signing credentials for the Windows EXE before any production
(non-ephemeral-cert) release — CI verifies signing *mechanics* only, not a
trusted chain. And treat any real-hardware run as a separate, deliberate
go/no-go decision; all evidence to date is against disposable virtual disks.

Recovery procedure: `docs/recovery.md`. Detailed commands and observed results:
`docs/test-evidence.md`. Release decision: `docs/release-readiness.md`.
