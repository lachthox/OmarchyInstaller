#!/usr/bin/env bash
set -euo pipefail

case "${1:-}" in
  omarchy-complete|boot-policy-complete|overall-setup-complete) stage="$1" ;;
  *) printf 'Unsupported Omarchy stage marker\n' >&2; exit 2 ;;
esac

directory=/var/lib/omarchy/install
install -d -m 0700 "$directory"
temporary="$(mktemp "$directory/.${stage}.XXXXXX")"
trap 'rm -f "$temporary"' EXIT
printf '{"schema_version":"1.0.0","stage":"%s","status":"complete","completed_at_utc":"%s"}\n' \
  "$stage" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >"$temporary"
chmod 0600 "$temporary"
mv -f "$temporary" "$directory/$stage.json"
trap - EXIT

if [[ -f "$directory/omarchy-complete.json" && -f "$directory/boot-policy-complete.json" \
  && ! -f "$directory/overall-setup-complete.json" ]]; then
  exec "$0" overall-setup-complete
fi
