# Installation guide

> [!CAUTION]
> The supported journey is not approved for real hardware until the release
> readiness checklist and disposable UEFI VM install/reboot gate pass.

## Supported journey

1. Download `OmarchyInstaller.exe` from an immutable release tag and verify its
   published hash and attestation.
2. Run `OmarchyInstaller.exe` from an elevated Windows session. It downloads
   the customized ISO and paired manifests for its baked-in release tag,
   verifies every SHA-256 entry, and caches them under LocalAppData.
3. Complete the
   preflight, verified backups, shrink, Ventoy, ISO-copy, and authenticated
   handoff stages in order. The USB step detects removable disks, selects the
   only safe candidate automatically, or lets you choose with Up/Down when
   several are attached. If Ventoy is absent, the verified official Windows
   release is downloaded and cached automatically.
4. Reboot from that Ventoy device in UEFI mode and select the paired ISO. The
   live console launches `/opt/omarchy-venv/bin/python -m installer.main`.
5. Review the rediscovered disk identity and destructive summary. Apply only
   after every preflight passes and the typed confirmation matches.
6. Reboot into the installed system. Log in as the target non-root user to run
   the one-time interactive Omarchy first-login flow.
7. Review guardian status and preserve the Windows, GPT, ESP, and BCD backups.

There are no supported shell, PowerShell, manual-bootstrap, or compatibility
entrypoints. Until release readiness changes to approved, use only disposable
VMs and synthetic disks.
