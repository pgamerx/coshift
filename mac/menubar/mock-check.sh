#!/bin/bash
# Mock-mode check: prints the menu-bar label and menu for several scenarios (normal and Switching state),
# renders the label to PNGs, then runs the settings self-test. Uses only temp files; never calls
# claude-switch and never touches real data.
# Usage: ./mock-check.sh [path-to-ClaudeSwitchMenu-binary]
set -euo pipefail
BIN="${1:-$HOME/Applications/Claude Switch Menu.app/Contents/MacOS/ClaudeSwitchMenu}"
T="$(mktemp -d /tmp/csm-mock.XXXXXX)"
export CLAUDE_SWITCH_BIN=/nonexistent   # makes any accidental claude-switch call fail loudly
ST_MAIN=$'Active profile : main\nClaude running : no'
ST_SECOND=$'Active profile : second\nClaude running : no'
LIST2=$'* main  (active, in live folder)\n  second'
LISTLONG=$'* a-very-long-real-profile-name-for-testing  (active, in live folder)\n  second'
ST_LONG=$'Active profile : a-very-long-real-profile-name-for-testing\nClaude running : no'
n=0
show() {  # title, names.json content ("" = no file), [status], [list]
  n=$((n+1)); echo; echo "######## $n. $1"
  mkdir -p "$T/$n"; export CLAUDE_SWITCH_MENU_NAMES="$T/$n/names.json"
  [ -n "$2" ] && printf '%s\n' "$2" > "$CLAUDE_SWITCH_MENU_NAMES"
  export MOCK_STATUS="${3:-$ST_MAIN}" MOCK_LIST="${4:-$LIST2}"
  "$BIN" --print-menu
  "$BIN" --render-png "$T/scenario-$n.png"
}
show "two profiles (no settings file: auto accents, real names)" ""
show "renamed profile (Work + briefcase + purple, Personal + green); second is active" \
  '{"main":{"name":"Work","icon":"💼","color":"purple"},"second":{"name":"Personal","color":"green"}}' "$ST_SECOND"
show "long names (exactly 20 chars kept; 21+ ignored; long real name truncated in the bar)" \
  '{"main":"Exactly twenty chars","second":"A very very long profile name that overflows"}'
show "long real profile name as active (bar truncates to 24 chars)" "" "$ST_LONG" "$LISTLONG"
show "name hidden (tinted sparkle only)" '{"main":{"name":"Work","color":"blue"},"@settings":{"showName":false}}'
show "broken settings file (real names, defaults)" '{ this is not json'
show "second instance running (switch closes it; Close Side by Side offered)" "" $'Active profile : main\nClaude running : yes\nSide-by-side   : an extra instance is running'
echo; echo "######## Switching state: the 'switching=true' block of every scenario above"
echo "PNG renders (light, dark, wallpaper-like; normal rows then Switching rows): $T/scenario-*.png"

echo; echo "######## settings self-test (validation, atomic write, 700/600 perms, broken file kept aside, accents, showName)"
export CLAUDE_SWITCH_MENU_NAMES="$T/selftest/names.json"
"$BIN" --selftest
echo; echo "temp files left in $T (safe to delete)"
