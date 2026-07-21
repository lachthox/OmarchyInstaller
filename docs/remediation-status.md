# Python TUI remediation status

This is the durable traceability ledger for the 61 enumerated findings in
`OmarchyInstaller-full-repository-audit.md`. A finding remains open until its
implementation, negative/failure tests, documentation, and acceptance evidence
are complete. `Commit` is intentionally blank until a reviewed phase commit is
created.

Baseline checkout: `08737764721d915921af4fa8a82015d3ea975fbd`

Execution branch: `fix/python-tui-full-remediation`

Environment note: Serena MCP is not exposed in this session. Existing local
Serena memories were read and found stale; they will be refreshed manually.
Docker/QEMU is not currently available on the Windows host, so VM gates cannot
be marked complete until run in a capable environment.

| Finding ID | Severity | Title | Implementation phase | Affected files | Fix summary | Tests/evidence | Status | Commit | Notes |
|---|---|---|---:|---|---|---|---|---|---|
| CRIT-01 | Critical | Legacy archinstall config incompatible | 2, 12, 17, 19 | `setup.sh`, install engine | Pending | Pending | Open | | |
| CRIT-02 | Critical | Partitioning precedes semantic validation | 3, 12 | install engine | Pending | Pending | Open | | |
| CRIT-03 | Critical | Linux TUI never performs a real install | 4, 11 | live TUI | Pending | Pending | Open | | |
| CRIT-04 | Critical | Internal plan passed to archinstall | 2, 12 | install engine | Pending | Pending | Open | | |
| CRIT-05 | Critical | Incomplete target layout preparation | 9, 11, 12, 13 | install engine | Pending | Pending | Open | | |
| CRIT-06 | Critical | ISO omits Python dependency installation | 8 | ISO pipeline | Pending | Pending | Open | | |
| CRIT-07 | Critical | Live package import path is broken | 8 | startup assets | Pending | Pending | Open | | |
| CRIT-08 | Critical | Target markers and assets not deployed | 13 | finalization | Pending | Pending | Open | | |
| CRIT-09 | Critical | Firstboot runs interactive install as root | 14 | first-login | Pending | Pending | Open | | |
| CRIT-10 | Critical | GPT free-space includes reserved sectors | 5, 9 | disk geometry | Pending | Pending | Open | | |
| CRIT-11 | Critical | Plan template fails production contract | 2 | shared models/templates | Replaced with complete schema 1.0.0 artifact accepted by `PlanContract` | `test_shipped_plan_template_passes_production_validator` | Resolved | | |
| CRIT-12 | Critical | Ventoy write precedes USB validation | 6 | Windows handoff | Added two pre-write USB/protected-role/identity reads and exact typed confirmation | internal-disk, wrong-confirmation, identity-race, and command-order tests | Resolved | | |
| CRIT-13 | Critical | ISO build can disable signature checks | 8 | ISO build | Pending | Pending | Open | | |
| HIGH-01 | High | TUIs block their event loops | 3, 4, 11 | Textual apps | Pending | Pending | Open | | |
| HIGH-02 | High | Pre-install flow requires Limine | 11, 15 | boot policy | Pending | Pending | Open | | |
| HIGH-03 | High | Handoff discovery does not mount USB | 9 | discovery | Pending | Pending | Open | | |
| HIGH-04 | High | Handoff lacks authenticated integrity | 6, 9 | handoff/discovery | Pending | Pending | Open | | |
| HIGH-05 | High | Linux ignores GPT disk GUID | 2, 9 | identity | Pending | Pending | Open | | |
| HIGH-06 | High | PARTUUID and filesystem UUID conflated | 2, 9 | models/identity | Pending | Pending | Open | | |
| HIGH-07 | High | Shrink planning merges unrelated extents | 5 | Windows partitioning | Counts only aligned extent immediately after C:; exact missing bytes plus 16 MiB margin | adjacent/non-adjacent/recovery fixtures | Resolved | | |
| HIGH-08 | High | Legacy path over-shrinks Windows | 5, 19 | legacy Windows | Pending | Pending | Open | | |
| HIGH-09 | High | Shrink lacks durable recovery journal | 3, 5 | transactions/partitioning | Requires verified identity-bound backup and atomic before/after journal; reports applied-validation failure distinctly | resize success/failure/identity tests | Resolved | | No automatic rollback is claimed |
| HIGH-10 | High | EFI fallback accepts arbitrary FAT32 | 5 | Windows identity | Removed FAT32 fallback; GPT ESP type required | FAT32-decoy and missing-ESP tests | Resolved | | |
| HIGH-11 | High | EFI backup is not verifiable | 5 | Windows backup | Added per-file SHA256, deterministic aggregate, and read-back verification | `test_backup_verifies_selected_esp_and_per_file_manifest` | Resolved | | |
| HIGH-12 | High | Backup may mount wrong ESP | 5 | Windows backup | Mounts exact disk/partition selected by system-partition probe and records identities | selected-ESP fixture and source manifest assertions | Resolved | | |
| HIGH-13 | High | USB may contain plaintext Wi-Fi secret | 6, 10 | handoff/network | Removed plaintext Wi-Fi handoff; credentials are interactive-only | `test_plaintext_wifi_handoff_is_disabled` | Resolved | | Live network secret handling continues in Phase 10 |
| HIGH-14 | High | Wi-Fi password exposed in argv | 10 | network | Pending | Pending | Open | | |
| HIGH-15 | High | nmtui lacks inherited terminal | 10 | network | Pending | Pending | Open | | |
| HIGH-16 | High | Link state mistaken for internet readiness | 10 | network | Pending | Pending | Open | | |
| HIGH-17 | High | Partial firstboot automatically retries | 14 | first-login service | Pending | Pending | Open | | |
| HIGH-18 | High | EFI mount contracts conflict | 12, 13, 15 | install/guardian | Pending | Pending | Open | | |
| HIGH-19 | High | Failure evidence is deleted | 3, 11, 12 | diagnostics | Pending | Pending | Open | | |
| HIGH-20 | High | Conflicting release products | 1, 7, 18, 19 | workflows | Pending | Pending | Open | | |
| HIGH-21 | High | Publisher can pair unrelated artifacts | 7, 18 | release tooling | Requires unique artifacts and matching commit/tag/version/run/ref/schema/name/hash/non-dry-run manifests | provenance pairing negative tests | Resolved | | VM release gate remains Phase 18 |
| HIGH-22 | High | Provenance failures can fail open | 7, 18 | release/Windows | Missing, ambiguous, dry-run, mismatched, or tampered provenance now hard-fails | provenance negative tests | Resolved | | |
| HIGH-23 | High | Interrupted ISO builds leak mounts | 3, 8 | ISO build | Pending | Pending | Open | | |
| HIGH-24 | High | Successful install leaves mounts/LUKS open | 3, 12 | install transactions | Pending | Pending | Open | | |
| HIGH-25 | High | Runtime dependency manifest incomplete | 8, 13 | ISO/finalization | Pending | Pending | Open | | |
| HIGH-26 | High | Startup metadata disagrees with runtime | 8, 19 | ISO assets | Pending | Pending | Open | | |
| HIGH-27 | High | Launcher silently falls back to PowerShell | 1, 4, 19 | Windows launcher, Windows TUI, EXE builder | Removed fallback/bypass and legacy payload; Python startup now fails visibly | `pytest -q rebuild/tests/test_windows_launcher.py rebuild/tests/test_windows_flow.py` (6 passed); focused Ruff passed | Resolved | | Final legacy archive remains tracked separately by Phase 19 |
| HIGH-28 | High | Windows TUI bypasses and fake completion | 4, 11 | Windows TUI | Pending | Pending | Open | | |
| HIGH-29 | High | Guardian defaults when expected state absent | 13, 15 | guardian | Pending | Pending | Open | | |
| HIGH-30 | High | Tracker lock survives crashed process | 16 | task orchestrator | Pending | Pending | Open | | |
| HIGH-31 | High | Tracker/state writes are non-atomic | 3, 16 | task orchestrator/state | Pending | Pending | Open | | |
| HIGH-32 | High | No install or boot CI test | 17, 18 | CI/vmtest | Pending | Pending | Open | | |
| HIGH-33 | High | Omarchy bootstrap mutable and unlogged | 14 | first-login | Pending | Pending | Open | | |
| MED-01 | Medium | Safety-critical plan fields untyped | 2 | shared models | Added strict nested user, locale, free-space, encryption, filesystem, boot, Omarchy, and provenance models | `test_shipped_plan_template_passes_production_validator`; strict-extra test | Resolved | | |
| MED-02 | Medium | Sector range size not cross-validated | 2 | shared models | Added inclusive range arithmetic and cross-plan logical-sector validation | sector mismatch and cross-sector tests | Resolved | | |
| MED-03 | Medium | MBR permitted by GPT-only design | 2 | shared models | `DiskIdentity` now accepts GPT only | `test_gpt_is_the_only_supported_partition_style` | Resolved | | |
| MED-04 | Medium | Version comparison mishandles prereleases | 2 | versioning | Replaced parser with `packaging.version.Version` | `test_version_comparison_uses_standard_prerelease_ordering` | Resolved | | |
| MED-05 | Medium | Windows preflight parsing locale-dependent | 4, 5 | Windows checks | Pending | Pending | Open | | |
| MED-06 | Medium | Disk number used when serial absent | 2, 5, 9 | identity | Pending | Pending | Open | | |
| MED-07 | Medium | Copied ISO hash not verified | 6 | handoff | Source/destination SHA256 compared; corrupt copy removed | ISO copy and corruption tests | Resolved | | |
| MED-08 | Medium | FAT32 file-size limit unchecked | 6 | handoff | Rejects any FAT32 payload above 4 GiB minus one byte | sparse over-limit test | Resolved | | |
| MED-09 | Medium | Arbitrary 72-hour plan freshness | 6, 9 | discovery/main | Pending | Pending | Open | | |
| MED-10 | Medium | EXE version derived from commit digits | 7 | EXE build | Requires explicit semantic X.Y.Z and emits X.Y.Z.0 | strict VERSIONINFO test | Resolved | | |
| MED-11 | Medium | Prompt responses logged | 3, 10 | command/logging | Pending | Pending | Open | | |
| MED-12 | Medium | Release template incompatible | 2, 7 | models/templates | Template and publisher both validate with `ReleaseManifestContract` schema 1.0.0 | template and valid release-pair tests | Resolved | | |
| MED-13 | Medium | README/status materially stale | 1, 19 | documentation | Pending | Pending | Open | | |
| MED-14 | Medium | Tests enforce obsolete archinstall shape | 12, 17, 19 | Bats/contracts | Pending | Pending | Open | | |
| MED-15 | Medium | Tests mock away production failures | 17, 18 | integration/VM tests | Pending | Pending | Open | | |

## Baseline evidence

- Branch created from audited commit `08737764721d915921af4fa8a82015d3ea975fbd`.
- Working tree was clean before remediation.
- Host Python: 3.14.2.
- Initial Python tool baseline: pytest, Ruff, and mypy not installed.
- Docker/Compose baseline: unavailable on host.
- WSL baseline: WSL 2 available.
- Destructive disk, EFI, Ventoy, BitLocker, and boot-order commands were not run.
