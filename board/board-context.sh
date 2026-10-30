#!/bin/sh
# Claude Code PostToolUse hook for the Coshift board. After tool calls it reads how full this session's
# context window is (from the session transcript) and reports it to the board. At the board's stop line,
# and whenever the user sent a message from the board page, it passes the board's reply to Claude.
# Needs COSHIFT_URL and COSHIFT_TOKEN (cloud environment variables); does nothing without them.
# It sends the raw token count; the board turns it into a percentage using the account's context window
# (set in `coshift setup` or `coshift config context_window <tokens> <ACCOUNT>`). COSHIFT_CONTEXT_WINDOW here
# only decides how often to report (every ~2% of that size).
COSHIFT_URL=${COSHIFT_URL:-$TEAM_BOARD_URL} COSHIFT_TOKEN=${COSHIFT_TOKEN:-$TEAM_BOARD_TOKEN}  # names before the rename
[ -n "$COSHIFT_URL" ] && [ -n "$COSHIFT_TOKEN" ] || exit 0
export COSHIFT_URL COSHIFT_TOKEN
PY=$(command -v python3 || command -v python) || exit 0  # Windows often names it python
exec "$PY" -c '
import json, os, sys, tempfile, urllib.request
hook = json.load(sys.stdin)
window = int(os.environ.get("COSHIFT_CONTEXT_WINDOW") or 200000)
sid = hook.get("session_id") or ""
used = 0
try:
    with open(hook.get("transcript_path") or "", "rb") as f:
        f.seek(0, 2)
        f.seek(max(0, f.tell() - 500000))
        for line in f.read().splitlines():
            try:
                msg = json.loads(line).get("message")
            except ValueError:
                continue
            u = msg.get("usage") if isinstance(msg, dict) else None
            if u:  # the latest assistant turn: its input + cache + output is the current context size
                used = sum(int(u.get(k) or 0) for k in ("input_tokens", "cache_creation_input_tokens",
                                                       "cache_read_input_tokens", "output_tokens"))
except OSError:
    sys.exit(0)
if not used:
    sys.exit(0)
pct = min(100, used * 100 // window)
state = os.path.join(tempfile.gettempdir(), "board-ctx-" + sid)  # works on Windows too
try:
    last = int(open(state).read())
except (OSError, ValueError):
    last = -100
if abs(pct - last) < 2:  # report every 2 points, not after every tool call
    sys.exit(0)
try:
    open(state, "w").write(str(pct))
except OSError:
    pass
req = urllib.request.Request(
    os.environ["COSHIFT_URL"].rstrip("/") + "/api/call/report_context",
    data=json.dumps({"pct": pct, "tokens": used}).encode(), method="POST",
    headers={"Authorization": "Bearer " + os.environ["COSHIFT_TOKEN"], "Content-Type": "application/json",
             "X-Session": sid, "X-Repo": os.path.basename(hook.get("cwd") or "")})
try:
    text = urllib.request.urlopen(req, timeout=5).read().decode()
except Exception:
    sys.exit(0)  # never block the session because the board is unreachable
if text.startswith("CONTEXT LIMIT") or "FROM THE USER" in text:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                             "additionalContext": "COSHIFT: " + text}}))
'
