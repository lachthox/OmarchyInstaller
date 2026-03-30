# Installer Workspace

This directory will hold the Python rebuild runtime.

Planned ownership boundaries:

- `shared/`: schema, compatibility, versioning, common validation contracts
- `platforms/windows/`: Windows checks, backup, partition prep, Ventoy, plan generation
- `platforms/linux_live/`: handoff discovery, preflight, network, partitioning, boot policy
- `platforms/installed_system/`: Omarchy wrapper, boot guardian, repair tooling
- `ui/`: Textual screens and shared widgets

Scaffold modules now exist for each boundary, with placeholder entrypoints that will be replaced by implementation slices.
