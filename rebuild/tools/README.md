# Build And Release Tools Workspace

This directory is reserved for Python build and release tooling that should be invoked by GitHub Actions instead of burying orchestration logic inside workflow YAML.

Planned examples:

- ISO payload preparation
- release manifest generation
- compatibility stamping
- Windows EXE packaging helpers
- artifact naming and checksum generation

Current scaffolded tools:

- `build_iso_pipeline.py`: rebuild-owned Arch ISO pipeline runner that detects source ISO, verifies checksums, stages Python runtime payload files, invokes `build-custom-iso.sh`, and emits ISO build metadata.
- `build_windows_exe.py`: rebuild-owned Windows EXE pipeline runner that packages `OmarchyInstaller.exe` with PyInstaller, stamps version metadata, and emits executable build metadata.
- `publish_release.py`: rebuild-owned release publisher that creates `release_manifest.json`, `compatibility_manifest.json`, consolidated checksums, and optional GitHub Release asset uploads.
