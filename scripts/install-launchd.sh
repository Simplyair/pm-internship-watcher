#!/bin/bash
# Install the watcher as a macOS background job (runs every 15 minutes).
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLIST="com.pmintern.watcher.plist"
TARGET="$HOME/Library/LaunchAgents/$PLIST"

mkdir -p "$HOME/Library/LaunchAgents" "$DIR/logs"

if [ ! -f "$DIR/.env" ]; then
  echo "error: $DIR/.env does not exist. Copy .env.example to .env and fill it in first." >&2
  exit 1
fi

cp "$DIR/scripts/$PLIST" "$TARGET"
launchctl bootout "gui/$(id -u)/com.pmintern.watcher" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$TARGET"
launchctl enable "gui/$(id -u)/com.pmintern.watcher"

echo "installed. it will scan every 15 minutes."
echo "  logs:      tail -f $DIR/logs/watcher.log"
echo "  stop:      launchctl bootout gui/$(id -u)/com.pmintern.watcher"
echo "  run now:   launchctl kickstart -k gui/$(id -u)/com.pmintern.watcher"
