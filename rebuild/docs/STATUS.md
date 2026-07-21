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
- The ISO contract is pinned to Arch `2026.07.01`/archinstall `4.4-1`; signed
  dated packages, a hash-locked Python venv, one canonical entrypoint, complete
  live command verification, and mount cleanup are implemented.
- Target finalization deploys and validates runtime, wrappers, units, actual
  machine state, boot assets, and protected directories before activation or
  atomic completion markers are permitted.

## Active work

- Phase 14: normal-user interactive Omarchy first-login flow.

## Known blockers

- Serena MCP is not exposed in this execution session; local memories are being
  refreshed manually.
- Docker/QEMU/OVMF are unavailable on the current host, so ISO boot, disposable
  install, reboot, and recovery gates remain open.
- Exact rootfs assembly and installed-system validation still require the
  destructive Linux VM acceptance environment.

## Readiness

See `docs/remediation-status.md`, `docs/test-evidence.md`, and
`docs/release-readiness.md`. Only those ledgers may claim subsystem readiness.
