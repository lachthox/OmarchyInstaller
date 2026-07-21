# ADR 0001: Python-only installer

Status: Accepted architecture; implementation and acceptance gates in progress.

## Decision

OmarchyInstaller has one supported product architecture. It never silently
falls back to PowerShell or the legacy Bash installer.

### Windows phase

```text
Python Textual TUI
-> environment preflight
-> stable GPT target identity
-> verified Windows/BCD/ESP/GPT backup
-> contiguous shrink planning and typed apply confirmation
-> post-resize validation
-> verified release acquisition
-> safe Ventoy USB selection and install
-> copied ISO hash verification
-> authenticated, artifact-bound handoff
-> reboot instructions
```

### Arch live phase

```text
Python Textual TUI
-> read-only handoff discovery and verification
-> GPT disk/partition identity and usable-extent validation
-> real internet readiness
-> destructive summary and typed confirmation
-> GPT diagnostics and backup
-> partition, LUKS2, Btrfs subvolumes, and complete mount tree
-> verified existing ESP mount
-> pinned archinstall config and separate credentials validation
-> pre-mounted archinstall execution
-> target runtime/finalization and validation
-> atomic success evidence
-> deterministic cleanup
-> reboot readiness
```

### Installed-system phase

```text
normal-user login
-> interactive Omarchy launcher with a real TTY
-> pinned/verified download to a file
-> source, version, SHA256, state, and redacted transcript
-> independent Omarchy completion
-> boot-policy verification
-> guardian enablement only with machine-specific expected state
-> overall completion
```

## Safety invariants

- Unknown, stale, ambiguous, or changed destructive state blocks apply mode.
- No partition change occurs before complete semantic plan validation.
- GPT disk GUID is primary identity; PARTUUID and filesystem UUID are distinct.
- Simulation is reported as `simulated`, never `completed`.
- Success requires measured postconditions and atomic evidence.
- Credentials never appear in argv, ordinary logs, or removable-media plaintext.
- Cleanup runs on success and failure; cancellation is disabled after unsafe
  transaction boundaries.
- Real-hardware use remains prohibited until isolated install, reboot, Windows
  EFI preservation, recovery, and first-login tests pass.

## External contracts

The exact Arch ISO, bundled archinstall version, and Omarchy bootstrap contract
must be pinned from current official sources before Phase 12. Until that research
is recorded here with contract-test evidence, installation-engine changes are
blocked by design.

## Legacy retirement

`windows-prep.ps1`, `setup.sh`, and `.github/workflows/build-iso.yml` are
unsupported forensic references during remediation. They may be moved to
`legacy/unsupported/` only after Python parity and end-to-end VM gates pass.
