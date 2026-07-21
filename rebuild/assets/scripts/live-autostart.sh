#!/usr/bin/env bash
set -Eeuo pipefail

PYTHON="/opt/omarchy-venv/bin/python"

if [[ ! -x "$PYTHON" ]]; then
  echo "live-autostart: missing installer virtual environment: $PYTHON" >&2
  exit 2
fi

exec "$PYTHON" -m installer.main "$@"
