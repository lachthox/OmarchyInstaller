# Issue hierarchy

The remediation work is organized by safety boundary, with the final acceptance
epic blocked until its evidence is produced.

| Epic | Scope | State |
| --- | --- | --- |
| Contracts and execution | Strict models, atomic state, command and transaction framework | Complete |
| Windows preparation | Preflight, backup, stable identity, shrink, Ventoy, authenticated handoff | Implemented; VM acceptance open |
| Arch live installation | Discovery, networking, storage, pinned archinstall, finalization | Implemented; VM acceptance open |
| Installed system | Normal-user first-login and machine-specific guardian | Implemented; PTY/VM acceptance open |
| Build and release | Paired provenance, pinned ISO, EXE, gated publication | Implemented; signing and VM gate open |
| Legacy retirement | Inert archive, obsolete tests removed, one supported journey | Complete |
| Final acceptance | Full install, reboot, Windows preservation, recovery, evidence reconciliation | Blocked on capable Linux UEFI VM runner |

Each implementation issue must state its goal, allowed and forbidden files,
inputs, outputs, safety rules, acceptance evidence, and out-of-scope work. A
finding closes only when the evidence required by `docs/remediation-status.md`
exists; implementation alone is not verification.
