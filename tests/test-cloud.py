#!/usr/bin/env python3
"""Runs the hosted API (api/index.py) locally on a temp board and drives it like two cloud sessions,
including the real context hook (board/board-context.sh). Run: python3 tests/test-cloud.py"""
import importlib.util, json, os, subprocess, sys, tempfile, threading, urllib.error, urllib.request
from http.server import ThreadingHTTPServer

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
TMP = tempfile.mkdtemp(prefix="team-cloud-test.")
for k in ("KV_REST_API_URL", "UPSTASH_REDIS_REST_URL", "CLAUDE_CODE_ORGANIZATION_UUID"):
    os.environ.pop(k, None)
os.environ.update(COSHIFT_HOME=TMP, COSHIFT_USAGE_APP="", COSHIFT_REQUIRE_USAGE="0",
                  COSHIFT_TOKENS=json.dumps({"tA": "ATLAS", "tF": "FORGE", "tX": "admin"}))
spec = importlib.util.spec_from_file_location("api_index", os.path.join(ROOT, "api", "index.py"))
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)
srv = ThreadingHTTPServer(("127.0.0.1", 0), api.handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
URL = f"http://127.0.0.1:{srv.server_port}"
FAILS = 0


def check(desc, cond, detail=""):
    global FAILS
    print(("PASS: " if cond else "FAIL: ") + desc + ("" if cond else f"\n      {str(detail)[:400]}"))
    FAILS += 0 if cond else 1


def call(tok, tool, body=None, sid="s1"):
    req = urllib.request.Request(f"{URL}/api/call/{tool}", data=json.dumps(body or {}).encode(), method="POST",
                                 headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json",
                                          "X-Session": sid})
    try:
        with urllib.request.urlopen(req) as r:
            return r.read().decode()
    except urllib.error.HTTPError as e:
        return "ERR " + e.read().decode()


def get(path, tok):
    req = urllib.request.Request(URL + path, headers={"Authorization": "Bearer " + tok})
    with urllib.request.urlopen(req) as r:
        return r.read().decode()


help_text = get("/api/help", "tA")
check("help says to start with resume, as ATLAS", help_text.startswith("You are: ATLAS") and "board resume" in help_text)
check("hook script served with install steps", "PostToolUse" in get("/api/hook", "tF") and "transcript_path" in get("/api/hook", "tF"))

raw = urllib.request.Request(f"{URL}/api/call/board_status", data=b"null", method="POST",
                             headers={"Authorization": "Bearer tA", "Content-Type": "application/json"})
check("no-argument call (body 'null', as the board() function sends) works",
      urllib.request.urlopen(raw).read().decode().startswith("You are: ATLAS"))
call("tA", "add_task", {"title": "task one"})
call("tA", "add_task", {"title": "task two"})
check("ATLAS claims #1", "#1" in call("tA", "claim_task"))

# the real hook, on a fake transcript at 72% of the default 200K window
transcript = os.path.join(TMP, "t.jsonl")
with open(transcript, "w") as f:
    f.write(json.dumps({"type": "user", "message": {"role": "user", "content": "hi"}}) + "\n")
    f.write(json.dumps({"type": "assistant", "message": {"usage": {"input_tokens": 4000, "cache_read_input_tokens":
                                                                   138000, "output_tokens": 2000}}}) + "\n")
hook_in = json.dumps({"session_id": "s1", "transcript_path": transcript, "cwd": "/repo/unified-crm"})
env = dict(os.environ, COSHIFT_URL=URL, COSHIFT_TOKEN="tA", TMPDIR=TMP)
r = subprocess.run(["sh", os.path.join(ROOT, "board", "board-context.sh")], input=hook_in, capture_output=True,
                   text=True, env=env)
out = json.loads(r.stdout or "{}")
ctx = out.get("hookSpecificOutput", {}).get("additionalContext", "")
check("hook reports 72% and tells Claude to wrap up", "CONTEXT LIMIT" in ctx and "72%" in ctx and "board resume" in ctx,
      r.stdout + r.stderr)
r2 = subprocess.run(["sh", os.path.join(ROOT, "board", "board-context.sh")], input=hook_in, capture_output=True,
                    text=True, env=env)
check("hook stays quiet when context hasn't moved", r2.stdout.strip() == "", r2.stdout)
r3 = subprocess.run(["sh", os.path.join(ROOT, "board", "board-context.sh")], input=hook_in, capture_output=True,
                    text=True, env={k: v for k, v in env.items() if k != "COSHIFT_URL"})
check("hook does nothing without board env vars", r3.returncode == 0 and r3.stdout == "")
r4 = subprocess.run(["sh", os.path.join(ROOT, "board", "board-context.sh")], capture_output=True, text=True,
                    input=hook_in.replace('"s1"', '"s1m"'), env=dict(env, COSHIFT_CONTEXT_WINDOW="1000000"))
s1m = next(x for x in json.loads(get("/api/board", "tX"))["sessions"] if x["id"] == "s1m")
check("COSHIFT_CONTEXT_WINDOW=1000000: same tokens read 14%, no stop", r4.stdout == "" and s1m["context_pct"] == 14, s1m)

state = json.loads(get("/api/board", "tX"))
sess = next(x for x in state["sessions"] if x["id"] == "s1")
check("page shows the session's context", sess["context_pct"] == 72 and state["stop_context"] == 70, sess)

check("over the line: no new task", "ERR" in call("tA", "claim_task", {"id": 2}) and
      "context is at 72%" in call("tA", "claim_task", {"id": 2}))
check("over the line: own task still claimable", "You own task #1" in call("tA", "claim_task"))
check("too-short summary refused", "too short" in call("tA", "save_context", {"text": "did stuff"}))
summary = "GOAL: finish the leads module. " * 10 + "NEXT: add validation in routes/leads.ts on branch claude."
saved = call("tA", "save_context", {"text": summary})
check("save_context returns the two-line restart prompt", "Context saved for ATLAS" in saved and "board resume" in saved)

res = call("tA", "resume", sid="s2")
check("new ATLAS session resumes with summary and its task", "SAVED CONTEXT" in res and "routes/leads.ts" in res
      and "YOUR CLAIMED TASK #1" in res, res)
check("new session can claim new work (fresh context)", "#2" in call("tA", "claim_task", {"id": 2}, sid="s2"))
check("FORGE doesn't get ATLAS's summary", "No saved context" in call("tF", "resume", sid="f1"))
state = json.loads(get("/api/board", "tX"))
check("page gets ATLAS's latest summary", state["contexts"]["ATLAS"]["text"] == summary)

# a session that first called without its id (old instructions), then with it, is one row
call("tF", "add_task", {"title": "forge task"}, sid="")
call("tF", "claim_task", sid="")
call("tF", "board_status", sid="real-forge")
rows = {x["id"]: x for x in json.loads(get("/api/board", "tX"))["sessions"]}
check("placeholder row merged into the real session, task moved with it",
      "cloud-FORGE" not in rows and rows["real-forge"]["task"].endswith("forge task"), list(rows))

srv.shutdown()
print(f"== failures: {FAILS}")
sys.exit(1 if FAILS else 0)
