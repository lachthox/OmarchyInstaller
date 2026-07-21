#!/usr/bin/env bash
set -euo pipefail

OMARCHY_SETUP_ROOT="${OMARCHY_SETUP_ROOT:-/opt/omarchy-installer}"
PYTHON_BIN="${PYTHON_BIN:-/usr/bin/python}"

if [[ -d "$OMARCHY_SETUP_ROOT" ]]; then
  if [[ -n "${PYTHONPATH:-}" ]]; then
    export PYTHONPATH="$OMARCHY_SETUP_ROOT:$PYTHONPATH"
  else
    export PYTHONPATH="$OMARCHY_SETUP_ROOT"
  fi
fi

exec "$PYTHON_BIN" -m installer.platforms.installed_system.first_login "$@"
