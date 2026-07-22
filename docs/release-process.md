# Release process

Status: the VM/install/reboot/recovery gates now pass green in CI (run
`29886048248`), and the release workflow can publish a downloadable
**unsigned** release now (see "Unsigned releases" below). Real Windows code
signing is an optional upgrade documented in `docs/windows-code-signing.md`,
not a publication blocker.

The VM job also requires a console-automation driver configured as
`OMARCHY_ISOLATED_VM_DRIVER`. A real implementation of this contract,
`rebuild/tools/vm_drivers/qemu_ovmf_driver.py`, has been built and proven
against a disposable KVM-accelerated VM: it drives the real production TUI
to a real, non-mocked install completion with verified Windows EFI
preservation, but does not yet succeed at unlocking the installed system's
LUKS2 volume after reboot (see `docs/test-evidence.md` Phase 21 and
`docs/release-readiness.md`). Its evidence is schema-checked and bound to the
exact ISO hash; missing, dry-run, partial, or mismatched evidence blocks
publish. The `offline-iso-boot`, `vm-install-reboot`, and
`recovery-rehearsal` jobs run on GitHub-hosted `ubuntu-latest` runners
(public-repo `/dev/kvm` access), not self-hosted infrastructure.

## Immutable paired build

The canonical release workflow is `.github/workflows/rebuild-release.yml` and is
manual-only. It requires an explicit `X.Y.Z` release version and a new immutable
tag. ISO and EXE manifests must both state `dry_run=false` and match on commit,
tag, version, workflow run, ref, schema, filename, and SHA256. Recursive matches
must be unique. The publishing checkout commit must also match.

Windows VERSIONINFO is derived only from the explicit semantic version as
`X.Y.Z.0`; commit text is never parsed as a product version.

Release and compatibility manifests are generated atomically and the release
manifest is validated through its production Pydantic model. Existing tags fail;
upload never uses `--clobber`.

## Attestation order

The workflow uses `actions/attest@v4` with `id-token: write` and
`attestations: write`, following GitHub's current official contract:

- https://github.com/actions/attest
- https://docs.github.com/actions/security-for-github-actions/using-artifact-attestations

ISO/EXE and generated release metadata are attested before the optional publish
step. Publication uses `--publish-only`, which verifies and reuses the attested
files without rewriting them.

## Unsigned releases and optional signing

The default release path publishes an **unsigned** Windows EXE. When no managed
Authenticode secret is configured, `sign_windows_exe.py` records
`production_signing: false` / `signed: false`, and the publish step runs with
`--allow-unsigned`, so `publish_release.py` permits the unsigned artifact instead
of failing closed. Users will encounter a Windows SmartScreen warning; artifact
origin and integrity are still verifiable via `sha256sums.txt` and the GitHub
build-provenance attestation produced by `actions/attest@v4`.

To publish a **real signed** release instead — including the free SignPath
Foundation open-source option — follow `docs/windows-code-signing.md`: provision
the `WINDOWS_CODESIGN_*` secrets (no code change needed; the signer auto-detects
them) and remove `--allow-unsigned` from the publish step to restore the
fail-closed gate that requires `production_signing: true`.
