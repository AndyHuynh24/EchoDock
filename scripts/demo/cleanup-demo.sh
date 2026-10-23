#!/bin/bash
# Moves the files created by setup-demo.sh to the Trash.
set -uo pipefail
HOME_DIR="${DEMO_HOME:-$HOME}"
MANIFEST="$HOME_DIR/.dock-demo-created"
[ -f "$MANIFEST" ] || { echo "Nothing to clean up."; exit 0; }
tail -r "$MANIFEST" | while read -r path; do
  [ -e "$path" ] || continue
  # only folders left empty
  if [ -d "$path" ] && [ -n "$(ls -A "$path" | grep -v '^\.DS_Store$')" ]; then echo "  kept ${path#$HOME_DIR/} (has other files in it)"; continue; fi
  osascript -e "tell application \"Finder\" to delete POSIX file \"$path\"" >/dev/null && echo "  - ${path#$HOME_DIR/}"
done
rm "$MANIFEST"
echo "Moved to the Trash. (Empty the Trash yourself if you're sure.)"
