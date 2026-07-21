# Dependency map

| Producer | Consumer | Contract | State |
| --- | --- | --- | --- |
| Shared strict models | Windows and live platforms | Plan, compatibility, provenance, disk and partition identity | Complete |
| Windows preflight/backup/shrink | Ventoy handoff | Fresh target snapshot and verified backup manifest | Complete |
| Paired release artifacts | Windows handoff | Exact ISO and release-manifest SHA256 | Complete |
| Windows handoff | Live discovery | Plan, authenticated manifest, ISO hash, one-time out-of-band key | Complete |
| Live discovery/identity/network | Install engine | Revalidated plan, device paths, connectivity, credentials, confirmation | Complete |
| Install engine | Target finalizer | Mounted target, actual UUID/PARTUUID and release pairing | Complete |
| Target finalizer | First-login and guardian | Success marker, user runtime, expected machine state | Complete |
| ISO/EXE builders | Publisher | Same commit/tag/version/run/ref and artifact hashes | Complete |
| Isolated VM driver | Release publisher | Install/reboot/EFI/first-login/recovery evidence | Externally blocked |

Downstream code must fail closed when its producer contract is absent, stale,
ambiguous, malformed, simulated where apply is required, or inconsistent with a
fresh machine observation.
