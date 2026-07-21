#!/usr/bin/env bash
set -euo pipefail

exec /usr/local/bin/omarchy-boot-guardian check "$@"
