# Omarchy Portable Installation Guide

Use this guide from a second device while installing.

## 1. Windows Pre-Install (Recommended)

From Windows, run the helper first:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\windows-prep.ps1
```

What it helps with:

- Readiness checks (Secure Boot, BitLocker, Fast Startup).
- Disk overview and unallocated-space planning.
- Optional automatic `C:` shrink to create install space.
- Optional latest Arch ISO download + checksum verification (stored in `media/` under the script folder).
- Optional download of a pre-built customized Arch ISO (built by CI) that auto-prompts to run `setup.sh` on first live shell.
- Optional USB live media creation from the ISO (Ventoy CLI workflow).
- Progress bars + ETA for major steps (workflow stages, downloads, partitioning, and media creation).

## 2. Manual Preparation Checklist

If you skip the PowerShell helper, do these manually:

1. Back up important data.
2. In Windows, shrink your main partition to create unallocated space (recommended 100+ GiB).
3. Create an Arch Linux USB installer.
4. Copy this `omarchy-setup` folder to the USB or another accessible drive.
5. In BIOS/UEFI:
   - Disable Secure Boot.
   - Ensure storage is visible to Linux (disable Intel VMD/RST if needed).

## 3. Boot Arch Live ISO

1. Boot from the Arch USB in UEFI mode.
2. Connect to network:
   ```bash
   iwctl
   device list
   station <wifi-device> scan
   station <wifi-device> get-networks
   station <wifi-device> connect <SSID>
   quit
   ```
3. Verify internet:
   ```bash
   ping -c 3 archlinux.org
   ```

If you chose the pre-built customized ISO during Windows prep, the live shell on first boot will automatically prompt to launch `setup.sh`.

## 4. Run the Arch Installer Assistant

1. Mount the drive containing this folder (if needed).
2. Enter the project folder and run:
   ```bash
   chmod +x setup.sh
   sudo ./setup.sh
   ```
3. Follow prompts:
   - Disk selection
   - EFI partition confirmation
   - Hostname, username, timezone, keyboard layout
   - User and encryption passwords
   - Final confirmation before partitioning and install
4. Watch progress output during long operations:
   - Stage progress with ETA across the full flow.
   - Live progress bar + ETA while creating the partition.
   - Live progress bar + ETA during `archinstall`.

## 5. What the Arch Script Changes

- Creates one new Linux partition in free, unallocated space.
- Keeps existing Windows partitions intact.
- Reuses existing EFI partition for boot files.
- Configures encrypted Btrfs root with common subvolumes.
- Runs `archinstall` with generated config at `/tmp/omarchy_config.json`.

## 6. After Reboot

1. Boot into your new Arch/Omarchy install.
2. Log in with the created user.
3. Run:
   ```bash
   curl -fsSL https://omarchy.org/install | bash
   ```

If Windows is missing in the boot menu:

```bash
sudo limine-update
```

## Troubleshooting

- Internal disk not visible in Windows helper:
  - Run PowerShell as Administrator and verify storage drivers are loaded.
- Internal disk not visible in Arch:
  - Check BIOS storage mode and disable Intel VMD/RST.
- EFI partition not auto-detected in `setup.sh`:
  - Manually enter the correct EFI partition path when prompted.
- Not enough free space:
  - Re-run `windows-prep.ps1` and choose resize, or shrink manually in Disk Management.
- Install cancelled:
  - Re-run `sudo ./setup.sh`; it is interactive and confirmation-based.
