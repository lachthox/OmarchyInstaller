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
| `rebuild/tools/build_windows_exe.py`, `rebuild/tools/windows/**`, or shared contract files | Rebuild the Windows EXE artifact                           |
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

## Current implementation

- `.github/workflows/rebuild-ci.yml` is the sole continuous validation graph.
- `.github/workflows/rebuild-release.yml` is the sole artifact build and publish graph.
- Python tools build the ISO and EXE, run the VM gate, and construct the paired
  manifests; workflow YAML only orchestrates those tools.

## Mandatory release graph

There is one publishing workflow. Its publish job depends on successful Python
Ruff/mypy/pytest, ShellCheck/Bats, pinned upstream archinstall contracts,
normal-user PTY, ISO build, Windows EXE build/test, and disposable VM
install-and-reboot jobs. GitHub Actions cannot schedule publication if any need
fails or is skipped. No independent artifact publisher exists.

The install/reboot job delegates firmware and console control to the isolated
runner's `OMARCHY_ISOLATED_VM_DRIVER`. The repository harness rejects absent,
dry-run, hash-mismatched, or incomplete install/reboot/EFI/first-login/recovery
evidence.

Dry-run artifacts are never inputs to the release workflow. The publisher still
revalidates unique ISO/EXE manifests, exact commit/tag/version/run/ref pairing,
non-dry-run state, and every artifact hash immediately before publication.

## Coordination note

This document is the release-process companion to the stage briefs and the dependency map. It should be kept aligned with the current build/release issue hierarchy.
