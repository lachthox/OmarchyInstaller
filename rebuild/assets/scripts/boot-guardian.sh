#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-python3}"
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
