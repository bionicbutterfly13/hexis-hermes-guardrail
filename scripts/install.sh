#!/usr/bin/env bash
# Install the Hexis guardrails plugin into the active Hermes profile.
#
# Copies the plugin code FROM this repo (the source of truth) into
# ~/.hermes/plugins/hexis/. Existing runtime state/ is preserved.
#
# Honors HERMES_HOME (defaults to ~/.hermes).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/hexis"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
DEST="$HERMES_HOME/plugins/hexis"

if [ ! -d "$SRC" ]; then
  echo "Plugin source not found: $SRC" >&2
  exit 1
fi

mkdir -p "$DEST"
# Copy only the plugin files — never touch DEST/state/ (runtime violation logs).
for f in __init__.py guards.py stuck.py violations.py plugin.yaml README.md SKILL.md; do
  cp "$SRC/$f" "$DEST/$f"
done

echo "Installed hexis plugin -> $DEST"
echo "(runtime state/ preserved if it already existed)"
cat <<'YAML'

Next: enable it in ~/.hermes/config.yaml

plugins:
  enabled:
    - hexis
  entries:
    hexis:
      guards:
        rm_rf: warn
        unscoped_search: warn
        credential_read: block
        force_push_main: block
        pkg_manager_mismatch: warn
      stuck_loop:
        enabled: true
        surface_to_model: false
YAML
