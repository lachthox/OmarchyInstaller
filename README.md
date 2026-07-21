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

## Legacy status

`windows-prep.ps1`, `setup.sh`, and `.github/workflows/build-iso.yml` are retained
temporarily for forensic comparison only. They are unsupported, must not be
packaged or launched by the Python product, and will be archived only after the
Python parity and VM gates pass.

## Development

Create a virtual environment and install the Python project with test tools:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".\rebuild[dev]"
.\.venv\Scripts\python.exe -m pytest -q rebuild\tests
.\.venv\Scripts\python.exe -m ruff check rebuild
.\.venv\Scripts\python.exe -m mypy rebuild\installer rebuild\tools
```

Shell/Bats and VM test instructions are in `vmtest/README.md` in the parent
workspace when that harness is available. Never point installer tests at a real
disk, ESP, USB device, or firmware store.

## Project status

- Finding ledger: `docs/remediation-status.md`
- Architecture decision: `docs/adr/0001-python-only-installer.md`
- Baseline and test evidence: `docs/test-evidence.md`
- Rebuild subsystem status: `rebuild/docs/STATUS.md`
