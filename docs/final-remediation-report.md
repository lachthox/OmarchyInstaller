# Final remediation report

Date: 2026-07-21  
Branch: `fix/python-tui-full-remediation`  
Baseline: `08737764721d915921af4fa8a82015d3ea975fbd`

## Decision

The repository has one Python implementation and one gated release graph, but
release remains **blocked**. The current host cannot build/boot the real ISO or
run the mandatory disposable UEFI install, reboot, Windows-preservation, and
recovery test. No real-hardware use is approved.

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

## Finding result

The ledger contains all 61 audit IDs: 53 resolved and 8 verification-blocked.
No finding is silently waived. See `docs/remediation-status.md`.

## Limitations and next action

An isolated Linux runner must provide QEMU, OVMF, `qemu-img`, Bats, the pinned
archinstall package, a non-dry-run ISO, and an approved console-automation driver
through `OMARCHY_ISOLATED_VM_DRIVER`. Run the release workflow and retain its VM
evidence. Then perform and document the restore rehearsal. Separately, configure
managed Authenticode signing credentials and verification for the Windows EXE.

Recovery procedure: `docs/recovery.md`. Detailed commands and observed results:
`docs/test-evidence.md`. Release decision: `docs/release-readiness.md`.
