#!/usr/bin/env bash
set -euo pipefail

OMARCHY_INSTALLER_ROOT="${OMARCHY_INSTALLER_ROOT:-/opt/omarchy-installer}"
PYTHON_BIN="${PYTHON_BIN:-/usr/bin/python}"

if [[ -d "$OMARCHY_INSTALLER_ROOT" ]]; then
  if [[ -n "${PYTHONPATH:-}" ]]; then
    export PYTHONPATH="$OMARCHY_INSTALLER_ROOT:$PYTHONPATH"
  else
    export PYTHONPATH="$OMARCHY_INSTALLER_ROOT"
  fi
fi

exec "$PYTHON_BIN" -m installer.platforms.installed_system.first_login "$@"
