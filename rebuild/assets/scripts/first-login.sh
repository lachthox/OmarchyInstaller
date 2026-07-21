#!/usr/bin/env bash
set -euo pipefail

OMARCHY_INSTALLER_ROOT="${OMARCHY_INSTALLER_ROOT:-/opt/omarchy-installer}"
# The target's system Python has none of pydantic/rich/textual/mcp; finalize
# builds a locked venv at /opt/omarchy-venv (mirroring the ISO's own
# provisioning) specifically so this wrapper can import the installer package.
PYTHON_BIN="${PYTHON_BIN:-/opt/omarchy-venv/bin/python}"

if [[ -d "$OMARCHY_INSTALLER_ROOT" ]]; then
  if [[ -n "${PYTHONPATH:-}" ]]; then
    export PYTHONPATH="$OMARCHY_INSTALLER_ROOT:$PYTHONPATH"
  else
    export PYTHONPATH="$OMARCHY_INSTALLER_ROOT"
  fi
fi

exec "$PYTHON_BIN" -m installer.platforms.installed_system.first_login "$@"
