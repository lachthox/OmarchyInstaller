# Python rebuild status

## Current state

The Python implementation is the canonical replacement under remediation. It is
not approved for real hardware and no release workflow may treat dry-run or unit
test success as installation success.

## Completed gates

- Audited checkout and dedicated remediation branch established.
- All 61 audit findings entered in `docs/remediation-status.md`.
- Real-hardware warning added to top-level documentation.
- Packaged Windows launcher no longer bundles, exposes, or falls back to the
  legacy PowerShell installer.
- Launcher failure behavior has focused automated coverage.
- Windows preflight, backup, and partition stages execute in Textual workers;
  simulation, failure, blocking, stale-state invalidation, and cancellation have
  Pilot coverage at 80x24.

## Active work

- Phase 5: Windows identity, backup, and contiguous shrink planning.

## Known blockers

- Serena MCP is not exposed in this execution session; local memories are being
  refreshed manually.
- Docker/QEMU/OVMF are unavailable on the current host, so ISO boot, disposable
  install, reboot, and recovery gates remain open.
- Exact external archinstall and Omarchy contracts still require pinned-version
  verification before installation-engine work.

## Readiness

See `docs/remediation-status.md`, `docs/test-evidence.md`, and
`docs/release-readiness.md`. Only those ledgers may claim subsystem readiness.
