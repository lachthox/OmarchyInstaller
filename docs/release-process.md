# Release process

Status: publication remains blocked by later VM gates and Windows code signing.

The VM job also requires an isolated console-automation driver configured as
`OMARCHY_ISOLATED_VM_DRIVER`. Its evidence is schema-checked and bound to the
exact ISO hash; missing, dry-run, partial, or mismatched evidence blocks publish.

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

## External signing blocker

Authenticode signing cannot be completed in this checkout because no code-signing
certificate, private-key service, timestamp authority configuration, or CI secret
contract has been provided. The EXE may be built for tests, but release approval
remains blocked until signing and verification run in CI with managed credentials.
