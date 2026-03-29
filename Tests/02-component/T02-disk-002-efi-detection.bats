#!/usr/bin/env bats
# T02-disk-002-efi-detection.bats
# Component tests for find_efi_partition.
#
# find_efi_partition makes two lsblk calls:
#   1. lsblk -prno NAME,PARTTYPE,FSTYPE <disk>
#      → awk checks tolower($2) == EFI PARTTYPE UUID
#   2. lsblk -prno NAME,FSTYPE,MOUNTPOINT <disk>   (fallback)
#      → awk checks tolower($2)=="vfat" && mountpoint is /boot or /boot/efi
#
# The mock lsblk stub dispatches on argument keywords:
#   MOCK_LSBLK_PARTTYPE_OUTPUT  → used when args contain "PARTTYPE"
#   MOCK_LSBLK_FSTYPE_OUTPUT    → used when args contain "MOUNTPOINT"
#
# EFI System Partition GUID: C12A7328-F81F-11D2-BA4B-00A0C93EC93B

setup() {
  load '../07-fixtures/assert'
  load '../07-fixtures/load-mocks'
  load '../07-fixtures/source-setup'
}

_EFI_GUID="C12A7328-F81F-11D2-BA4B-00A0C93EC93B"
_EFI_GUID_LOWER="c12a7328-f81f-11d2-ba4b-00a0c93ec93b"

# ---------------------------------------------------------------------------
# PARTTYPE-based detection (primary path)
# ---------------------------------------------------------------------------

@test "find_efi_partition: detects EFI by PARTTYPE UUID (mixed case)" {
  export MOCK_LSBLK_PARTTYPE_OUTPUT="/dev/sda1 ${_EFI_GUID} vfat"
  export MOCK_LSBLK_FSTYPE_OUTPUT=""
  run find_efi_partition "/dev/sda"
  assert_success
  assert_output "/dev/sda1"
}

@test "find_efi_partition: detects EFI by PARTTYPE UUID (lowercase)" {
  export MOCK_LSBLK_PARTTYPE_OUTPUT="/dev/sda1 ${_EFI_GUID_LOWER} vfat"
  export MOCK_LSBLK_FSTYPE_OUTPUT=""
  run find_efi_partition "/dev/sda"
  assert_success
  assert_output "/dev/sda1"
}

@test "find_efi_partition: detects EFI on NVMe device by PARTTYPE" {
  export MOCK_LSBLK_PARTTYPE_OUTPUT="/dev/nvme0n1p1 ${_EFI_GUID} vfat"
  export MOCK_LSBLK_FSTYPE_OUTPUT=""
  run find_efi_partition "/dev/nvme0n1"
  assert_success
  assert_output "/dev/nvme0n1p1"
}

@test "find_efi_partition: returns first EFI partition when multiple match PARTTYPE" {
  # awk uses `exit` after first match — first line wins
  export MOCK_LSBLK_PARTTYPE_OUTPUT="/dev/sda1 ${_EFI_GUID} vfat
/dev/sda2 ${_EFI_GUID} vfat"
  export MOCK_LSBLK_FSTYPE_OUTPUT=""
  run find_efi_partition "/dev/sda"
  assert_success
  assert_output "/dev/sda1"
}

@test "find_efi_partition: non-EFI PARTTYPE entries are ignored" {
  # Linux data partition GUID
  export MOCK_LSBLK_PARTTYPE_OUTPUT="/dev/sda2 0FC63DAF-8483-4772-8E79-3D69D8477DE4 ext4"
  export MOCK_LSBLK_FSTYPE_OUTPUT=""
  run find_efi_partition "/dev/sda"
  assert_success
  assert_output ""
}

# ---------------------------------------------------------------------------
# Fallback detection (FSTYPE + mountpoint)
# ---------------------------------------------------------------------------

@test "find_efi_partition: fallback detects vfat partition mounted at /boot" {
  export MOCK_LSBLK_PARTTYPE_OUTPUT=""
  export MOCK_LSBLK_FSTYPE_OUTPUT="/dev/sda1 vfat /boot"
  run find_efi_partition "/dev/sda"
  assert_success
  assert_output "/dev/sda1"
}

@test "find_efi_partition: fallback detects vfat partition mounted at /boot/efi" {
  export MOCK_LSBLK_PARTTYPE_OUTPUT=""
  export MOCK_LSBLK_FSTYPE_OUTPUT="/dev/sda1 vfat /boot/efi"
  run find_efi_partition "/dev/sda"
  assert_success
  assert_output "/dev/sda1"
}

@test "find_efi_partition: fallback ignores vfat not at /boot or /boot/efi" {
  export MOCK_LSBLK_PARTTYPE_OUTPUT=""
  export MOCK_LSBLK_FSTYPE_OUTPUT="/dev/sda1 vfat /mnt/usb"
  run find_efi_partition "/dev/sda"
  assert_success
  assert_output ""
}

@test "find_efi_partition: fallback ignores non-vfat at /boot" {
  export MOCK_LSBLK_PARTTYPE_OUTPUT=""
  export MOCK_LSBLK_FSTYPE_OUTPUT="/dev/sda1 ext4 /boot"
  run find_efi_partition "/dev/sda"
  assert_success
  assert_output ""
}

# ---------------------------------------------------------------------------
# No EFI found
# ---------------------------------------------------------------------------

@test "find_efi_partition: returns empty when no EFI partition present" {
  export MOCK_LSBLK_PARTTYPE_OUTPUT="/dev/sda1 0FC63DAF-8483-4772-8E79-3D69D8477DE4 ext4
/dev/sda2 0FC63DAF-8483-4772-8E79-3D69D8477DE4 swap"
  export MOCK_LSBLK_FSTYPE_OUTPUT="/dev/sda1 ext4 /
/dev/sda2 swap [SWAP]"
  run find_efi_partition "/dev/sda"
  assert_success
  assert_output ""
}

@test "find_efi_partition: empty lsblk output returns empty" {
  export MOCK_LSBLK_PARTTYPE_OUTPUT=""
  export MOCK_LSBLK_FSTYPE_OUTPUT=""
  run find_efi_partition "/dev/sda"
  assert_success
  assert_output ""
}
