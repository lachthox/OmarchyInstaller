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

## Phase 20 final verification evidence

- `python -m pytest rebuild/tests -q -rs`: **138 passed, 2 skipped**. The skips
  are explicit: the installed `archinstall` package is absent on this Windows
  host, and the first-login PTY test requires a non-root Unix host.
- `python -m ruff check rebuild`: passed.
- `python -m mypy --no-incremental rebuild`: passed across 101 source files.
- `python rebuild/tools/check_no_legacy_production_refs.py`: passed.
- `shellcheck -s bash <all rebuild/assets/scripts/*.sh plus build-custom-iso.sh>`:
  passed after explicitly documenting intentional inner-chroot expansion.
- `python -m compileall -q rebuild`: passed.
- Dry-run ISO and EXE packaging produced manifests, checksums, and placeholder
  artifacts for the same local tag. `publish_release` rejected them with
  `ISO manifest is dry-run or missing an explicit false dry_run state`, proving
  that simulated artifacts cannot be promoted.
- VM prerequisite probe: `qemu-system-x86_64`, `qemu-img`, Docker, and Bats are
  unavailable; WSL is installed but has no usable Linux distribution. There is
  no non-dry-run ISO in `rebuild/dist/vm-input`.
- `python -m rebuild.tools.vm_install_test --iso-glob
  'rebuild/dist/vm-input/*-omarchy-auto.iso' --work-dir
  rebuild/dist/vm-gate --require-install --require-reboot`: **blocked**, exactly
  one ISO required and zero found. No VM pass is claimed.
- Serena MCP was not exposed in this session, so its final memory update could
  not be performed. Repository ledgers and reports are the durable handoff.
- Independent ID reconciliation extracted 61 unique `CRIT`/`HIGH`/`MED` IDs
  from the audit and 61 from the ledger; `Compare-Object` returned no mismatch.
  Ledger totals were 53 resolved and 8 verification-blocked at that point.

## Phase 21 evidence — real disposable VM execution

This phase closes the environment gap the previous phase left open: it
provisions a genuine, disposable, KVM-accelerated Linux environment and runs
every previously-blocked gate against real artifacts through the real
production code paths. No mocks, dry-runs, or fake command runners are used
anywhere in this section.

### Environment

A disposable WSL2 distribution (`omarchy-vm-test`) was created by direct
rootfs import specifically for this testing, with `.wslconfig` raised to
12 GB RAM / 6 vCPU / 4 GB swap and `nestedVirtualization=true`. It had a real
non-root Linux userland, `/dev/kvm` access, and no prior state. It was used
only for this remediation work and is torn down afterward; it is not part of
the shipped product or a claimed permanent CI runner.

### Real ISO build (CRIT-06)

`build-custom-iso.sh` was executed for real — not `--dry-run` — on the
disposable host. It produced a bootable ISO plus `iso-build-manifest.json`
and a `.sha256` sidecar. The manifest's recorded SHA256 was independently
recomputed with `sha256sum` and matched exactly. Interrupting this same real
build mid-run (HIGH-23) surfaced a genuine leaked mount caused by
`gpg-agent` (spawned by `pacman-key`) holding `/dev` busy; this was fixed by
adding an explicit `gpgconf --kill all` to the cleanup path, and a repeat
interruption then cleaned up completely with no leaked mounts.

### Real offline UEFI boot (CRIT-07)

The real ISO from the previous step was booted with QEMU/OVMF
(`-machine q35,accel=kvm`, `-cpu host`), no network attached. The live
console reached `login:`, logged in as `root`, and confirmed the entrypoint
runs correctly from an arbitrary `cwd` and that `archinstall`, `cryptsetup`,
`mkfs.btrfs`, `efibootmgr`, and the rest of the required binary set are all
present on the live image.

### Real archinstall 4.4-1 upstream parser (CRIT-01)

A real Arch Linux bootstrap chroot was built (the official bootstrap
tarball, SHA256-verified). Inside it, `archinstall-4.4-1-any.pkg.tar.zst`
was downloaded from the official Arch archive, SHA256-verified, and
installed via `pacman -U`, confirmed as exactly `archinstall 4.4-1`. The
generated pre-mounted config and separate credentials file were fed to the
real, installed package's own `ArchConfig`/`ConfigurationOutput` parser
(not a hand-rolled shape check), which accepted them.

### Real disposable dual-boot disk fixture

A raw disk image was built with a real GPT: an ESP (vfat), a synthetic
"Windows" NTFS partition seeded with a placeholder `bootmgfw.efi` (its
SHA256 recorded before any install activity), and free extent for Linux —
matching `plan.template.json`'s documented disk geometry exactly, including
querying the real `mkfs.vfat`-assigned filesystem UUID via `blkid` rather
than a synthetic placeholder.

### Real VM automation driver (CRIT-03 / `OMARCHY_ISOLATED_VM_DRIVER`)

`rebuild/tools/vm_drivers/qemu_ovmf_driver.py` is a real implementation of
the isolated-runner driver contract, not a stub. Against the disposable disk
above, it:

1. Booted the real ISO under QEMU/OVMF and logged in as `root` over a real
   serial console (parsed with a `pyte` VT100 terminal emulator, since the
   Textual TUI redraws via cursor-positioned partial updates that a naive
   ANSI-strip cannot follow).
2. Registered a synthetic "Windows Boot Manager" NVRAM entry via
   `efibootmgr`, mirroring what real Windows setup does via `bcdboot` (this
   cannot be pre-baked into a raw disk image — NVRAM only exists once real
   firmware runs).
3. Drove the **actual production Python TUI** (not a mock or fake runner):
   entered the 64-hex handoff key, waited for real `Dependencies: PASS` /
   `Handoff: PASS` / `Machine identity: PASS` preflight results, waited for
   real network-readiness output, then entered a real LUKS passphrase and
   user password and pressed the real apply-install action.
4. The **real production install engine** ran to completion: real
   `sgdisk`-backed partitioning, real `cryptsetup luksFormat`/`luksOpen`,
   real `mkfs.btrfs` with `@`/`@home` subvolumes, a real (non-dry-run,
   PTY-attached) `archinstall` invocation against the pre-mounted layout,
   real manual Limine installation, and real `arch-chroot` target
   finalization (provisioning `/opt/omarchy-venv`, `pip install
   --require-hashes`, wrapper/unit deployment, atomic marker activation).
   `install.log` and the run's `vm-evidence.json` record
   `installation_completed: true`.
5. After completion, the target was remounted (LUKS-unlocked, root +
   ESP) purely for inspection: `/etc/fstab`, `/etc/crypttab.initramfs`, the
   ESP's Limine files, and the *original* synthetic `bootmgfw.efi` were all
   present, and the Windows EFI loader's SHA256 was **unchanged** from the
   pre-install hash — `windows_efi_preserved: true`. This is genuine,
   hash-verified Windows EFI preservation evidence (CRIT-05 / HIGH-18),
   not a claim.

### Real backup/restore recovery rehearsal (Task 11 / `docs/recovery.md`)

`rebuild/tools/vm_drivers/recovery_rehearsal.py` built a fresh disposable
disk, took a real `sgdisk --backup` GPT snapshot and a real per-file SHA256
manifest of the ESP tree, **deliberately destroyed** the GPT
(`sgdisk --zap-all`) and corrupted the Windows EFI loader in place, then
restored from the backups and re-hashed. Result:
`gpt_restored_clean: true`, `esp_restore_matches_backup: true`,
`recovery_passed: true`. Output saved at
`rebuild/dist/vm-gate-evidence/recovery-test.json`.

### Real non-root first-login PTY run (Task 8 / CRIT-09)

A genuine non-root user (`omarchytest`, uid 1001) was created on the
disposable host. `rebuild/tests/test_first_login.py` was run under a real
`script --quiet --return`-allocated PTY (not a synthetic/faked terminal).
All 10 tests passed, including
`test_pseudo_terminal_preserves_installer_output`, which is
platform-gated off on Windows and was previously only a CI-only claim.
Transcript saved at
`rebuild/dist/vm-gate-evidence/first-login-pty-transcript.log`.

### What is genuinely NOT resolved: post-reboot LUKS unlock

The one sub-claim that could not be closed: booting the *installed* disk
(ISO detached) and unlocking its LUKS2 volume through the automation
console. Six independent fix attempts were made — varying the line-ending
sent to the passphrase prompt (`\r`, `\n`, `\r\n`), slowing down every send
during the install phase, switching QEMU's disk cache mode from
`cache=unsafe` to `cache=writeback` (so guest flush/FUA requests are
actually honored across separate QEMU process invocations of the same
image), and building a 12-attempt retry loop that waits only for `login:`
rather than misfiring on the ambient "passphrase for" text that persists in
scrollback. Every attempt produced the same symptom: the console echoes the
correct number of dots for the passphrase, then re-displays the identical
prompt, consistent with `systemd-ask-password` in the initramfs not
receiving the input as expected input over this particular
serial-console/PTY plumbing. This is an automation/tooling gap in driving
`systemd-ask-password` over a raw serial console, not evidence of an
incorrect installed system — the pre-reboot remount inspection above
independently confirms `/etc/crypttab.initramfs`, `mkinitcpio`'s
`sd-encrypt` hook, and the LUKS header are all present and correctly
configured. **No reboot/login pass is claimed.** CRIT-03, CRIT-05,
HIGH-32, and MED-15 remain `Verification blocked` for exactly this reason.

### CI graph changes

The `offline-iso-boot`, `vm-install-reboot`, and `recovery-rehearsal` jobs
in `.github/workflows/rebuild-release.yml` previously targeted
`runs-on: [self-hosted, linux, x64, omarchy-vm]` — a runner label that was
never registered against this repository, so triggering the workflow would
only ever have hung waiting for a runner that does not exist, never
producing evidence. They were switched to `runs-on: ubuntu-latest`:
GitHub-hosted Linux runners on public repositories expose `/dev/kvm`, which
is the only real hardware requirement these jobs have, and the repository
is public. Package installation (`qemu-system-x86`, `qemu-utils`, `ovmf`,
`gdisk`, `dosfstools`, `ntfs-3g`) was added to each job since a hosted
runner is not pre-provisioned the way a dedicated self-hosted box would be.
This has not yet been observed running green in GitHub's own infrastructure
at the time of writing — see `docs/release-readiness.md` for exactly what
that leaves open.
