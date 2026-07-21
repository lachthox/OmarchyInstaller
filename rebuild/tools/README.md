# Build And Release Tools Workspace

This directory contains the Python build, VM-evidence, and release tools invoked
by GitHub Actions instead of embedding orchestration logic in workflow YAML.

Supported tools:

- `build_iso_pipeline.py`: rebuild-owned Arch ISO pipeline runner that detects source ISO, verifies checksums, stages Python runtime payload files, invokes `build-custom-iso.sh`, and emits ISO build metadata.
- `build_windows_exe.py`: rebuild-owned Windows EXE pipeline runner that packages `OmarchyInstaller.exe` with PyInstaller, stamps version metadata, and emits executable build metadata.
- `publish_release.py`: rebuild-owned release publisher that creates `release_manifest.json`, `compatibility_manifest.json`, consolidated checksums, and optional GitHub Release asset uploads.
- `vm_install_test.py`: fail-closed policy boundary for isolated UEFI install,
  reboot, Windows-preservation, first-login, and recovery evidence.
