# Rebuild Assets Workspace

This directory is reserved for static assets that belong to the rebuild architecture.

Planned examples:

- service unit templates
- bootstrap scripts
- JSON templates
- packaged runtime assets for ISO and installed-system stages

Current scaffolded paths:

- `templates/`: plan and release manifest template JSON files
- `services/`: systemd unit templates for first-boot handoff and boot guardian
- `scripts/`: helper shell wrappers for live autostart and first-boot flow
- `iso_payload/`: ISO payload asset area
- `startup/`: installed-system startup asset area
