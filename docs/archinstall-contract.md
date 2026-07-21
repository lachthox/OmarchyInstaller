# Pinned archinstall contract

The live installer supports Arch's `archinstall 4.4-1`, whose upstream tag is
`4.4` at commit `3ece182d31dda7b14abd56d13abf3ff79a5717ae`. The contract was derived from
the official [archinstall repository](https://github.com/archlinux/archinstall/tree/4.4)
and its [declarative configuration documentation](https://archinstall.archlinux.page/installing/guided.html).

Three files remain separate:

- the Omarchy handoff/runtime plan;
- a strict archinstall 4.4 configuration;
- mode-0600 archinstall credentials containing a crypt-format password hash.

The archinstall configuration uses `disk_config.config_type =
pre_mounted_config` at `/mnt/archinstall`. It never contains Omarchy disk
identity, prepared-sector, provenance, LUKS passphrase, or other internal-plan
fields. The invocation is `archinstall --config <path> --creds <path> --silent
--mountpoint /mnt/archinstall`.

Before any partition command, strict semantic models validate the full internal
plan, archinstall config, and credentials. The transaction then saves GPT and
disk snapshots, rechecks the usable extent, creates the partition, records its
actual geometry/PARTUUID, creates LUKS2 and Btrfs, builds all configured
subvolumes, mounts the verified ESP at `/boot`, and runs archinstall. It installs
the kernel, CPU microcode selected by archinstall, locale/timezone/keyboard,
normal sudo user, NetworkManager, required bootstrap packages, Limine, and an
`sd-encrypt` initramfs.

Mounts are tracked and unmounted in reverse order, LUKS is closed on both
success and failure, and the credentials file is always deleted. Redacted
diagnostics, the semantic config, GPT backup, and pre-partition snapshot remain.

Local strict-model and fake-command contract tests pass. Exact execution by the
pinned archinstall package and disposable-VM installation remain blocked until
a Linux/QEMU runner is available; this is not waived by the unit tests.
