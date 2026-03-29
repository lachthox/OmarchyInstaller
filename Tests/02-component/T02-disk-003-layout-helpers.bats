#!/usr/bin/env bats
# T02-disk-003-layout-helpers.bats
# Component tests for disk layout helper functions.

setup() {
  load '../07-fixtures/assert'
  load '../07-fixtures/load-mocks'
  load '../07-fixtures/source-setup'
}

@test "disk_partition_count: blank disk returns zero" {
  export MOCK_LSBLK_OUTPUT='/dev/sda disk'
  run disk_partition_count "/dev/sda"
  assert_success
  assert_output "0"
}

@test "disk_partition_count: counts partitions on selected disk" {
  export MOCK_LSBLK_OUTPUT='/dev/sda disk
/dev/sda1 part
/dev/sda2 part'
  run disk_partition_count "/dev/sda"
  assert_success
  assert_output "2"
}

@test "partition_belongs_to_disk: sdX partition matches parent disk" {
  run partition_belongs_to_disk "/dev/sda" "/dev/sda1"
  assert_success
}

@test "partition_belongs_to_disk: nvme partition matches parent disk" {
  run partition_belongs_to_disk "/dev/nvme0n1" "/dev/nvme0n1p2"
  assert_success
}

@test "partition_belongs_to_disk: partition from another disk is rejected" {
  run partition_belongs_to_disk "/dev/sda" "/dev/sdb1"
  assert_failure
}

@test "collect_partition_paths: only partition device paths are returned" {
  export MOCK_LSBLK_OUTPUT='/dev/sda disk
/dev/sda1 part
/dev/sda2 part'
  run collect_partition_paths "/dev/sda"
  assert_success
  assert_output "/dev/sda1
/dev/sda2"
}

@test "find_partition_by_label: returns matching partition path" {
  export MOCK_LSBLK_OUTPUT='/dev/sda 
/dev/sda1 EFI
/dev/sda2 ROOT'
  run find_partition_by_label "/dev/sda" "ROOT"
  assert_success
  assert_output "/dev/sda2"
}

@test "disk_menu_hint: includes transport and serial" {
  export MOCK_LSBLK_OUTPUT='nvme ABC123 0'
  run disk_menu_hint "/dev/nvme0n1"
  assert_success
  assert_output " (nvme sn:ABC123)"
}

@test "disk_menu_hint: marks removable devices" {
  export MOCK_LSBLK_OUTPUT='usb  1'
  run disk_menu_hint "/dev/sdb"
  assert_success
  assert_output_contains "removable"
}

@test "disk_partition_preview: renders partition details" {
  export MOCK_LSBLK_OUTPUT='/dev/sda1 512M vfat EFI /boot
/dev/sda2 100G btrfs ROOT /'
  run disk_partition_preview "/dev/sda"
  assert_success
  assert_output_contains "/dev/sda1 | 512M | fs:vfat | label:EFI"
  assert_output_contains "/dev/sda2 | 100G | fs:btrfs | label:ROOT"
}
