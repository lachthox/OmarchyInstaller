# Installation guide

> [!CAUTION]
> This workflow shrinks or prepares disks and completely erases the selected
> USB. Verify every model, size, and disk number shown before confirming.

## Supported journey

1. Download `OmarchyInstaller.exe` from an immutable release tag and verify its
   published hash and attestation.
2. Double-click `OmarchyInstaller.exe` and approve the Windows Administrator
   prompt. The EXE always starts the real guided apply workflow; it downloads
   the customized ISO and paired manifests for its baked-in release tag,
   verifies every SHA-256 entry, and caches them under LocalAppData.
3. Complete the
   preflight, verified backups, shrink, Ventoy, ISO-copy, and authenticated
   handoff stages in order. The USB step detects removable disks, selects the
   only safe candidate automatically, or lets you choose with Up/Down when
   several are attached. If Ventoy is absent, the verified official Windows
   release is downloaded and cached automatically.
4. Reboot from that Ventoy device in UEFI mode and select the paired ISO. The
   live installer automatically checks the USB, prepared disk space, machine,
   and network connection.
5. Choose one password for disk unlock and login, review the plain-language
   summary, and press Enter to install. Technical diagnostics remain hidden in
   Advanced view unless they are needed.
6. Reboot into the installed system. Log in as the target non-root user to run
   the one-time interactive Omarchy first-login flow.
7. Review guardian status and preserve the Windows, GPT, ESP, and BCD backups.

There are no supported shell, PowerShell, manual-bootstrap, simulation, or
compatibility entrypoints for end users. The EXE owns the complete Windows-side
workflow.
