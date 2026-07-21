# OmarchyInstaller

> [!CAUTION]
> Current releases are **not approved for real hardware**. The installer has
> unresolved destructive-operation and end-to-end validation findings. Use only
> mocked backends or disposable VMs until `docs/release-readiness.md` says every
> release gate passed.

OmarchyInstaller is being remediated into one Python-only dual-boot installer:

- a Textual Windows application for preflight, verified backup, shrink planning,
  release acquisition, Ventoy preparation, and authenticated handoff creation;
- a Textual Arch-live application for validated handoff discovery, networking,
  installation, finalization, diagnostics, and reboot readiness;
- a normal-user interactive first-login launcher for Omarchy;
- an installed-system Python boot guardian with fail-closed expected state.

## Supported entrypoints

The only supported Windows entrypoint is the packaged Python launcher at
`rebuild/tools/windows/omarchy_installer_launcher.py`. Python startup failures
are fatal and never fall back to another installer implementation.

The only intended live entrypoint is the installed Python package:

```text
/opt/omarchy-venv/bin/python -m installer.main
```

That packaged runtime and the complete installation flow are still undergoing
acceptance work. There is currently no approved real-hardware quick start.

## Retired implementations

The former shell and PowerShell entrypoints are inert `.txt` records under
`legacy/unsupported/`. They are not executable, imported, packaged, launched,
or accepted as compatibility paths. CI enforces one Python journey, one CI
workflow, and one gated release workflow.

## Development

Create a virtual environment and install the Python project with test tools:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".\rebuild[dev]"
.\.venv\Scripts\python.exe -m pytest -q rebuild\tests
.\.venv\Scripts\python.exe -m ruff check rebuild
.\.venv\Scripts\python.exe -m mypy rebuild\installer rebuild\tools
```

See `docs/installation-guide.md` and `docs/recovery.md`. Never point
installer tests at a real disk, ESP, USB device, or firmware store.

## Project status

- Finding ledger: `docs/remediation-status.md`
- Architecture decision: `docs/adr/0001-python-only-installer.md`
- Baseline and test evidence: `docs/test-evidence.md`
- Rebuild subsystem status: `rebuild/docs/STATUS.md`
