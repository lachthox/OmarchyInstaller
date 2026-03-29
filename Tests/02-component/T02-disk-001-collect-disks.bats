#!/usr/bin/env bats
# T02-disk-001-collect-disks.bats
# Component tests for collect_disks.
#
# Strategy: load mock-commands/ before setup.sh so the mock `lsblk` stub
# shadows the real binary.  Set MOCK_LSBLK_OUTPUT to control what lsblk
# returns, then verify collect_disks parses it correctly.

setup() {
  load '../07-fixtures/assert'
  load '../07-fixtures/load-mocks'
  load '../07-fixtures/source-setup'
}

# ---------------------------------------------------------------------------
# Single disk
# ---------------------------------------------------------------------------

@test "collect_disks: single disk line parsed to name|size|model" {
  export MOCK_LSBLK_OUTPUT='NAME="sda" SIZE="500G" TYPE="disk" MODEL="Samsung SSD 870"'
  run collect_disks
  assert_success
  assert_output "sda|500G|Samsung SSD 870"
}

@test "collect_disks: NAME field extracted correctly" {
  export MOCK_LSBLK_OUTPUT='NAME="nvme0n1" SIZE="1T" TYPE="disk" MODEL="WD Black SN850"'
  run collect_disks
  assert_success
  assert_output_contains "nvme0n1"
}

@test "collect_disks: SIZE field extracted correctly" {
  export MOCK_LSBLK_OUTPUT='NAME="sda" SIZE="256G" TYPE="disk" MODEL="Crucial MX500"'
  run collect_disks
  assert_success
  assert_output_contains "256G"
}

@test "collect_disks: MODEL field extracted correctly" {
  export MOCK_LSBLK_OUTPUT='NAME="sda" SIZE="1T" TYPE="disk" MODEL="WD Blue 1TB"'
  run collect_disks
  assert_success
  assert_output_contains "WD Blue 1TB"
}

# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

@test "collect_disks: partition entries (type=part) are filtered out" {
  export MOCK_LSBLK_OUTPUT='NAME="sda" SIZE="500G" TYPE="disk" MODEL="Samsung SSD"
NAME="sda1" SIZE="512M" TYPE="part" MODEL=""'
  run collect_disks
  assert_success
  # Only the disk line should appear
  assert_output "sda|500G|Samsung SSD"
}

@test "collect_disks: rom entries are filtered out" {
  export MOCK_LSBLK_OUTPUT='NAME="sda" SIZE="500G" TYPE="disk" MODEL="Samsung SSD"
NAME="sr0" SIZE="4G" TYPE="rom" MODEL="VBOX CD-ROM"'
  run collect_disks
  assert_success
  assert_output "sda|500G|Samsung SSD"
}

# ---------------------------------------------------------------------------
# Multiple disks
# ---------------------------------------------------------------------------

@test "collect_disks: two disks produce two output lines" {
  export MOCK_LSBLK_OUTPUT='NAME="sda" SIZE="500G" TYPE="disk" MODEL="Samsung SSD"
NAME="sdb" SIZE="1T" TYPE="disk" MODEL="WD Black"'
  run collect_disks
  assert_success
  local line_count
  line_count="$(printf '%s\n' "$output" | wc -l)"
  assert_equal "2" "$line_count"
}

@test "collect_disks: second disk line is correct" {
  export MOCK_LSBLK_OUTPUT='NAME="sda" SIZE="500G" TYPE="disk" MODEL="Samsung SSD"
NAME="sdb" SIZE="1T" TYPE="disk" MODEL="WD Black"'
  run collect_disks
  assert_success
  assert_output_contains "sdb|1T|WD Black"
}

@test "collect_disks: mixed disks and partitions — only disks returned" {
  export MOCK_LSBLK_OUTPUT='NAME="sda" SIZE="500G" TYPE="disk" MODEL="Samsung SSD"
NAME="sda1" SIZE="512M" TYPE="part" MODEL=""
NAME="sda2" SIZE="499G" TYPE="part" MODEL=""
NAME="sdb" SIZE="2T" TYPE="disk" MODEL="Seagate Barracuda"'
  run collect_disks
  assert_success
  local line_count
  line_count="$(printf '%s\n' "$output" | wc -l)"
  assert_equal "2" "$line_count"
  assert_output_contains "sda|500G|Samsung SSD"
  assert_output_contains "sdb|2T|Seagate Barracuda"
}

# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

@test "collect_disks: empty lsblk output produces no output" {
  export MOCK_LSBLK_OUTPUT=""
  run collect_disks
  assert_success
  assert_output ""
}

@test "collect_disks: empty MODEL field produces trailing pipe separator" {
  export MOCK_LSBLK_OUTPUT='NAME="sda" SIZE="500G" TYPE="disk" MODEL=""'
  run collect_disks
  assert_success
  assert_output "sda|500G|"
}

@test "collect_disks: MODEL with spaces preserved" {
  export MOCK_LSBLK_OUTPUT='NAME="sda" SIZE="256G" TYPE="disk" MODEL="Kingston A2000 NVMe"'
  run collect_disks
  assert_success
  assert_output "sda|256G|Kingston A2000 NVMe"
}
