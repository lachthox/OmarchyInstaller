#!/usr/bin/env bash
set -Eeuo pipefail

ENTRYPOINT="/opt/omarchy-installer/main.py"
SETUP_ENTRYPOINT="/opt/omarchy-setup/main.py"

if [[ ! -f "$ENTRYPOINT" && -f "$SETUP_ENTRYPOINT" ]]; then
  mkdir -p /opt/omarchy-installer
  ln -sfn "$SETUP_ENTRYPOINT" "$ENTRYPOINT"
fi

if [[ ! -f "$ENTRYPOINT" ]]; then
  echo "live-autostart: missing entrypoint $ENTRYPOINT" >&2
  exit 2
fi

exec python3 "$ENTRYPOINT" "$@"
