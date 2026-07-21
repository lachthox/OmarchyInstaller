# Security model

Status: implemented with synthetic tests; real-hardware use prohibited pending
isolated VM and recovery acceptance.

## Device safety

Ventoy installation re-reads the candidate disk before any Ventoy command. It
requires USB bus type, rejects boot/system/pagefile disks, requires a stable
serial or disk GUID, displays a 12-character identifier derived from serial,
model, size, and GUID, and accepts only `ERASE <identifier>`. Identity is read a
second time immediately before the write. Any mismatch blocks.

## Media and handoff integrity

- FAT32 payloads are checked against the 4 GiB file limit; exFAT is preferred.
- ISO source and destination SHA256 must match after copy.
- The plan and every optional handoff artifact are hashed after writing.
- `omarchy/handoff-manifest.json` binds plan/ISO hashes, release tag, commit,
  workflow run, producer/schema versions, and GPT disk/partition identities.
- The manifest has an HMAC-SHA256 made with a one-time key of at least 256 bits.
  The key is never written to the USB and must be entered/transported separately.
- The Windows TUI displays the generated key after verified staging; the user
  enters its 64 hexadecimal characters into the concealed live-TUI field. Linux
  mounts exactly one removable Ventoy data partition read-only, verifies the
  HMAC and every bound identity/hash, then unmounts it.

## Secrets

Plaintext Wi-Fi profiles on removable media are disabled. Credentials are
entered interactively in the live environment and must never appear in argv or
ordinary diagnostics.
