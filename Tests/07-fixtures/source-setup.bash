#!/usr/bin/env bash
# source-setup.bash — source setup.sh helper functions without running main.
#
# Usage (in a Bats setup() function):
#   load '../07-fixtures/source-setup'
#
# Technique: pipe setup.sh through grep to drop the unconditional `main "$@"`
# invocation at the bottom, then source the result.  All function definitions
# become available in the test's shell without starting the installer flow.
#
# Side-effects cleaned up here:
#   - The `trap cleanup_config_path EXIT` registered by setup.sh is cleared so
#     it doesn't interfere with Bats's own EXIT handling.
#   - USE_TUI is forced to 0 so tests always exercise the non-whiptail paths.
#   - CONFIG_PATH is reset to "" so prepare_config_path creates a fresh file.

# BATS_TEST_DIRNAME is set by Bats 1.5+; fall back to deriving from BATS_TEST_FILENAME.
if [[ -z "${BATS_TEST_DIRNAME:-}" ]]; then
  BATS_TEST_DIRNAME="$(dirname "$BATS_TEST_FILENAME")"
fi
_SETUP_SH="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)/setup.sh"

if [[ ! -f "$_SETUP_SH" ]]; then
  echo "source-setup.bash: setup.sh not found at $_SETUP_SH" >&2
  return 1
fi

# shellcheck disable=SC1090
source <(grep -v '^main "\$@"$' "$_SETUP_SH")

# Clear the EXIT trap setup.sh registered; Bats manages its own traps.
trap - EXIT

# Reset state variables to known-good defaults for testing.
USE_TUI=0
CONFIG_PATH=""
