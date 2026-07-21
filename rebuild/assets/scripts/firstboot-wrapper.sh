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

INSTALL_MARKER="${OMARCHY_INSTALL_MARKER:-/var/lib/omarchy/install/install-success.json}"
COMPLETION_MARKER="${OMARCHY_FIRSTBOOT_COMPLETION_MARKER:-/var/lib/omarchy/firstboot/completed.json}"
ATTEMPT_LOG="${OMARCHY_FIRSTBOOT_ATTEMPT_LOG:-/var/lib/omarchy/firstboot/attempt.log.jsonl}"
INSTALL_COMMAND="${OMARCHY_INSTALL_COMMAND:-curl -fsSL https://omarchy.org/install | bash}"
BOOTSTRAP_URL="${OMARCHY_BOOTSTRAP_URL:-https://omarchy.org/install}"
BOOTSTRAP_REPO="${OMARCHY_BOOTSTRAP_REPO:-lachthox/OmarchyInstaller}"
BOOTSTRAP_ROOT="${OMARCHY_BOOTSTRAP_ROOT:-/opt/omarchy-setup}"
EFI_MOUNT="${OMARCHY_EFI_MOUNT:-/boot/efi}"

exec "$PYTHON_BIN" -m installer.platforms.installed_system.firstboot \
  --bootstrap-url "$BOOTSTRAP_URL" \
  --bootstrap-repo "$BOOTSTRAP_REPO" \
  --bootstrap-root "$BOOTSTRAP_ROOT" \
  --install-marker "$INSTALL_MARKER" \
  --completion-marker "$COMPLETION_MARKER" \
  --attempt-log "$ATTEMPT_LOG" \
  --efi-mount "$EFI_MOUNT" \
  --command "$INSTALL_COMMAND"
