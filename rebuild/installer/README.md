# Installer Workspace

This directory will hold the Python rebuild runtime.

Planned ownership boundaries:

- `shared/`: schema, compatibility, versioning, common validation contracts
- `platforms/windows/`: Windows checks, backup, partition prep, Ventoy, plan generation
- `platforms/linux_live/`: handoff discovery, preflight, network, partitioning, boot policy
- `platforms/installed_system/`: Omarchy wrapper, boot guardian, repair tooling
- `ui/`: Textual screens and shared widgets

The live installer now has an interactive Textual entrypoint in `installer/ui/screens.py`, and the Windows-side flow runs through `installer/platforms/windows/app.py` with Python-first migration logic.
