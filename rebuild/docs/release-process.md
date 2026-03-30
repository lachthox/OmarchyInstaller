# Release Process

This document describes the release and packaging flow for the rebuild.

## Purpose

The release process turns the repository state into repeatable deliverables: the customized Arch ISO, the packaged Windows EXE, checksums, and release metadata.

## Release model

The release layer is responsible for:

- building the customized Arch ISO
- building the packaged Windows EXE
- publishing release artifacts
- publishing checksums and compatibility metadata
- rebuilding automatically when relevant source or packaging files change

## Workflow boundaries

- CI and packaging logic belong in the build/release layer.
- Runtime installer logic must not be embedded into workflow YAML.
- Platform implementation work must stay separate from release orchestration.
- Workflows should call Python tooling from `rebuild/tools/**` instead of inlining orchestration logic.

## Required outputs

Each release should produce a consistent set of artifacts, including:

- ISO artifact
- Windows EXE artifact
- checksum file
- release manifest
- compatibility metadata

Operational readiness evidence (required before production publish):

- completed hardware boot matrix report (`rebuild/docs/hardware-boot-matrix-report.template.json`)
- completed firstboot validation report (`rebuild/docs/firstboot-validation-report.template.json`)
- passing release readiness audit output from `rebuild/tools/release_readiness_check.py`

## Trigger policy

Rebuilds must be triggered when changes affect:

- ISO payload structure
- Windows EXE packaging inputs
- shared contracts and compatibility logic
- release metadata or manifest behavior

## Trigger matrix

The workflow trigger matrix keeps the release artifacts fresh without depending on manual judgement:

| Change area                                                                                                    | Workflow result                                            |
| -------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------- |
| `build-custom-iso.sh`, `rebuild/installer/**`, `rebuild/assets/**`, or rebuild dependency files                | Rebuild the ISO artifact                                   |
| `windows-prep.ps1`, `rebuild/tools/build_windows_exe.py`, `rebuild/tools/windows/**`, or shared contract files | Rebuild the Windows EXE artifact                           |
| Any ISO, EXE, or shared contract change                                                                        | Rebuild the release bundle and regenerate release metadata |

## Freshness policy

- Release outputs must be rebuilt from the current source slice when their owned inputs change.
- Shared contract changes are freshness-critical and must invalidate both ISO and EXE outputs.
- A release publication must never reuse stale manifests or checksums when any owned build input has changed.

## Coordination rules

- Treat release metadata as a first-class contract.
- Do not publish artifacts without the matching compatibility context.
- Keep build/release work reviewable and separate from runtime changes.

## Ownership

Primary boundary:

- `rebuild/tools/**`

Workflow boundary:

- `.github/workflows/**`

Supporting docs:

- `rebuild/docs/dependency-map.md`
- `rebuild/docs/github-project-setup.md`
- `rebuild/docs/STATUS.md`

## Current implementation note

- `.github/workflows/rebuild-iso.yml` invokes `rebuild/tools/build_iso_pipeline.py` to build the customized Arch ISO artifact and emit build manifest metadata.
- `.github/workflows/rebuild-windows-exe.yml` invokes `rebuild/tools/build_windows_exe.py` to package `OmarchyInstaller.exe` with PyInstaller and emit executable build manifest metadata.
- `.github/workflows/rebuild-release.yml` invokes `rebuild/tools/publish_release.py` to produce `release_manifest.json`, `compatibility_manifest.json`, consolidated checksums, and optional GitHub Release publication.

## Readiness audit

Before production publication, run release readiness audit with all gates enforced:

```
python rebuild/tools/release_readiness_check.py \
	--artifact-dir <release-artifact-dir> \
	--hardware-report rebuild/docs/hardware-boot-matrix-report.json \
	--firstboot-report rebuild/docs/firstboot-validation-report.json \
	--require-all \
	--output rebuild/dist/release/release-readiness-audit.json
```

This gate enforces:

- release EXE default launcher policy is `python-then-legacy`
- required hardware matrix cases are marked `pass`
- required firstboot/boot-guardian validation checks are marked `pass`

## Coordination note

This document is the release-process companion to the stage briefs and the dependency map. It should be kept aligned with the current build/release issue hierarchy.
