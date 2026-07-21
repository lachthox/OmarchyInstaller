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

## Phase 2 evidence

- `pytest -q rebuild/tests`: 26 passed.
- `ruff check rebuild`: passed.
- `mypy rebuild/installer rebuild/tools`: one remaining pre-existing error, the
  Phase 16 task-orchestrator script import; all shared-contract and consumer
  modules passed.
- `test_shared_contracts.py` verifies production loading of both shipped JSON
  templates, GPT-only identity, inclusive sector arithmetic, UUID namespace
  separation, strict extra-field rejection, fail-closed legacy schema handling,
  cross-contract sector-size consistency, and standards-compliant prereleases.

## Phase 3 evidence

- `pytest -q rebuild/tests/test_execution_transactions.py`: 13 passed.
- Focused Ruff and mypy for all shared framework modules: passed.
- Evidence covers atomic replacement, temporary-file cleanup after simulated
  replace failure, cleanup on success/handled failure/exception/cancellation,
  cleanup failure, interrupted-journal recovery, simulation state, allowlists,
  secret redaction, inherited-terminal enforcement, and pre-start cancellation.

## Phase 4 evidence

- `pytest -q rebuild/tests/test_windows_tui_pilot.py`: 5 passed.
- Focused Ruff and mypy for the Windows Textual app: passed.
- Textual Pilot evidence covers 80x24 layout, keyboard/Vim/Tab navigation,
  worker-backed refresh, fail-closed disk snapshot errors, a deliberately blocked
  long-running backup while the UI continues handling keys, stale-result
  invalidation, and cancellation reported as `cancelled` rather than success.

## Phase 5 evidence

- Full Python suite: 57 passed.
- Full Ruff: passed.
- Mypy: only the pre-existing Phase 16 task-orchestrator import remains.
- `test_windows_disk_safety.py` covers empty adjacency, a true adjacent gap, a
  larger non-adjacent gap, recovery partitions, misleading FAT32 partitions,
  missing ESP, absent serial, 512/4096-byte sectors, exact shrink plus 16 MiB
  margin, insufficient supported shrink, mismatched backup identity, successful
  validation, and identity drift after an applied resize.
- `test_windows_backup.py` verifies selected-ESP per-file hashing, aggregate
  hashing, source identity binding, raw GPT artifacts, and simulated-not-verified
  dry runs.

## Phase 6 evidence

- `pytest -q rebuild/tests/test_windows_handoff.py rebuild/tests/test_shared_contracts.py`:
  18 passed.
- Focused Ruff and mypy for Windows handoff: passed.
- Evidence proves non-USB/internal targets, wrong typed confirmation, and identity
  races execute no Ventoy command; matching identity is read twice before write;
  ISO copy hashes match; corruption removes the copy; FAT32 rejects a sparse file
  over 4 GiB; plaintext Wi-Fi handoff is blocked; and plan/ISO/provenance are
  HMAC-bound with a one-time key.
