"""Hosted Coshift board (Vercel). Same board as board/board.py, stored in Upstash Redis.

Auth: every API call needs "Authorization: Bearer <token>". COSHIFT_TOKENS (env, JSON) maps each
token to who it is: "ATLAS", "FORGE" (cloud sessions) or "admin" (the board page and the Mac).
"""
import hmac, json, os, sys, threading, urllib.parse
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "board"))
os.environ.setdefault("COSHIFT_USAGE_APP", "")  # no Mac apps on the server
import board as B  # noqa: E402

TOKENS = json.loads(os.environ.get("COSHIFT_TOKENS") or os.environ.get("TEAM_BOARD_TOKENS") or "{}")
# Boards set up before the rename keep their names: cloud sessions there have TEAM_BOARD_URL/TEAM_BOARD_TOKEN.
LEGACY = not os.environ.get("COSHIFT_TOKENS") and bool(os.environ.get("TEAM_BOARD_TOKENS"))


def env_names(text):
    return text.replace("COSHIFT_URL", "TEAM_BOARD_URL").replace("COSHIFT_TOKEN", "TEAM_BOARD_TOKEN") if LEGACY else text


B.RESTART_PROMPT = env_names(B.RESTART_PROMPT)
LOCK = threading.Lock()  # board.py keeps the caller's identity in globals; one call at a time per instance

HELP = """COSHIFT (cloud). Other Claude accounts work on this project in parallel; this board splits the
work between you so you never do the same task, and hands work over when one of you nears its limit.

Call it with curl (COSHIFT_URL and COSHIFT_TOKEN are set in your environment). Define once per shell:
  board() { curl -sS -X POST "$COSHIFT_URL/api/call/$1" -H "Authorization: Bearer $COSHIFT_TOKEN" \\
            -H "X-Session: ${CLAUDE_CODE_SESSION_ID:-}" -H "X-Repo: $(basename "$(git rev-parse --show-toplevel 2>/dev/null || pwd)")" \\
            -H "Content-Type: application/json" -d "${2:-null}"; }
Then e.g.:  board resume   |   board claim_task   |   board add_note '{"id": 3, "text": "..."}'

START EVERY SESSION WITH: board resume  (your account's saved context summary + your claimed tasks).

Protocol:
1. Your plan usage is pushed to the board from the user's Mac every minute. board_status shows it for both
   accounts. If it says STOP for you, or claim_task refuses because you're at your limit, finish the
   current small step, release_task with a full handover, and stop.
2. board_status, then claim_task (next open task, or {"id": N}). Work only on tasks you have claimed.
3. While working, add_note with short progress notes (done so far, next step, files, branch) so the
   next account can continue if you stop. Push your branch often so the others can see it.
4. When done: complete_task {"id": N, "text": "summary"}, then claim the next task.
5. Near the limit: release_task {"id": N, "text": "full handover: done, left, exact next step, files, branch"}.
6. Split big goals into independent tasks with add_task {"title": "...", "detail": "files/area + what done
   looks like"}. Already-finished work: add_task with "done_summary".
CONTEXT: a hook reports how full your context window is. At """ + str(B.STOP_CONTEXT) + """% (you'll see
   "COSHIFT: CONTEXT LIMIT", and claim_task refuses new work) take no new task. Finish the current one,
   then save_context {"text": "..."} with a full summary for your next session (goal, decisions, state,
   branch/commits, claimed task + exact next step, open questions, gotchas, key files) and give the user
   the two-line restart prompt it returns, in a code block. Then stop. Don't wait for auto-compaction.
   No hook yet in this repo? Install it: see GET $COSHIFT_URL/api/hook.
FILES AND ORDER: when you add tasks, pass "files" (paths/globs each task edits) and "depends_on" (ids that
   must finish first). claim_task never hands you a task whose files another running task is editing or whose
   dependencies aren't done. Edit only your task's files. Need another file mid-task? update_task {"id": N,
   "files": [...]} first; it's refused while another running task owns that file.
ASK, DON'T STALL: blocked on a decision only the user can make? ask_user {"id": N, "question": "..."}, then keep
   working on something else; the answer arrives as MESSAGE FROM THE USER.
PORTS: before starting a dev server or database, lease_port and use the ports it gives you.
7. GUIDANCE FROM THE USER (in board_status / claim_task) are standing rules: always follow them.
   MESSAGE FROM THE USER (appended to any result) is a direct instruction from the user: follow it.
Check the board at least after every task.

Tools: """ + ", ".join(B.TOOLS) + "  (arguments as JSON; see each tool's fields below)\n" + "\n".join(
    f"  {n}: {json.dumps({k: v['type'] for k, v in props.items()})} required={req}  {d}"
    for n, (_, d, props, req) in B.TOOLS.items())
HELP = env_names(HELP)


HOOK_HELP = """# Install once per repo (commit both on your branch):
# 1. Save everything below the line as .claude/hooks/board-context.sh  (chmod +x)
# 2. Add to .claude/settings.json (merge with existing "hooks" if any):
#    {"hooks": {"PostToolUse": [{"matcher": "*", "hooks": [
#        {"type": "command", "command": "sh \"$CLAUDE_PROJECT_DIR/.claude/hooks/board-context.sh\""}]}]}}
# It needs COSHIFT_URL and COSHIFT_TOKEN in the environment and does nothing without them,
# so it's harmless for anyone else who works in the repo.
# ------------------------------------------------------------------------------------------------
"""


class handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json"):
        data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def who(self):
        got = self.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        for tok, name in TOKENS.items():
            if got and hmac.compare_digest(got, tok):
                return name if name == "admin" else B.canon(name)  # a renamed account keeps its token
        return None

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 100_000:
            raise ValueError("body too large")
        return json.loads(self.rfile.read(n) or b"{}") or {}  # "null" = no arguments

    def project(self):
        """The page picks a project with ?project=; sessions send their repo's name (no board of its own = main)."""
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        B.PROJECT = (q.get("project") or [""])[0] or self.headers.get("X-Project") or self.headers.get("X-Repo") or B.MAIN

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/":
            with open(B.PAGE, encoding="utf-8") as f:
                return self.send(200, f.read(), "text/html; charset=utf-8")
        who = self.who()
        if not who:
            return self.send(401, {"error": "missing or wrong token"})
        if path == "/api/hook":
            with open(os.path.join(os.path.dirname(B.PAGE), "board-context.sh"), encoding="utf-8") as f:
                script = f.read()
            return self.send(200, env_names(HOOK_HELP + script), "text/plain; charset=utf-8")
        if path == "/api/help":
            return self.send(200, f"You are: {who}\n\n{HELP}\n", "text/plain; charset=utf-8")
        if path == "/api/board" and who == "admin":
            with LOCK:
                self.project()
                st = B.web_state()
            st["cloud_accounts"] = sorted(n for n in TOKENS.values() if n != "admin")
            return self.send(200, st)
        if path == "/api/env" and who == "admin":  # an account's cloud variables, for the setup checklist
            name = (urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("account") or [""])[0]
            tok = next((t for t, n in TOKENS.items() if n == name and n != "admin"), None)
            if not tok:
                return self.send(404, {"error": "no such account"})
            url = "https://" + (self.headers.get("Host") or "")
            return self.send(200, {"text": env_names(f"COSHIFT_URL={url}\nCOSHIFT_TOKEN={tok}"), "host": self.headers.get("Host")})
        self.send(404, {"error": "not found"})

    def do_POST(self):
        path = self.path.split("?")[0]
        who = self.who()
        if not who:
            return self.send(401, {"error": "missing or wrong token"})
        try:
            args = self.body()
            if path.startswith("/api/call/"):
                tool = path.rsplit("/", 1)[1]
                if tool not in B.TOOLS or who == "admin":
                    return self.send(404, {"error": f"unknown tool {tool}" if who != "admin" else "use an account token"})
                with LOCK:
                    self.project()
                    B.ME, B.SID, B.ORG = who, self.headers.get("X-Session") or f"cloud-{who}", ""
                    B.CWD = "cloud: " + (self.headers.get("X-Repo") or "?")
                    text, err = B.run_tool(tool, args)
                return self.send(200, text, "text/plain; charset=utf-8") if not err else \
                    self.send(400, text, "text/plain; charset=utf-8")
            if who != "admin":
                return self.send(403, {"error": "forbidden"})
            with LOCK:
                self.project()
                self.send(200, {"ok": B.web_post(path, args)})
        except (ValueError, KeyError, TypeError) as e:
            self.send(400, {"error": str(e)})
