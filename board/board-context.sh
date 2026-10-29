#!/bin/sh
# Claude Code PostToolUse hook for the Baton board. After tool calls it reads how full this session's
# context window is (from the session transcript) and reports it to the board. At the board's stop line,
# and whenever the user sent a message from the board page, it passes the board's reply to Claude.
# Needs BATON_URL and BATON_TOKEN (cloud environment variables); does nothing without them.
# BATON_CONTEXT_WINDOW sets the window size in tokens (default 1000000).
[ -n "$BATON_URL" ] && [ -n "$BATON_TOKEN" ] || exit 0
exec python3 -c '
import json, os, sys, urllib.request
hook = json.load(sys.stdin)
window = int(os.environ.get("BATON_CONTEXT_WINDOW") or 1000000)
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
state = os.path.join(os.environ.get("TMPDIR") or "/tmp", "board-ctx-" + sid)
try:
    last = int(open(state).read())
except (OSError, ValueError):
    last = -100
if abs(pct - last) < 2:  # report every 2 points, not after every tool call
    sys.exit(0)
open(state, "w").write(str(pct))
req = urllib.request.Request(
    os.environ["BATON_URL"].rstrip("/") + "/api/call/report_context",
    data=json.dumps({"pct": pct, "tokens": used}).encode(), method="POST",
    headers={"Authorization": "Bearer " + os.environ["BATON_TOKEN"], "Content-Type": "application/json",
             "X-Session": sid, "X-Repo": os.path.basename(hook.get("cwd") or "")})
try:
    text = urllib.request.urlopen(req, timeout=5).read().decode()
except Exception:
    sys.exit(0)  # never block the session because the board is unreachable
if text.startswith("CONTEXT LIMIT") or "FROM THE USER" in text:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                             "additionalContext": "BATON: " + text}}))
'
