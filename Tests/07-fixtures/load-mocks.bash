#!/usr/bin/env bash
# load-mocks.bash — prepend mock-commands/ to PATH so stubs shadow real commands.
#
# Usage (in a Bats setup() function):
#   load '../07-fixtures/load-mocks'
#
# After loading, every command listed in mock-commands/ takes precedence over
# system binaries for the duration of the test.

if [[ -z "${BATS_TEST_DIRNAME:-}" ]]; then
  BATS_TEST_DIRNAME="$(dirname "$BATS_TEST_FILENAME")"
fi
_MOCK_COMMANDS_DIR="$(cd "${BATS_TEST_DIRNAME}/../07-fixtures/mock-commands" && pwd)"
export PATH="${_MOCK_COMMANDS_DIR}:${PATH}"
