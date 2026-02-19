# Omarchy Portable Installer

Portable installer toolkit for Omarchy dual-boot setups across Windows and Arch live ISO.

This project provides two guided assistants:

- `windows-prep.ps1`: interactive Windows pre-install helper (machine prep + optional ISO/USB creation).
- `setup.sh`: interactive Arch live-ISO installer helper for partitioning + `archinstall` config generation.

## What it does

### Windows pre-install (`windows-prep.ps1`)

- Validates elevated/admin execution.
- Checks readiness signals:
  - Secure Boot status
  - BitLocker status
  - Fast Startup status (with optional disable)
- Shows disk inventory and unallocated space.
- Optionally shrinks `C:` to create unallocated space with safe bounds.
- Optionally downloads latest Arch ISO + verifies SHA256 (saved in `media/` under the script folder).
- Optionally creates UEFI USB media using Ventoy CLI and ISO copy workflow.
- Optional download of a pre-built customized Arch ISO (built automatically by GitHub Actions CI) that auto-prompts to run `setup.sh` on first live shell.
- Shows progress bars with ETA for major workflow stages, downloads, partitioning, and USB copy operations.

### Arch live installer (`setup.sh`)

- Verifies internet access before installation and guides Wi-Fi/Ethernet setup if offline.
- Detects available disks and helps choose a target disk.
- Detects an EFI partition automatically (with manual override).
- Computes logic-based defaults per machine:
  - Hostname from DMI/machine identity
  - Username from current context
  - Timezone from system/network
  - CPU microcode package (`intel-ucode` or `amd-ucode`)
- Guides through credentials and locale settings.
- Shows a confirmation summary before partitioning.
- Creates one Linux root partition in unallocated space.
- Generates `/tmp/omarchy_config.json` and runs `archinstall`.
- Shows progress bars with ETA for end-to-end install stages, partition creation, and the `archinstall` run.

## Requirements

### Windows phase

- Windows PowerShell 5.1+ or PowerShell 7+
- Run as Administrator
- Internet access for ISO download
- `winget` (for automatic Ventoy CLI install)
- Internet access to download the pre-built customized ISO from GitHub Releases (no local build tools needed)

### Arch phase

Run from an Arch Linux live ISO session with:

- `archinstall`
- `sgdisk` (from `gptfdisk`)
- `lsblk`
- `partprobe`
- `whiptail` (optional but recommended)

## Quick start

### 1) Windows preparation

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\windows-prep.ps1
```

### 2) Arch installation

```bash
chmod +x setup.sh
sudo ./setup.sh
```

If using the customized ISO and the live-shell auto-prompt does not appear, run:

```bash
cd /opt/omarchy-setup
chmod +x setup.sh
./setup.sh
```

## Safety model

- Existing EFI partition is reused, not wiped.
- Existing Windows partitions are not reformatted by `setup.sh`.
- `setup.sh` requires at least 40 GiB unallocated space.
- Destructive steps (partition create / USB wipe) always require explicit confirmation.

## After installation

After reboot:

```bash
curl -fsSL https://omarchy.org/install | bash
```

If Windows does not appear in the boot menu:

```bash
sudo limine-update
```

## Project files

- `windows-prep.ps1`: Windows pre-install and optional media creation assistant.
- `setup.sh`: Arch live installer assistant script.
- `build-custom-iso.sh`: standalone Linux script to build the customized Arch ISO (used by CI and for local dev).
- `.github/workflows/build-iso.yml`: GitHub Actions workflow that builds and publishes the customized ISO on each release.
- `installation-guide.md`: full step-by-step operational guide.
- `.editorconfig`: formatting defaults.
- `.gitattributes`: line ending normalization.
- `.gitignore`: standard ignore patterns.
- `LICENSE`: MIT license.

## GitHub upload checklist

1. Initialize git in this folder (if not already):
   ```bash
   git init
   ```
2. Add files:
   ```bash
   git add .
   ```
3. Commit:
   ```bash
   git commit -m "Portable Omarchy installer toolkit"
   ```
4. Create a GitHub repo and push:
   ```bash
   git remote add origin <your-repo-url>
   git branch -M main
   git push -u origin main
   ```
