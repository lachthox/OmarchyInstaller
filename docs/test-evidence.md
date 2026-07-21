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

## Phase 7 evidence

- Full Python suite: 74 passed; full Ruff: passed.
- `test_release_provenance.py` covers strict semantic VERSIONINFO, a valid exact
  ISO/EXE pair, dry-run rejection, commit mismatch, tampered hash, ambiguous
  recursive matches, immutable existing tags, and upload without clobber.
- GitHub artifact attestation configuration follows the official current
  `actions/attest@v4` contract and runs before optional publication.
- Authenticode remains externally blocked because no certificate/key service or
  CI signing-secret contract is available.

## Phase 8 evidence

- Full Python suite: 78 passed; full Ruff: passed.
- Full mypy retains only the pre-existing Phase 16 task-orchestrator import.
- ISO dry-run produces the pinned `2026.07.01` source identity, release
  version/tag/commit, `archinstall 4.4-1`, canonical venv module entrypoint,
  complete runtime command list, and no compatibility aliases.
- `test_iso_packaging.py` verifies the dated mirror, hash lock, signature-safe
  pacman contract, exact archinstall check, cwd-independent package import,
  runtime binary verification, and cleanup trap.
- The official Arch release and package indexes establish that ISO 2026.07.01
  is available and archinstall `4.4-1` was published for that ISO cycle.
- Real rootfs assembly, OVMF boot, and offline TUI startup are blocked because
  this host has no Linux distribution, Docker, QEMU, or OVMF.

## Phase 9 evidence

- Full Python suite: 86 passed; full Ruff passes; focused Linux-live mypy passes.
- `test_linux_handoff_identity.py` covers nested mount topology, deliberate
  removable VENTOY selection, read-only mount options, guaranteed unmount,
  authenticated plan/ISO hashes, stale and tampered handoffs, exact GPT disk
  GUID matching, absent serials, duplicate identities, filesystem UUID namespace
  separation, GPT first/last usable sectors, a stale occupied extent immediately
  before creation, and post-creation alignment changes.
- The install transaction records the created partition's actual path, start,
  end, size, and PARTUUID, and rewrites runtime configuration from those observed
  values instead of assuming requested `sgdisk` boundaries.

## Phase 10 evidence

- Full Python suite: 91 passed; full Ruff and focused Linux-live mypy pass.
- `test_linux_network.py`: 5 passed.
- Evidence covers NetworkManager `connected` with failed DNS, independent TLS,
  HTTP, package mirror and Omarchy bootstrap failures, captive portal rejection,
  complete readiness, removable-media credential rejection, password absence
  from argv, and inherited-terminal execution for `nmcli --ask` and `nmtui`.
- No live-network integration test was run on this host; the gate is fully
  deterministic through injected readiness and command-runner fixtures.

## Phase 11 evidence

- `test_linux_state_machine.py`: 6 passed; focused UI Ruff and mypy pass.
- The required 24 stages execute in order through a backend protocol. Simulation
  ends only as `simulated`; real mode requires exact disk-GUID-bound typed
  confirmation and ends only as `applied` after every postcondition succeeds.
- Tests reject `plan_payload=None`, preserve an atomic redacted diagnostic on
  failure, and prove cancellation is honored only before partition changes.
- An 80x24 Textual Pilot test blocks runtime collection in a worker while the UI
  continues accepting navigation. The old snapshot probe no longer calls an
  empty install plan or treats it as success, and Limine is no longer a
  pre-install prerequisite.

## Phase 12 evidence

- Full local gate includes strict archinstall 4.4 config/credentials models,
  pre-mounted `/mnt/archinstall`, separate mode-0600 credentials, no internal
  plan fields, and current `--config/--creds/--silent/--mountpoint` CLI shape.
- Fake real-mode execution proves semantic validation and a GPT backup precede
  partition creation; actual geometry replaces requested geometry; LUKS2,
  Btrfs, subvolumes, root/ESP mounts, archinstall, `sd-encrypt` initramfs,
  reverse unmount, mapper close, and credential deletion occur in order.
- Exact pinned-package parsing and disposable VM installation are blocked on
  this host and remain explicitly open acceptance gates.

## Phase 13 evidence

- `test_target_finalization.py` proves deployment of the installed Python
  package, first-login and guardian wrappers, systemd units, machine-specific
  GUID/UUID state, protected state/log/diagnostic directories, and help command.
- Target validation fails closed on kernel/initramfs, Btrfs/ESP fstab entries,
  LUKS crypttab and initramfs hooks, user/wheel/sudo state, NetworkManager,
  Limine and preserved Windows EFI assets, Python compilation/import, wrapper
  permissions, unit references, and expected-state schema/machine identity.
- Chroot imports and `systemd-analyze verify` precede service activation. Base
  and target-finalization markers and the success marker are atomic; later
  Omarchy, boot-policy, and overall markers are not claimed early.

## Phase 14 evidence

- The root `multi-user.target` firstboot unit and `Restart=on-failure` path are
  removed. A profile hook can launch only after an interactive normal-user
  login; Python policy separately rejects root, non-TTY, WSL, live ISO, and a
  missing base-install marker.
- The upstream script is downloaded to user-owned state, SHA256-checked against
  root-owned release-pairing metadata, and identified to the user before exact
  typed confirmation. URL, retrieval time, upstream version/commit when exposed,
  release/build identity, hash, and every stage are written atomically.
- Partial state never retries automatically. `--retry` first displays that state
  and runs exactly once. The upstream process gets an inherited pseudo-terminal;
  util-linux `script --log-out` records output without enabling input/password
  logging. Omarchy completion is a distinct privileged atomic marker.
- Full local suite: 113 passed, 1 skipped. The skipped test is the actual Unix
  pseudo-terminal integration, which is platform-gated off on Windows and runs
  on a non-root Linux CI/VM host.

## Phase 15 evidence

- Pre-install preservation validates a real FAT ESP mount and the Windows loader
  without requiring Limine. Post-install finalization requires both loaders,
  measures firmware entries and Windows fallback, and blocks target activation
  on any critical mismatch.
- Installed guardian state has no built-in default. `findmnt` must prove the
  canonical path is a FAT mount whose filesystem UUID and PARTUUID exactly match
  machine-specific expected state before entries or repair are considered.
- Tests cover missing state, an unmounted ESP directory, no pre-install Limine,
  correct post-install state, missing Windows, ambiguous similar labels,
  boot-order-only drift, failed repair, and successful repair with remeasurement.
- A healthy/repaired guardian writes the boot-policy marker atomically. Overall
  completion is written only when the independent Omarchy marker also exists.
- Full local suite: 119 passed, 1 platform-gated Unix PTY test skipped.

## Phase 16 evidence

- `test_task_orchestrator_store.py`: 10 passed, covering an actually terminated
  lock-owning subprocess, stale owner metadata, six concurrent claimants with
  one winner, persisted lease expiry, malformed task records, corrupt state
  preservation, and replay after interruption between tracker/state writes.
- Lock metadata records host, PID, process-start identity, and timestamp while
  OS locking provides automatic crash release. JSON uses same-directory temp
  files, flush/fsync, and atomic replace.
- Server package launch uses a relative import and retains a tested direct-script
  compatibility fallback. Focused Ruff and mypy gates pass.
- Full suite: 129 passed, 1 Windows-side PTY skip. Full-tree mypy now reaches
  Phase 17 test typing and reports test-only fallback/negative-fixture issues;
  production orchestrator mypy is clean.

## Phase 17 evidence

- Removed `T01-config-001-json-generation.bats`, which asserted the obsolete
  shell generator's own invalid archinstall shape. The Bats inventory now points
  to strict Python contract tests and the upstream-consumer validation gate.
- `validate_archinstall_upstream.py` requires exactly archinstall 4.4 and feeds
  the generated config plus separate credentials to upstream `ArchConfig`, then
  checks the parsed pre-mounted layout and hashed sudo user.
- The suite covers Pydantic/templates, command ordering, atomic writes, Textual
  Pilot, Windows disk layouts, GPT bounds, wrong Ventoy disk, authenticated
  handoff, ISO dependencies/imports, first-login PTY behavior, mounted guardian,
  cleanup, and release pairing.
- Full local results: 129 passed, 2 skipped; Ruff passes; mypy reports no issues
  in 98 source files. Skips are the Unix PTY integration and upstream archinstall
  parser, both intentionally required on the Phase 18 Linux CI runners.

## Phase 18 evidence

- Added PR/push CI for pytest, Ruff, mypy, ShellCheck, remaining Bats, exact
  archived archinstall `4.4-1` parsing, Windows tests, PyInstaller packaging, and
  legacy payload scanning.
- The release workflow separately requires quality, shell, pinned contracts,
  Linux first-login PTY, a real ISO build, Windows EXE build/tests, and an
  OVMF disposable install/reboot job. Publication lists every gate in `needs`.
- Removed `.github/workflows/build-iso.yml`, the only conflicting legacy path
  that could directly publish a different setup.sh-only product.
- `test_workflow_gates.py` proves the legacy publisher is absent, all required
  jobs are publish dependencies, install/reboot flags are mandatory, and the CI
  matrix contains the required commands.
- This Windows host cannot execute the newly required Linux/OVMF jobs. Their
  workflow and fail-closed dependency graph are implemented; Phase 20 owns the
  harness and exact destructive VM evidence.
# Phase 19 legacy retirement evidence

- Removed executable historical entrypoints and stored inert `.txt` records
  under `legacy/unsupported/` with an explicit non-execution notice.
- Removed obsolete shell tests, duplicate installed-system bootstrap modules,
  duplicate workflows, and compatibility wrapper naming.
- ISO dry-run payload includes the complete target asset tree and uses only
  `/opt/omarchy-installer` plus the isolated Python virtual environment.
- `python rebuild/tools/check_no_legacy_production_refs.py`: passed.
- `python -m pytest rebuild/tests -q`: 128 passed, 2 skipped (Linux-only pinned
  upstream parser and pseudo-terminal integration).
- `python -m ruff check rebuild`: passed.
- `python -m mypy rebuild`: passed across 98 source files.
