# Python installer implementation

`rebuild/` contains the canonical Python implementation under active remediation.
It is no longer a future-only scaffold, but it is not release-ready until the
repository acceptance gates pass.

Runtime boundaries:

- `installer/shared/`: strict contracts and cross-platform safety policy;
- `installer/platforms/windows/`: Windows preparation;
- `installer/platforms/linux_live/`: live installation;
- `installer/platforms/installed_system/`: first-login and boot guardian;
- `installer/ui/`: Textual interaction and state presentation;
- `tools/`: packaging, release, and repository automation;
- `assets/`: packaged scripts, services, templates, and ISO assets.

No compatibility launcher exists. Inert historical source is isolated under
`../legacy/unsupported/` and is excluded from all runtime and packaging paths.

See `../docs/remediation-status.md` for finding-level status and
`../docs/adr/0001-python-only-installer.md` for the target architecture.
