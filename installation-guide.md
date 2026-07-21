# Installation guide

The product is not yet approved for installation on real hardware. There is no
supported bypass to the archived PowerShell or Bash implementations.

Development validation must use mocked command runners or a disposable VM. The
eventual supported journey is documented in
`docs/adr/0001-python-only-installer.md`; readiness evidence is tracked in
`docs/release-readiness.md` and `docs/remediation-status.md`.

Do not run `windows-prep.ps1`, `setup.sh`, Ventoy writes, partition changes,
BitLocker operations, EFI writes, or boot-order changes on a developer machine.
