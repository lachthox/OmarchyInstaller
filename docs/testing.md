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
isolated QEMU/OVMF gate. The VM gate accepts exactly one non-dry-run ISO and
requires evidence for Windows-prep simulation, UEFI boot, Python TUI startup,
installation, reboot, Windows EFI preservation, normal-user first-login, and a
recovery restore test. Mocked, dry-run, missing, or incomplete evidence fails.

No test may target a host disk, USB device, ESP, firmware store, or real Windows
installation. VM evidence belongs under the harness work directory only.
