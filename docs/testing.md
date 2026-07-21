# Testing

The local non-destructive gate is:

```powershell
.\.venv\Scripts\python.exe -m pytest rebuild\tests -q
.\.venv\Scripts\python.exe -m ruff check rebuild
.\.venv\Scripts\python.exe -m mypy --no-incremental rebuild
.\.venv\Scripts\python.exe rebuild\tools\check_no_legacy_production_refs.py
```

Linux CI additionally runs ShellCheck, Bats, the installed archinstall 4.4
parser, pseudo-terminal first-login coverage, real ISO construction, and the
QEMU/OVMF gate. The VM gate accepts exactly one non-dry-run ISO and
requires evidence for Windows-prep simulation, UEFI boot, Python TUI startup,
installation, reboot, Windows EFI preservation, normal-user first-login, and a
recovery restore test. Mocked, dry-run, missing, or incomplete evidence fails.
The VM jobs (`offline-iso-boot`, `vm-install-reboot`, `recovery-rehearsal`) run
on GitHub-hosted `ubuntu-latest` runners, which expose `/dev/kvm` on this
public repository — no self-hosted runner needs to be provisioned.

No test may target a host disk, USB device, ESP, firmware store, or real Windows
installation. VM evidence belongs under the harness work directory only.

All of the above except the reboot half of the install/reboot gate has been
executed for real, non-mocked, on a disposable KVM-accelerated Linux
environment: see `docs/test-evidence.md` (Phase 21) for exact commands and
results, and `docs/release-readiness.md` for what remains open.
