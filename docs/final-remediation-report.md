# Final remediation report

Date: 2026-07-22
Branch: `fix/python-tui-full-remediation`
Baseline: `08737764721d915921af4fa8a82015d3ea975fbd`

## Decision

The repository has one Python implementation and one gated release graph, but
release remains **blocked**. A disposable, KVM-accelerated Linux environment
was provisioned specifically to close the environment gap the prior phase
left open: the real ISO now builds and boots for real, the real production
TUI drives a real disposable UEFI install through to completion (real GPT,
LUKS2, Btrfs, archinstall 4.4-1, Limine, and target finalization), Windows
EFI preservation is verified byte-for-byte, and the backup/restore recovery
rehearsal passes for real. What remains genuinely unresolved is narrower and
more specific than before: unlocking the LUKS2 volume on the *installed*
disk through serial-console automation after reboot has not succeeded after
six independent attempts, and a green run of the CI VM jobs (now retargeted
at GitHub-hosted, KVM-capable runners) has not yet been observed. No
real-hardware use is approved until both close.

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
  onto GitHub-hosted runners that can actually execute them, and pushed this
  branch to trigger a real run.

## Finding result

The ledger contains all 61 audit IDs: 57 resolved and 4 verification-blocked
(`CRIT-03`, `CRIT-05`, `HIGH-32`, `MED-15` — all four share the single root
cause described below). No finding is silently waived. See
`docs/remediation-status.md`.

## Limitations and next action

The real disposable install completes successfully and is verified correct
by remounting the target, but the post-reboot LUKS2 unlock could not be
driven through the serial-console automation after six independent fix
attempts (line-ending variations, slower typing, `cache=writeback` instead
of `cache=unsafe`, and a corrected retry loop) — this is an
automation/tooling gap in driving `systemd-ask-password` over a raw serial
console, not an installed-system defect. Separately, the retargeted CI VM
jobs have been pushed and triggered but a green run has not yet been
observed; re-check the Actions run before treating HIGH-32/MED-15 as
closed. Configure managed Authenticode signing credentials for the Windows
EXE before any production (non-ephemeral-cert) release.

Recovery procedure: `docs/recovery.md`. Detailed commands and observed results:
`docs/test-evidence.md`. Release decision: `docs/release-readiness.md`.
