#!/usr/bin/env bash
# assert.bash — minimal Bats assertion helpers (no bats-assert dependency)
#
# Expects the standard Bats variables to be set:
#   $status   exit code captured by `run`
#   $output   stdout captured by `run`

assert_success() {
  if [[ "$status" -ne 0 ]]; then
    echo "# assert_success: expected exit 0, got $status" >&3
    echo "# output: $output" >&3
    return 1
  fi
}

assert_failure() {
  if [[ "$status" -eq 0 ]]; then
    echo "# assert_failure: expected non-zero exit, got 0" >&3
    echo "# output: $output" >&3
    return 1
  fi
}

# assert_output EXPECTED
# Exact match of the entire $output string.
assert_output() {
  local expected="$1"
  if [[ "$output" != "$expected" ]]; then
    echo "# assert_output mismatch" >&3
    echo "#   expected: $(printf '%q' "$expected")" >&3
    echo "#   actual:   $(printf '%q' "$output")" >&3
    return 1
  fi
}

# assert_output_contains SUBSTRING
# Checks that $output contains the given substring.
assert_output_contains() {
  local substring="$1"
  if [[ "$output" != *"$substring"* ]]; then
    echo "# assert_output_contains: substring not found" >&3
    echo "#   substring: $(printf '%q' "$substring")" >&3
    echo "#   output:    $(printf '%q' "$output")" >&3
    return 1
  fi
}

# assert_equal EXPECTED ACTUAL
assert_equal() {
  local expected="$1"
  local actual="$2"
  if [[ "$expected" != "$actual" ]]; then
    echo "# assert_equal mismatch" >&3
    echo "#   expected: $(printf '%q' "$expected")" >&3
    echo "#   actual:   $(printf '%q' "$actual")" >&3
    return 1
  fi
}
