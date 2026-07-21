# ISO packaging contract

The rebuild supports one immutable upstream base at a time:

- Arch Linux ISO: `2026.07.01`
- ISO URL directory: `https://geo.mirror.pkgbuild.com/iso/2026.07.01`
- Arch package snapshot: `https://archive.archlinux.org/repos/2026/07/01`
- Bundled archinstall package: `4.4-1`

The release and mirror records were verified on 2026-07-21 against the official
[Arch release list](https://archlinux.org/releng/releases/) and the official
[Arch package mirror](https://geo.mirror.pkgbuild.com/extra/os/x86_64/). A newer
monthly ISO is not adopted implicitly; changing either pin requires contract,
boot, disposable-install, reboot, and recovery validation.

## Trust and reproducibility

The pipeline downloads the dated ISO and validates its entry in the official
`sha256sums.txt`. Rootfs package installation uses the dated Arch Linux Archive,
the Arch keyring, and normal pacman signature verification. There is no
signature-disabled fallback.

`rebuild/requirements.lock` pins every Python transitive dependency and includes
artifact SHA-256 hashes. The ISO build creates `/opt/omarchy-venv`, installs that
lock with `pip --require-hashes`, and adds only `/opt/omarchy-installer` to the
environment's import path. The one canonical launch command is:

```text
/opt/omarchy-venv/bin/python -m installer.main
```

It is independent of the caller's current directory. Build metadata records the
base ISO, source checksum, release version/tag/commit, Python lock, virtual
environment, archinstall version, startup hook, and required runtime commands.

## Runtime verification

The rootfs build fails unless archinstall is exactly `4.4-1`, the installer is
importable from `/`, and these commands exist: `cryptsetup`, `mkfs.btrfs`,
`mount`, `umount`, `findmnt`, `lsblk`, `blkid`, `udevadm`, `partprobe`, `sgdisk`,
`efibootmgr`, `nmcli`, and `archinstall`.

The build trap unmounts tracked bind/proc/sys/tmpfs mounts in reverse order
before removing its temporary tree. Static and dry-run tests run on Windows;
OVMF boot and offline-startup acceptance remain blocked until a QEMU-capable
Linux runner is available.
