#!/usr/bin/env bash
set -euo pipefail

# The target's system Python has none of pydantic/rich/textual/mcp; finalize
# builds a locked venv at /opt/omarchy-venv (mirroring the ISO's own
# provisioning) specifically so this wrapper can import the installer package.
PYTHON_BIN="${PYTHON_BIN:-/opt/omarchy-venv/bin/python}"
RUNTIME_ROOT="${OMARCHY_RUNTIME_ROOT:-/opt/omarchy-installer}"
export PYTHONPATH="$RUNTIME_ROOT${PYTHONPATH:+:$PYTHONPATH}"
MODE="check"

script_name="$(basename "$0")"
case "$script_name" in
  *repair*) MODE="repair" ;;
  *check*) MODE="check" ;;
esac

if [[ $# -gt 0 ]]; then
  case "$1" in
    check|repair)
      MODE="$1"
      shift
      ;;
  esac
fi

if [[ "$MODE" == "check" ]]; then
  set -- --quiet "$@"
fi

exec "$PYTHON_BIN" -m installer.platforms.installed_system.boot_guardian "$MODE" "$@"
