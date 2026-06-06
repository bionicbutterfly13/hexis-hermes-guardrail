#!/usr/bin/env bash
# Remove the installed Hexis plugin from the active Hermes profile.
#
#   uninstall.sh            remove plugin CODE, PRESERVE state/ (violation history)
#   uninstall.sh --purge    remove everything, including state/
#
# Also remember to remove `hexis` from plugins.enabled in ~/.hermes/config.yaml.
# Honors HERMES_HOME (defaults to ~/.hermes).
set -euo pipefail

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
DEST="$HERMES_HOME/plugins/hexis"

PURGE=0
if [ "${1:-}" = "--purge" ]; then
  PURGE=1
fi

# Safety: only ever operate on a path that ends in plugins/hexis.
case "$DEST" in
  */plugins/hexis) : ;;
  *) echo "Refusing to operate on unexpected path: $DEST" >&2; exit 1 ;;
esac

if [ ! -d "$DEST" ]; then
  echo "Nothing to uninstall: $DEST not present"
  exit 0
fi

if [ "$PURGE" -eq 1 ]; then
  rm -rf "$DEST"
  echo "Purged $DEST (including state/)."
else
  for f in __init__.py guards.py stuck.py violations.py plugin.yaml README.md SKILL.md .gitignore; do
    rm -f "$DEST/$f"
  done
  rm -rf "$DEST/__pycache__"
  echo "Removed plugin code from $DEST; preserved state/ (violation history)."
fi

echo "Remember to remove 'hexis' from plugins.enabled in $HERMES_HOME/config.yaml."
