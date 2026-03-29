#!/usr/bin/env bats
# T01-string-001-pure-functions.bats
# Unit tests for pure string/logic functions:
#   normalize_hostname, validate_username, json_escape, cpu_ucode_pkg
#
# All tests are fast and isolated — no disk access, no root, no network.

setup() {
  load '../07-fixtures/assert'
  load '../07-fixtures/source-setup'
  local _test_dir="${BATS_TEST_DIRNAME:-$(dirname "$BATS_TEST_FILENAME")}"
  _FIXTURES_DIR="$(cd "${_test_dir}/../07-fixtures" && pwd)"
}

# ===========================================================================
# normalize_hostname
# ===========================================================================

@test "normalize_hostname: uppercase letters are lowercased" {
  run normalize_hostname "MyLaptop"
  assert_success
  assert_output "mylaptop"
}

@test "normalize_hostname: spaces are replaced with hyphens" {
  run normalize_hostname "my laptop"
  assert_success
  assert_output "my-laptop"
}

@test "normalize_hostname: dots are replaced with hyphens" {
  run normalize_hostname "my.laptop.local"
  assert_success
  assert_output "my-laptop-local"
}

@test "normalize_hostname: underscores are replaced with hyphens" {
  run normalize_hostname "my_host_name"
  assert_success
  assert_output "my-host-name"
}

@test "normalize_hostname: consecutive special chars collapse to single hyphen" {
  run normalize_hostname "my--laptop"
  assert_success
  assert_output "my-laptop"
}

@test "normalize_hostname: mixed special chars collapse to single hyphen" {
  run normalize_hostname "my._laptop"
  assert_success
  assert_output "my-laptop"
}

@test "normalize_hostname: leading hyphens are stripped" {
  run normalize_hostname "-myhost"
  assert_success
  assert_output "myhost"
}

@test "normalize_hostname: trailing hyphens are stripped" {
  run normalize_hostname "myhost-"
  assert_success
  assert_output "myhost"
}

@test "normalize_hostname: leading and trailing hyphens both stripped" {
  run normalize_hostname "-myhost-"
  assert_success
  assert_output "myhost"
}

@test "normalize_hostname: empty string returns omarchy-host" {
  run normalize_hostname ""
  assert_success
  assert_output "omarchy-host"
}

@test "normalize_hostname: all-hyphens input returns omarchy-host" {
  run normalize_hostname "---"
  assert_success
  assert_output "omarchy-host"
}

@test "normalize_hostname: all special chars produce omarchy-host" {
  run normalize_hostname "...!!!"
  assert_success
  assert_output "omarchy-host"
}

@test "normalize_hostname: valid hostname passes through unchanged" {
  run normalize_hostname "omarchy-thinkpad"
  assert_success
  assert_output "omarchy-thinkpad"
}

@test "normalize_hostname: digits are preserved" {
  run normalize_hostname "host42"
  assert_success
  assert_output "host42"
}

@test "normalize_hostname: uppercase + special chars combined" {
  run normalize_hostname "My Laptop 2024"
  assert_success
  assert_output "my-laptop-2024"
}

# ===========================================================================
# validate_username
# ===========================================================================

@test "validate_username: simple lowercase name is valid" {
  run validate_username "alice"
  assert_success
}

@test "validate_username: name with trailing digits is valid" {
  run validate_username "bob123"
  assert_success
}

@test "validate_username: name starting with underscore is valid" {
  run validate_username "_sysuser"
  assert_success
}

@test "validate_username: name containing hyphen is valid" {
  run validate_username "test-user"
  assert_success
}

@test "validate_username: single lowercase letter is valid" {
  run validate_username "a"
  assert_success
}

@test "validate_username: underscore and digits combination is valid" {
  run validate_username "user_123"
  assert_success
}

@test "validate_username: empty string is invalid" {
  run validate_username ""
  assert_failure
}

@test "validate_username: uppercase letters are invalid" {
  run validate_username "Alice"
  assert_failure
}

@test "validate_username: leading digit is invalid" {
  run validate_username "123user"
  assert_failure
}

@test "validate_username: space in name is invalid" {
  run validate_username "user name"
  assert_failure
}

@test "validate_username: at-sign is invalid" {
  run validate_username "user@host"
  assert_failure
}

@test "validate_username: leading hyphen is invalid" {
  run validate_username "-badstart"
  assert_failure
}

@test "validate_username: dot in name is invalid" {
  run validate_username "user.name"
  assert_failure
}

# ===========================================================================
# json_escape
# ===========================================================================

@test "json_escape: plain string is returned unchanged" {
  run json_escape "hello world"
  assert_success
  assert_output "hello world"
}

@test "json_escape: backslash is doubled" {
  run json_escape 'path\to\file'
  assert_success
  assert_output 'path\\to\\file'
}

@test "json_escape: double-quote is escaped with backslash" {
  run json_escape 'say "hello"'
  assert_success
  assert_output 'say \"hello\"'
}

@test "json_escape: newline is replaced with literal backslash-n" {
  run json_escape $'line1\nline2'
  assert_success
  assert_output 'line1\nline2'
}

@test "json_escape: carriage return is replaced with literal backslash-r" {
  run json_escape $'text\rmore'
  assert_success
  assert_output 'text\rmore'
}

@test "json_escape: tab is replaced with literal backslash-t" {
  run json_escape $'col1\tcol2'
  assert_success
  assert_output 'col1\tcol2'
}

@test "json_escape: multiple special chars handled in one call" {
  run json_escape $'a\\b"c\nd'
  assert_success
  assert_output 'a\\b\"c\nd'
}

@test "json_escape: empty string produces empty output" {
  run json_escape ""
  assert_success
  assert_output ""
}

# ===========================================================================
# cpu_ucode_pkg  (tested via redefined version using fixture files)
#
# The original function hardcodes /proc/cpuinfo; we replicate its exact
# logic with a configurable path controlled by CPUINFO_FIXTURE so we can
# run deterministic tests without depending on the host CPU.
# ===========================================================================

# Helper: same logic as cpu_ucode_pkg but reads from $CPUINFO_FIXTURE.
_cpu_ucode_from_fixture() {
  local vendor
  vendor="$(awk -F: '/vendor_id/{print $2; exit}' "${CPUINFO_FIXTURE}" | tr -d ' ')"
  case "$vendor" in
    GenuineIntel) echo "intel-ucode" ;;
    AuthenticAMD) echo "amd-ucode" ;;
    *) echo "" ;;
  esac
}

@test "cpu_ucode_pkg: GenuineIntel vendor returns intel-ucode" {
  export CPUINFO_FIXTURE="${_FIXTURES_DIR}/intel-cpuinfo.txt"
  run _cpu_ucode_from_fixture
  assert_success
  assert_output "intel-ucode"
}

@test "cpu_ucode_pkg: AuthenticAMD vendor returns amd-ucode" {
  export CPUINFO_FIXTURE="${_FIXTURES_DIR}/amd-cpuinfo.txt"
  run _cpu_ucode_from_fixture
  assert_success
  assert_output "amd-ucode"
}

@test "cpu_ucode_pkg: unknown vendor returns empty string" {
  export CPUINFO_FIXTURE="${_FIXTURES_DIR}/unknown-cpuinfo.txt"
  run _cpu_ucode_from_fixture
  assert_success
  assert_output ""
}

@test "cpu_ucode_pkg: real /proc/cpuinfo returns a known-good value or empty" {
  # Smoke test: the real function must not crash and must return one of the
  # three valid values regardless of the host machine's CPU.
  run cpu_ucode_pkg
  assert_success
  [[ "$output" == "intel-ucode" || "$output" == "amd-ucode" || "$output" == "" ]]
}
