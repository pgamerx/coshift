#!/bin/bash
# Installs claude-switch to ~/bin, puts ~/bin on PATH (zsh), and builds a
# one-click "Claude Switch.app" (runs `claude-switch toggle`) in ~/Applications.
# Safe to re-run.
set -euo pipefail

SRC_DIR="$(cd "$(dirname "$0")" && pwd)"
BIN="$HOME/bin"
APP="$HOME/Applications/Claude Switch.app"

mkdir -p "$BIN"
install -m 755 "$SRC_DIR/claude-switch" "$BIN/claude-switch"
echo "Installed $BIN/claude-switch"

LINE='export PATH="$HOME/bin:$PATH"'
if ! grep -qsF "$LINE" "$HOME/.zshrc"; then
  printf '\n# claude-switch\n%s\n' "$LINE" >> "$HOME/.zshrc"
  echo "Added ~/bin to PATH in ~/.zshrc (open a new terminal tab)"
fi

mkdir -p "$HOME/Applications"
TMP_SCPT="$(mktemp -t claude-switch).applescript"
cat > "$TMP_SCPT" <<'EOF'
try
	do shell script "\"$HOME/bin/claude-switch\" toggle 2>&1"
on error errMsg
	display notification errMsg with title "Claude Switch failed"
end try
EOF
if [ -e "$APP" ]; then
  mv "$APP" "$APP.old.$(date +%s)"   # keep the previous build rather than deleting it
fi
osacompile -o "$APP" "$TMP_SCPT"
rm -f "$TMP_SCPT"
echo "Built $APP"
