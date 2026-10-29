#!/bin/bash
# Builds ~/Applications/Claude Switch Menu.app (menu bar item for claude-switch).
# Needs swiftc (Xcode CLT). No downloads. Safe to re-run.
# Launch at login is handled only by the menu's "Launch at Login" item. No LaunchAgent is written:
# launchd loads every plist in ~/Library/LaunchAgents at login, which started a second copy.
set -euo pipefail

SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
APP="$HOME/Applications/Claude Switch Menu.app"

command -v swiftc >/dev/null || { echo "swiftc not found (run: xcode-select --install)"; exit 1; }
[ -x "$HOME/bin/claude-switch" ] || echo "note: ~/bin/claude-switch not found; run ../install.sh first"

mkdir -p "$HOME/Applications"
if [ -e "$APP" ]; then
  mv "$APP" "$APP.old.$(date +%s)"   # keep the previous build rather than deleting it
fi
mkdir -p "$APP/Contents/MacOS"
cp "$SRC_DIR/Info.plist" "$APP/Contents/Info.plist"
swiftc -O -o "$APP/Contents/MacOS/ClaudeSwitchMenu" "$SRC_DIR/main.swift"
codesign --force --sign - "$APP" >/dev/null 2>&1 || echo "note: ad-hoc codesign failed (app should still run)"
echo "Built $APP"

cat <<MSG

Run now:  open "$APP"
At login: turn on "Launch at Login" in the menu.
MSG
