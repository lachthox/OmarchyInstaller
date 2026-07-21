# Test evidence

## Baseline at audited commit

Date: 2026-07-21

- `pytest -q rebuild/tests`: 13 passed, 1 failed. Failure:
  `test_firstboot_blocks_without_login` attempted to write the production
  `/var/lib/omarchy/firstboot` path on Windows.
- `ruff check rebuild`: failed with three unused imports.
- `mypy rebuild/installer rebuild/tools`: failed with eight errors in disk
  identity, install command typing, guardian severity, and orchestrator import.
- JSON parse validation: 2 files parsed successfully; this does not prove their
  production models accept them.
- Bats: blocked because WSL 2 is enabled but no Linux distribution is installed.
- Docker/Compose: unavailable.
- Workflow syntax: not yet independently validated.
- QEMU/OVMF ISO boot/install/reboot: blocked because the required runtime is not
  available on this host.

## Phase 1 evidence

- `pytest -q rebuild/tests/test_windows_launcher.py rebuild/tests/test_windows_flow.py`:
  6 passed.
- Focused Ruff check for the launcher, Windows app, EXE builder, and test: passed.
- Focused mypy reached one pre-existing transitive disk-model error; no new
  launcher/app/build errors were reported.
