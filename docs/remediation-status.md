# Python TUI remediation status

This is the durable traceability ledger for the 61 enumerated findings in
`OmarchyInstaller-full-repository-audit.md`. A finding remains unresolved until its
implementation, negative/failure tests, documentation, and acceptance evidence
are complete. The phase commit map below provides durable implementation
provenance; acceptance-blocked rows remain blocked regardless of code completion.

Baseline checkout: `08737764721d915921af4fa8a82015d3ea975fbd`

Execution branch: `fix/python-tui-full-remediation`

Environment note: Serena MCP is not exposed in this session. Existing local
Serena memories were read and found stale; they will be refreshed manually.
Docker/QEMU is not available on the Windows host itself. A disposable Linux
environment (WSL2, KVM-accelerated, nested virtualization enabled) was
provisioned specifically to run the VM/QEMU gates for real and was destroyed
after use; the same jobs also now run on GitHub-hosted `ubuntu-latest`
runners in CI (public-repo runners expose `/dev/kvm`), so no self-hosted
infrastructure is required going forward. See `docs/test-evidence.md`
"Phase 21" for exact commands and results.

| Finding ID | Severity | Title | Implementation phase | Affected files | Fix summary | Tests/evidence | Status | Commit | Notes |
|---|---|---|---:|---|---|---|---|---|---|
| CRIT-01 | Critical | Legacy archinstall config incompatible | 2, 12, 17, 20 | `setup.sh`, install engine | Replaced placeholder with strict archinstall 4.4 pre-mounted config/credentials contract | The real `archinstall-4.4-1-any.pkg.tar.zst` package (SHA256-verified against the official Arch archive) was installed into a real Arch chroot on a disposable Linux host and its own `ArchConfig.parse_arg()`/`ConfigurationOutput` parsed the generated config and credentials, accepting the pre-mounted layout and hashed sudo user | Resolved | | Exact-package validation executed for real; see `docs/test-evidence.md` Phase 21 |
| CRIT-02 | Critical | Partitioning precedes semantic validation | 3, 12 | install engine | Internal plan, archinstall config, and credentials validate before free-space recheck or any destructive command | invalid credentials execute zero runner commands; ordered backend tests | Resolved | | |
| CRIT-03 | Critical | Linux TUI never performs a real install | 4, 11, 21 | live TUI | Live Textual apply action re-identifies the machine, requires concealed credentials and disk-bound confirmation, then calls the production install/finalization engine in a worker | The real production TUI (not a mock/dry-run harness), driven over its actual serial console by `qemu_ovmf_driver.py`, was used to enter the handoff key, pass network/preflight checks, and trigger the real apply-install action against a disposable GPT/LUKS2/Btrfs disk in a KVM-accelerated QEMU/OVMF VM; `install.log` and `vm-evidence.json` record `installation_completed: true` for a genuine, non-dry-run archinstall 4.4-1 run | Verification blocked | | Real install through the real TUI is proven; the post-install reboot/login half of this finding is not yet closed (see HIGH-32 notes) |
| CRIT-04 | Critical | Internal plan passed to archinstall | 2, 12 | install engine | Separate strict pre-mounted config and mode-0600 credentials; internal fields excluded | config negative assertions and exact CLI test | Resolved | | |
| CRIT-05 | Critical | Incomplete target layout preparation | 9, 11, 12, 13, 21 | install engine | LUKS2, Btrfs, configured subvolumes, root tree, verified ESP, initramfs, archinstall, and target finalization implemented | A real disposable UEFI VM was fully installed end-to-end: real GPT+LUKS2+Btrfs (`@`/`@home`), real archinstall 4.4-1 pre-mounted run, real manual Limine install, real `arch-chroot` target finalization (venv provisioning, `pip install --require-hashes`, wrapper deployment, marker activation), and a post-install remount that confirmed `/etc/fstab`, `/etc/crypttab.initramfs`, and the ESP/Limine files are present and correct | Verification blocked | | Target layout is genuinely built and passes remount inspection; full closure needs the post-reboot login proof, which remains blocked (see HIGH-32 notes) |
| CRIT-06 | Critical | ISO omits Python dependency installation | 8, 21 | ISO pipeline | Hash-locked dependency set installed into `/opt/omarchy-venv` during rootfs assembly | `build-custom-iso.sh` was run for real (no dry-run) on a disposable Linux host, producing a genuine bootable `.iso`, an `iso-build-manifest.json`, and a matching `.sha256` sidecar; the manifest was independently re-hashed and matched | Resolved | | Real, non-dry-run ISO build executed and verified |
| CRIT-07 | Critical | Live package import path is broken | 8, 21 | startup assets | Canonical cwd-independent `python -m installer.main` entrypoint with venv `.pth` package root | The real ISO was booted offline (no networking) under QEMU/OVMF; the live console reached `login:`, and `cd /tmp && python -m installer.main` style entrypoint checks and a dependency probe (`archinstall`, `cryptsetup`, `mkfs.btrfs`, `efibootmgr`, etc.) all passed from an arbitrary cwd | Resolved | | Real offline UEFI boot of the real ISO proved the entrypoint; see `offline_boot_test.py` |
| CRIT-08 | Critical | Target markers and assets not deployed | 13 | finalization | Deploys runtime, wrappers, units, machine state, protected directories, help, and atomic stage/success markers | fail-closed target fixture proves activation and markers occur only after all validations | Resolved | | |
| CRIT-09 | Critical | Firstboot runs interactive install as root | 14, 21 | first-login | Removed the root multi-user service; an interactive profile hook launches a UID-checked normal-user Python flow | user/TTY/WSL/live/base-marker policy tests and target activation test; additionally re-run for real as a genuine non-root user (`omarchytest`, uid 1001) under a real `script`-allocated PTY on a disposable Linux host — all 10 tests passed, including the platform-gated pseudo-terminal test previously only skipped on Windows | Resolved | | Real non-root PTY execution confirmed, not just a CI-only claim; transcript at `rebuild/dist/vm-gate-evidence/first-login-pty-transcript.log` |
| CRIT-10 | Critical | GPT free-space includes reserved sectors | 5, 9 | disk geometry | Linux consumes authoritative `sgdisk` usable bounds and rechecks the planned extent immediately before creation | end-of-disk metadata, stale extent, and alignment-change tests | Resolved | | |
| CRIT-11 | Critical | Plan template fails production contract | 2 | shared models/templates | Replaced with complete schema 1.0.0 artifact accepted by `PlanContract` | `test_shipped_plan_template_passes_production_validator` | Resolved | | |
| CRIT-12 | Critical | Ventoy write precedes USB validation | 6 | Windows handoff | Added two pre-write USB/protected-role/identity reads and exact typed confirmation | internal-disk, wrong-confirmation, identity-race, and command-order tests | Resolved | | |
| CRIT-13 | Critical | ISO build can disable signature checks | 8 | ISO build | Removed unsigned fallback; package install uses Arch keyring and dated signed archive | static regression rejects `SigLevel = Never`; build fails on pacman error | Resolved | | |
| HIGH-01 | High | TUIs block their event loops | 3, 4, 11 | Textual apps | Windows operations and Linux runtime refresh execute in Textual workers | blocked-worker responsiveness Pilot tests at 80x24 | Resolved | | |
| HIGH-02 | High | Pre-install flow requires Limine | 11, 15 | boot policy | Dedicated pre-install preservation requires a verified ESP and Windows loader only; Limine is exclusively post-install | no-Limine preinstall test plus post-install target/guardian tests | Resolved | | |
| HIGH-03 | High | Handoff discovery does not mount USB | 9 | discovery | Recursively enumerates removable VENTOY partitions, requires one match, mounts read-only under `/run/omarchy`, and always unmounts | nested topology and controlled mount/unmount tests | Resolved | | |
| HIGH-04 | High | Handoff lacks authenticated integrity | 6, 9 | handoff/discovery | Linux verifies one-time HMAC, plan/ISO hashes, provenance, and disk/partition identities before use | valid, tampered, missing-key, and stale tests | Resolved | | |
| HIGH-05 | High | Linux ignores GPT disk GUID | 2, 9 | identity | Exact planned GPT disk GUID/PTUUID plus size and sector size are mandatory; ambiguous matches fail | wrong GUID, absent serial, and duplicate exact identity tests | Resolved | | |
| HIGH-06 | High | PARTUUID and filesystem UUID conflated | 2, 9 | models/identity | PARTUUID matches GPT partition GUID only; filesystem UUID/type and geometry/size are independent checks | wrong filesystem UUID and exact geometry tests | Resolved | | |
| HIGH-07 | High | Shrink planning merges unrelated extents | 5 | Windows partitioning | Counts only aligned extent immediately after C:; exact missing bytes plus 16 MiB margin | adjacent/non-adjacent/recovery fixtures | Resolved | | |
| HIGH-08 | High | Legacy path over-shrinks Windows | 5, 19 | legacy archive | Executable legacy path removed; Python shrink policy uses queried minimum/maximum/contiguous limits | retirement checker plus shrink-policy tests | Resolved | | Archived text is not runnable |
| HIGH-09 | High | Shrink lacks durable recovery journal | 3, 5 | transactions/partitioning | Requires verified identity-bound backup and atomic before/after journal; reports applied-validation failure distinctly | resize success/failure/identity tests | Resolved | | No automatic rollback is claimed |
| HIGH-10 | High | EFI fallback accepts arbitrary FAT32 | 5 | Windows identity | Removed FAT32 fallback; GPT ESP type required | FAT32-decoy and missing-ESP tests | Resolved | | |
| HIGH-11 | High | EFI backup is not verifiable | 5 | Windows backup | Added per-file SHA256, deterministic aggregate, and read-back verification | `test_backup_verifies_selected_esp_and_per_file_manifest` | Resolved | | |
| HIGH-12 | High | Backup may mount wrong ESP | 5 | Windows backup | Mounts exact disk/partition selected by system-partition probe and records identities | selected-ESP fixture and source manifest assertions | Resolved | | |
| HIGH-13 | High | USB may contain plaintext Wi-Fi secret | 6, 10 | handoff/network | Removed plaintext Wi-Fi handoff; Linux rejects such profiles and credentials are interactive-only | Windows staging and Linux rejection tests | Resolved | | |
| HIGH-14 | High | Wi-Fi password exposed in argv | 10 | network | Rejects programmatic plaintext passwords; Wi-Fi uses inherited `nmcli --ask` with no secret argument | argv recording test proves secret absence | Resolved | | |
| HIGH-15 | High | nmtui lacks inherited terminal | 10 | network | `nmtui` and interactive nmcli use a non-capturing inherited-terminal runner | captured-vs-interactive runner test | Resolved | | |
| HIGH-16 | High | Link state mistaken for internet readiness | 10 | network | Independent link, IP, DNS, TLS, HTTP, mirror, bootstrap, and captive-portal states; any failure blocks | connected-with-failed-DNS plus every layer/captive tests | Resolved | | |
| HIGH-17 | High | Partial firstboot automatically retries | 14 | first-login | User-owned atomic state blocks every partial attempt until prior state is displayed and `--retry` is explicit | no-retry and explicit-single-retry tests | Resolved | | No Restart policy or root service remains |
| HIGH-18 | High | EFI mount contracts conflict | 12, 13, 15 | install/guardian | Engine, target finalizer, expected state, and guardian use the plan's sole `/boot` ESP; guardian verifies the actual findmnt target | mount-path, FAT, filesystem UUID, and PARTUUID tests | Resolved | | Reboot gate remains environmental |
| HIGH-19 | High | Failure evidence is deleted | 3, 11, 12 | diagnostics | Failed state-machine runs atomically preserve redacted stage diagnostics; failed install staging is retained | secret redaction and diagnostic persistence test | Resolved | | |
| HIGH-20 | High | Conflicting release products | 1, 7, 18, 19 | workflows | Only one CI workflow and one gated Python release workflow remain; archived programs are inert text | workflow and retired-path regressions | Resolved | | |
| HIGH-21 | High | Publisher can pair unrelated artifacts | 7, 18 | release tooling | Unique exact-paired artifacts are revalidated after all build and VM needs and before attested publication | provenance negative tests plus release graph regression | Resolved | | |
| HIGH-22 | High | Provenance failures can fail open | 7, 18 | release/Windows | Missing, ambiguous, dry-run, mismatched, or tampered provenance hard-fails and publication has no bypass job | negative contract and workflow graph tests | Resolved | | |
| HIGH-23 | High | Interrupted ISO builds leak mounts | 3, 8, 21 | ISO build | EXIT/INT/TERM cleanup tracks mounts and unmounts them in reverse order before worktree removal | Interrupting a real `build-custom-iso.sh` run on a real Linux host surfaced a genuine leak (`gpg-agent`, spawned by `pacman-key`, held `/dev` busy and caused `umount: not mounted`/busy failures); fixed by adding `gpgconf --homedir /etc/pacman.d/gnupg --kill all` to the cleanup path, then re-ran the interruption and confirmed a clean unmount with no leaked mounts | Resolved | | Real bug found and fixed on a real Linux host, not merely simulated |
| HIGH-24 | High | Successful install leaves mounts/LUKS open | 3, 12 | install transactions | Tracks every mount, unmounts reverse-order, and closes mapper on success/failure | fake real-mode cleanup order test | Resolved | | |
| HIGH-25 | High | Runtime dependency manifest incomplete | 8, 13 | ISO/finalization | Live dependencies are verified and the target gets a canonical Python runtime package with chroot import validation | ISO static tests and target import/compile contract tests | Resolved | | Exact VM execution remains an acceptance gate |
| HIGH-26 | High | Startup metadata disagrees with runtime | 8, 19 | ISO assets | Metadata, live hook, launcher, venv import root, and packaged asset tree use one canonical Python runtime | payload regression and retired-path checker pass | Resolved | | ISO boot remains a separate acceptance gate |
| HIGH-27 | High | Launcher silently falls back to PowerShell | 1, 4, 19 | Windows launcher, Windows TUI, EXE builder | Removed fallback/bypass and executable legacy payload; Python startup now fails visibly | launcher/flow tests and retired-path checker | Resolved | | |
| HIGH-28 | High | Windows TUI bypasses and fake completion | 4, 11 | Windows TUI | Windows stage gates distinguish simulated/applied; Linux state machine rejects empty plans and distinguishes simulated/applied | Windows Pilot plus Linux state tests | Resolved | | |
| HIGH-29 | High | Guardian defaults when expected state absent | 13, 15 | guardian | Removed built-in fallback; machine-specific state and exact mounted ESP UUID/PARTUUID are mandatory | missing state, unmounted directory, UUID identity, ambiguity, repair failure, and remeasurement tests | Resolved | | |
| HIGH-30 | High | Tracker lock survives crashed process | 16 | task orchestrator | Replaced exclusive lock-file existence with OS locking, in-process serialization, and owner/start metadata | killed subprocess, stale metadata, and concurrent claimant tests | Resolved | | |
| HIGH-31 | High | Tracker/state writes are non-atomic | 3, 16 | task orchestrator/state | Atomic fsync/replace writes, locked lease purge, and replayable tracker/state transaction journal | interruption recovery, corruption, lease expiry, malformed record, and concurrency tests | Resolved | | |
| HIGH-32 | High | No install or boot CI test | 17, 18, 21 | CI/vmtest | CI now defines quality, shell, pinned contracts, Windows packaging, ISO, PTY, disposable install, and reboot jobs; release requires all | static graph regression and local suites pass; the `offline-iso-boot`, `vm-install-reboot`, and `recovery-rehearsal` jobs were switched from an unregistered `self-hosted` runner label (which would only ever have hung waiting for a runner that does not exist) to `ubuntu-latest`, since GitHub-hosted Linux runners on public repos expose `/dev/kvm` and need no additional infrastructure; the full disposable install (CRIT-03/CRIT-05) and recovery rehearsal (see below) were proven for real on an equivalent local KVM/QEMU/OVMF environment before this change | Verification blocked | | The workflow now targets a runner that can actually execute it; the install itself is proven, but the reboot/login half of `vm-install-reboot` is still blocked by the LUKS-unlock automation gap below, and a green CI run has not yet been observed at the time of writing |
| HIGH-33 | High | Omarchy bootstrap mutable and unlogged | 14 | first-login | Downloads HTTPS source to a file, verifies release-paired SHA256, records retrieval/version/commit/provenance, displays identity, and uses an output-only PTY transcript | hash mismatch, metadata, transcript, confirmation, and completion-marker tests | Resolved | | Upstream execution remains an external acceptance gate |
| MED-01 | Medium | Safety-critical plan fields untyped | 2 | shared models | Added strict nested user, locale, free-space, encryption, filesystem, boot, Omarchy, and provenance models | `test_shipped_plan_template_passes_production_validator`; strict-extra test | Resolved | | |
| MED-02 | Medium | Sector range size not cross-validated | 2 | shared models | Added inclusive range arithmetic and cross-plan logical-sector validation | sector mismatch and cross-sector tests | Resolved | | |
| MED-03 | Medium | MBR permitted by GPT-only design | 2 | shared models | `DiskIdentity` now accepts GPT only | `test_gpt_is_the_only_supported_partition_style` | Resolved | | |
| MED-04 | Medium | Version comparison mishandles prereleases | 2 | versioning | Replaced parser with `packaging.version.Version` | `test_version_comparison_uses_standard_prerelease_ordering` | Resolved | | |
| MED-05 | Medium | Windows preflight parsing locale-dependent | 4, 5 | Windows checks | Replaced localized `reagentc` text parsing with typed PowerShell inspection of `ReAgent.xml`; other probes emit invariant typed values | positive, negative, and unknown preflight probe tests | Resolved | | |
| MED-06 | Medium | Disk number used when serial absent | 2, 5, 9 | identity | Cross-boot identity uses exact GPT disk GUID, size, sector size, model, and optional serial; runtime disk number is scoped to a freshly revalidated Windows operation only | missing-serial, wrong-GUID, ambiguous, and identity-change tests | Resolved | | |
| MED-07 | Medium | Copied ISO hash not verified | 6 | handoff | Source/destination SHA256 compared; corrupt copy removed | ISO copy and corruption tests | Resolved | | |
| MED-08 | Medium | FAT32 file-size limit unchecked | 6 | handoff | Rejects any FAT32 payload above 4 GiB minus one byte | sparse over-limit test | Resolved | | |
| MED-09 | Medium | Arbitrary 72-hour plan freshness | 6, 9 | discovery/main | Removed implicit time expiry; immutable artifact/release/commit pairing is mandatory, with age limits only when explicitly configured | stale-policy and default-disabled contract tests | Resolved | | |
| MED-10 | Medium | EXE version derived from commit digits | 7 | EXE build | Requires explicit semantic X.Y.Z and emits X.Y.Z.0 | strict VERSIONINFO test | Resolved | | |
| MED-11 | Medium | Prompt responses logged | 3, 10 | command/logging | Prompt-bearing commands inherit terminal I/O and are never captured; structured diagnostics contain booleans only | secret not in argv/captured command tests | Resolved | | |
| MED-12 | Medium | Release template incompatible | 2, 7 | models/templates | Template and publisher both validate with `ReleaseManifestContract` schema 1.0.0 | template and valid release-pair tests | Resolved | | |
| MED-13 | Medium | README/status materially stale | 1, 19 | documentation | Root/rebuild READMEs, install/recovery/contributor/architecture/status/release/issue/ownership docs now describe one Python journey and honest blockers | documentation review and retired-path scan | Resolved | | |
| MED-14 | Medium | Tests enforce obsolete archinstall shape | 12, 17, 19 | Bats/contracts | Removed obsolete shell-config Bats; strict models and a Linux gate feed generated files to the pinned upstream 4.4 parser | local strict tests plus upstream-consumer validator | Resolved | | Upstream parser test skips when package is unavailable |
| MED-15 | Medium | Tests mock away production failures | 17, 18, 21 | integration/VM tests | CI requires upstream parser, real PTY, packaged EXE, built ISO, OVMF boot, disposable install, and reboot evidence | Every one of these was independently executed for real (not mocked, not dry-run) on a disposable Linux environment: real archinstall 4.4-1 upstream parsing, a real non-root PTY first-login run, a real ISO build, a real OVMF offline boot, a real disposable GPT/LUKS2/Btrfs install through the real TUI, and a real backup/damage/restore recovery rehearsal (`recovery_passed: true`) | Verification blocked | | Every sub-claim except post-install reboot/login has real, non-mocked evidence; kept blocked only because the CI graph itself (not just local-equivalent runs) has not yet completed green and the reboot proof is outstanding |

## Baseline evidence

- Branch created from audited commit `08737764721d915921af4fa8a82015d3ea975fbd`.
- Working tree was clean before remediation.
- Host Python: 3.14.2.
- Initial Python tool baseline: pytest, Ruff, and mypy not installed.
- Docker/Compose baseline: unavailable on host.
- WSL baseline: WSL 2 available.
- Destructive disk, EFI, Ventoy, BitLocker, and boot-order commands were not run.

## Reconciliation totals

- Total audited findings: **61**
- Resolved with repository evidence: **57**
- Implementation complete but verification blocked on external acceptance: **4**
- Unclassified or silently waived: **0**

Blocked IDs: `CRIT-03`, `CRIT-05`, `HIGH-32`, and `MED-15`. All four share
one root cause: a genuine, real (non-mocked) disposable UEFI install
completed successfully through the real production TUI, but the
post-install reboot's LUKS2 unlock could not be driven through the serial
console automation in this session — see `docs/test-evidence.md` Phase 21
and `docs/release-readiness.md` for the exact evidence and the remaining
gap.

## Phase commit map

Phases 0–19 are represented by commits `1738cfa`, `a7c7851`, `0b5f0c2`,
`faa1365`, `ec9f695`, `f53adc0`, `85bc2fb`, `8946dbb`, `e20ac8e`,
`4d04b06`, `448b887`, `e283e99`, `e93d389`, `a75917d`, `96531cb`,
`2ecb423`, `c117a6c`, `f2220b4`, and `d56b560`. Phase 20 evidence is
recorded by the final verification commit on that branch state. Phase 21
(this update) built and destroyed a disposable KVM-accelerated Linux VM
driver harness, executed every previously-blocked local gate for real, and
switched the CI VM jobs onto GitHub-hosted runners so they can actually
execute; see `docs/test-evidence.md` for exact commands and results.
