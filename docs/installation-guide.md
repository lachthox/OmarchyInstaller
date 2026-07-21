# Installation guide

> [!CAUTION]
> The supported journey is not approved for real hardware until the release
> readiness checklist and disposable UEFI VM install/reboot gate pass.

## Supported journey

1. Download the paired `OmarchyInstaller.exe`, customized Arch ISO, checksum
   file, release manifest, and compatibility manifest from one immutable tag.
2. Verify the published hashes and attestation.
3. Run `OmarchyInstaller.exe` from an elevated Windows session. Complete the
   preflight, verified backups, shrink, Ventoy, ISO-copy, and authenticated
   handoff stages in order.
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
