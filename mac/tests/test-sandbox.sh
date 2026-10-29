#!/bin/bash
# Sandbox test suite for ../claude-switch. bash 3.2 compatible.
# Purpose: exercise claude-switch entirely inside a mktemp sandbox (never the real
# Claude data/app). Run: bash tests/test-sandbox.sh   Touches: only the mktemp dir.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$HERE/../claude-switch"

SB="$(mktemp -d "${TMPDIR:-/tmp}/claude-switch-test.XXXXXX")" || exit 2
SB="$(cd "$SB" && pwd -P)"
LIVE="$SB/App Support/Claude"
HOME_DIR="$SB/Profiles"

# ---- guard: refuse anything resolving to real locations ----
REAL_HOME="$(cd ~ && pwd -P)"
guard() {
  case "$1" in
    "$SB"/*) ;;
    *) echo "ABORT: $1 is outside sandbox"; exit 2 ;;
  esac
  case "$1" in
    "$REAL_HOME/Library"*|"$REAL_HOME/ClaudeProfiles"*) echo "ABORT: $1 is a real path"; exit 2 ;;
  esac
}
guard "$LIVE"; guard "$HOME_DIR"
mkdir -p "$LIVE" || exit 2

cleanup() {
  chflags -R nouchg "$SB" 2>/dev/null
  chmod -R u+rwx "$SB" 2>/dev/null
  case "$SB" in
    "${TMPDIR:-/tmp}"/claude-switch-test.*|/tmp/claude-switch-test.*|/var/folders/*/claude-switch-test.*|/private/var/folders/*/claude-switch-test.*)
      [ -d "$SB" ] && rm -rf "$SB" ;;
  esac
}
trap cleanup EXIT

sw() {  # run script in sandbox; sets OUT and RC
  guard "$LIVE"; guard "$HOME_DIR"
  OUT="$(CLAUDE_SWITCH_LIVE="$LIVE" CLAUDE_SWITCH_HOME="$HOME_DIR" \
    CLAUDE_SWITCH_APP_PATH=/nonexistent/FakeClaude.app CLAUDE_SWITCH_BUNDLE_ID=invalid.test.fake \
    CLAUDE_SWITCH_NO_LAUNCH=1 CLAUDE_SWITCH_NO_NOTIFY=1 CLAUDE_SWITCH_TIMEOUT=3 \
    bash "$SCRIPT" "$@" 2>&1)"
  RC=$?
}

FAILS=0
ok()   { echo "PASS: $1"; }
bad()  { echo "FAIL: $1"; [ -n "${2:-}" ] && echo "      $2"; FAILS=$((FAILS+1)); }
check() { # desc, command...
  local d="$1"; shift
  if "$@" >/dev/null 2>&1; then ok "$d"; else bad "$d"; fi
}
snapshot() {
  ( cd "$SB" && find . -print | sort && find . -exec stat -f '%N %p %z %m' {} + | sort \
    && find . -type f -exec shasum {} + | sort )
}
# content-only snapshot (no mtimes): refusals take/release the lock, bumping dir mtimes
csnap() { ( cd "$SB" && find . -print | sort && find . -type f -exec shasum {} + | sort ); }
nbackups() { ls -1d "$HOME_DIR"/_backup/Claude-* 2>/dev/null | wc -l | tr -d ' '; }
state() { head -n 1 "$HOME_DIR/.active" 2>/dev/null; }
acct() { cat "$LIVE/acct.txt" 2>/dev/null; }
marker() { head -n 1 "$LIVE/.claude-switch-profile" 2>/dev/null; }
entries() { find "$1" | wc -l | tr -d ' '; }

# ---- fake live data ----
mkdir -p "$LIVE/Local Storage/leveldb"
echo cookiedata > "$LIVE/Cookies"
echo x > "$LIVE/Local Storage/leveldb/x"
echo account1 > "$LIVE/acct.txt"

echo "== sandbox: $SB"

# 1. save main
# 1a: first-ever run, profiles home does not exist yet (real-world fresh install)
sw save main
if [ $RC = 0 ]; then ok "1a save on fresh install (no profiles home yet)"; else bad "1a save on fresh install (SCRIPT BUG: acquire_lock mkdir precedes ensure_home)" "rc=$RC $(echo "$OUT" | cut -c1-80)"; fi
# workaround so the remaining cases can run: pre-create the home dir
[ -d "$HOME_DIR" ] || { mkdir -p "$HOME_DIR"; chmod 700 "$HOME_DIR"; sw save main; }
if [ $RC = 0 ] && [ "$(state)" = main ] && [ "$(marker)" = main ] && [ ! -e "$HOME_DIR/main/data" ]; then ok "1 save main"; else bad "1 save main" "rc=$RC $OUT"; fi
PRE_COUNT="$(entries "$LIVE")"

# 2. dry-run new
snapshot > "$SB.before"
sw --dry-run new second; RC2=$RC
snapshot > "$SB.after"
if [ $RC2 = 0 ] && cmp -s "$SB.before" "$SB.after" && [ "$(nbackups)" = 0 ]; then ok "2 dry-run new is a no-op"; else bad "2 dry-run new is a no-op" "rc=$RC2"; fi
rm -f "$SB.before" "$SB.after"

# 3. new second
sw new second
B="$(ls -1d "$HOME_DIR"/_backup/Claude-* 2>/dev/null | head -n 1)"
if [ $RC = 0 ] && [ "$(nbackups)" = 1 ] && [ "$(entries "$B")" = "$PRE_COUNT" ]; then ok "3a backup exists, entry count $PRE_COUNT matches"; else bad "3a backup" "rc=$RC n=$(nbackups) $OUT"; fi
if [ "$(cat "$HOME_DIR/main/data/acct.txt" 2>/dev/null)" = account1 ] && [ "$(marker)" = second ] && [ ! -e "$LIVE/acct.txt" ] && [ "$(state)" = second ]; then ok "3b main stored, live fresh w/ marker second"; else bad "3b swap result" "$OUT"; fi
echo account2 > "$LIVE/acct.txt"

# 4. toggle x5
EXP="main account1 second account2 main account1 second account2 main account1"
set -- $EXP; i=1
while [ $i -le 5 ]; do
  e_state=$1; e_acct=$2; shift 2
  sw toggle
  if e_other=main; [ "$e_state" = main ]; then e_other=second; fi
  if [ $RC = 0 ] && [ "$(acct)" = "$e_acct" ] && [ "$(state)" = "$e_state" ] \
     && [ -d "$HOME_DIR/$e_other/data" ] && [ ! -e "$HOME_DIR/$e_state/data" ] && [ "$(nbackups)" = 1 ]; then
    ok "4.$i toggle -> $e_state ($e_acct), 1 backup"
  else bad "4.$i toggle -> $e_state" "rc=$RC acct=$(acct) state=$(state) nb=$(nbackups) $OUT"; fi
  i=$((i+1))
done
# now active=main, second/data holds account2

# 5. use active
snapshot > "$SB.before"
sw use main
snapshot > "$SB.after"
if [ $RC = 0 ] && echo "$OUT" | grep -qi "already active" && cmp -s "$SB.before" "$SB.after"; then ok "5 use <active> no-op"; else bad "5 use <active>" "rc=$RC $OUT"; fi

# 6. dry-run use / toggle
sw --dry-run use second; R1=$RC
sw --dry-run toggle; R2=$RC
snapshot > "$SB.after"
if [ $R1 = 0 ] && [ $R2 = 0 ] && cmp -s "$SB.before" "$SB.after"; then ok "6 dry-run use/toggle no-op"; else bad "6 dry-run use/toggle" "rc=$R1/$R2"; fi
rm -f "$SB.before" "$SB.after"

# 7. refusals
snapshot > "$SB.before"
sw use nonexistent
if [ $RC != 0 ] && echo "$OUT" | grep -qi "no stored data"; then ok "7a use nonexistent refused"; else bad "7a" "rc=$RC $OUT"; fi
sw save other
if [ $RC != 0 ] && echo "$OUT" | grep -qi "already belongs"; then ok "7b save other-name refused"; else bad "7b" "rc=$RC $OUT"; fi
snapshot > "$SB.after"
if cmp -s "$SB.before" "$SB.after"; then ok "7c refusals changed nothing"; else bad "7c refusals changed something"; fi
# marker mismatch
echo second > "$LIVE/.claude-switch-profile"
csnap > "$SB.before"
sw toggle; R1=$RC; O1="$OUT"
sw use second; R2=$RC
csnap > "$SB.after"
if [ $R1 != 0 ] && [ $R2 != 0 ] && echo "$O1" | grep -qi "mismatch" && cmp -s "$SB.before" "$SB.after"; then ok "7d marker mismatch refused, nothing moved"; else bad "7d marker mismatch" "rc=$R1/$R2 $O1"; fi
echo main > "$LIVE/.claude-switch-profile"
# pre-existing active data dir
mkdir "$HOME_DIR/main/data"
csnap > "$SB.before"
sw toggle
csnap > "$SB.after"
if [ $RC != 0 ] && echo "$OUT" | grep -qi "already exists" && cmp -s "$SB.before" "$SB.after"; then ok "7e pre-existing <active>/data refused"; else bad "7e" "rc=$RC $OUT"; fi
rmdir "$HOME_DIR/main/data"
rm -f "$SB.before" "$SB.after"

# 8. rollback on step-2 failure (target data immutable -> mv fails)
chflags uchg "$HOME_DIR/second/data"
sw toggle; R=$RC; O8="$OUT"
chflags nouchg "$HOME_DIR/second/data"
if [ $R != 0 ] && echo "$O8" | grep -qi "rolled back" && [ "$(acct)" = account1 ] && [ "$(marker)" = main ] \
   && [ "$(state)" = main ] && [ ! -e "$HOME_DIR/main/data" ] && [ -d "$HOME_DIR/second/data" ]; then
  ok "8 rollback restores original profile"
else bad "8 rollback" "rc=$R acct=$(acct) state=$(state) $O8"; fi
# lock released after failure?
[ ! -e "$HOME_DIR/.lock" ] && ok "8b lock released after failure" || bad "8b lock left behind"

# 9. permissions
PERM_OK=1
for p in "$HOME_DIR" "$HOME_DIR/main" "$HOME_DIR/second" "$HOME_DIR/_backup" "$B"; do
  m="$(stat -f %Lp "$p")"; [ "$m" = 700 ] || { PERM_OK=0; echo "      $p mode $m"; }
done
[ $PERM_OK = 1 ] && ok "9 profile dirs/_backup/backup mode 700" || bad "9 permissions"

# 10. restore-from-backup on a copy
mkdir -p "$SB/restore-test"
cp -cpR "$B" "$SB/restore-test/Claude"
if diff -rq "$B" "$SB/restore-test/Claude" >/dev/null && [ "$(cat "$SB/restore-test/Claude/acct.txt")" = account1 ]; then ok "10 restore copy identical, acct=account1"; else bad "10 restore copy"; fi

# 11. stale lock
mkdir "$HOME_DIR/.lock"; echo 99999999 > "$HOME_DIR/.lock/pid"
snapshot > "$SB.before"
sw toggle
snapshot > "$SB.after"
if [ $RC != 0 ] && echo "$OUT" | grep -qi "stale lock" && cmp -s "$SB.before" "$SB.after"; then ok "11 stale lock refused with message"; else bad "11 stale lock" "rc=$RC $OUT"; fi
rm -f "$HOME_DIR/.lock/pid"; rmdir "$HOME_DIR/.lock"
rm -f "$SB.before" "$SB.after"

# 12. side-by-side opens the inactive profile's stored data; the active one is refused
ACT="$(cat "$HOME_DIR/.active")"
if [ "$ACT" = main ]; then INACT=second; else INACT=main; fi
sw --dry-run side-by-side
if [ $RC = 0 ] && echo "$OUT" | grep -qF -- "--user-data-dir=$HOME_DIR/$INACT/data"; then ok "12a side-by-side defaults to stored '$INACT' data"; else bad "12a side-by-side default" "rc=$RC $OUT"; fi
sw --dry-run side-by-side "$ACT"
if [ $RC != 0 ] && echo "$OUT" | grep -q "already open in the main window"; then ok "12b side-by-side of active profile refused"; else bad "12b side-by-side active" "rc=$RC $OUT"; fi
sw --dry-run side-by-side third
if [ $RC = 0 ] && echo "$OUT" | grep -qF -- "--user-data-dir=$HOME_DIR/_sidebyside/third"; then ok "12c unknown profile falls back to fresh _sidebyside"; else bad "12c side-by-side fallback" "rc=$RC $OUT"; fi

echo "== failures: $FAILS"
[ $FAILS = 0 ] || exit 1
