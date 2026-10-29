#!/usr/bin/env python3
"""Two fake accounts drive board/board.py over MCP stdio against a temp board. Run: python3 tests/test-board.py"""
import json, os, subprocess, sys, tempfile, threading

BOARD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "board", "board.py")
HOME = tempfile.mkdtemp(prefix="coshift-test.")
os.environ["COSHIFT_USAGE_APP"] = ""  # never read the real Claude Usage app in tests
FAILS = 0


class Account:
    def __init__(self, email):
        env = dict(os.environ, COSHIFT_HOME=HOME, CLAUDE_CODE_USER_EMAIL=email, CLAUDE_CODE_SESSION_ID="s-" + email)
        env.pop("COSHIFT_AS", None)
        env.pop("CLAUDE_CODE_ORGANIZATION_UUID", None)  # else real usage on this Mac counts as a report
        self.p = subprocess.Popen([sys.executable, BOARD, "serve"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  text=True, env=env)
        self.n = 0
        init = self.rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})
        assert "Shared task board" in init["instructions"]
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")

    def rpc(self, method, params=None):
        self.n += 1
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params or {}}) + "\n")
        self.p.stdin.flush()
        r = json.loads(self.p.stdout.readline())
        assert r["id"] == self.n
        return r["result"]

    def call(self, name, **args):
        r = self.rpc("tools/call", {"name": name, "arguments": args})
        return r["content"][0]["text"], r["isError"]


def check(desc, cond, detail=""):
    global FAILS
    print(("PASS: " if cond else "FAIL: ") + desc + ("" if cond else f"\n      {detail}"))
    FAILS += 0 if cond else 1


a, b = Account("a@x.com"), Account("b@x.com")
check("tools listed", {t["name"] for t in a.rpc("tools/list")["tools"]} >=
      {"board_status", "report_usage", "add_task", "claim_task", "add_note", "complete_task", "release_task"})

a.call("add_task", title="API routes", detail="build /api/leads")
a.call("add_task", title="UI table")
a.call("add_task", title="Tests")

txt, err = a.call("claim_task")
check("claim refused without a usage report", err and "report your usage" in txt, txt)

a.call("report_usage", five_hour_pct=40, weekly_pct=30, five_hour_resets_in="2h")
b.call("report_usage", five_hour_pct=10, weekly_pct=20)
ta, _ = a.call("claim_task")
tb, _ = b.call("claim_task")
check("A gets #1, B gets #2 (no overlap)", "#1" in ta and "#2" in tb, ta + " | " + tb)

txt, err = b.call("claim_task", id=1)
check("B can't take A's active task", err and "claimed by a@x.com" in txt, txt)

a.call("add_note", id=1, text="routes done, validation next")
txt, _ = a.call("report_usage", five_hour_pct=88, weekly_pct=31)
check("report over 5h threshold says STOP", "STOP" in txt and "b@x.com" in txt, txt)
txt, err = a.call("claim_task", id=3)
check("A at limit can't claim new work", err and "at your limit" in txt, txt)

txt, _ = a.call("release_task", id=1, text="next: add zod validation in routes/leads.ts, branch acct-a")
b.call("complete_task", id=2, text="table built")
txt, _ = b.call("claim_task")
check("B picks up released #1 with the handover", "#1" in txt and "zod validation" in txt and "routes done" in txt, txt)

# A hits the hard limit mid-task without releasing: B can take over because A reported over the limit
a.call("report_usage", five_hour_pct=10, weekly_pct=31)
a.call("claim_task", id=3)
a.call("report_usage", five_hour_pct=100, weekly_pct=31)
txt, err = b.call("claim_task", id=3)
check("B takes over #3 from A at limit", not err and "taken over" in txt, txt)

txt, err = a.call("complete_task", id=3, text="x")
check("A can't complete a task it no longer owns", err, txt)

# concurrent writes from both accounts don't lose tasks
def spam(acc, tag):
    for i in range(25):
        acc.call("add_task", title=f"{tag}{i}")
ths = [threading.Thread(target=spam, args=(x, x is a and "a" or "b")) for x in (a, b)]
[t.start() for t in ths]; [t.join() for t in ths]
board = json.load(open(os.path.join(HOME, "board.json")))
check("50 concurrent adds, no lost writes", len(board["tasks"]) == 53 and board["next_id"] == 54, len(board["tasks"]))

status, _ = b.call("board_status")
check("status shows both accounts and STOP flag", "a@x.com" in status and "b@x.com" in status and "STOP" in status, status)

out = subprocess.run([sys.executable, BOARD, "show"], env=dict(os.environ, COSHIFT_HOME=HOME),
                     capture_output=True, text=True).stdout
check("CLI show works", "Claimed" in out and "Open" in out, out)

# ---- web page API ----
import socket, time, urllib.request, urllib.error
with socket.socket() as s:
    s.bind(("127.0.0.1", 0)); PORT = s.getsockname()[1]
web = subprocess.Popen([sys.executable, BOARD, "web", str(PORT)],
                       env=dict(os.environ, COSHIFT_HOME=HOME, CLAUDE_SWITCH_BIN="/nonexistent"))
for _ in range(50):
    try:
        socket.create_connection(("127.0.0.1", PORT), 0.2).close(); break
    except OSError:
        time.sleep(0.1)


def http(path, body=None, headers=None):
    h = {"Content-Type": "application/json"} if body is not None else {}
    h.update(headers or {})
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}{path}", method="POST" if body is not None else "GET",
                                 data=json.dumps(body).encode() if body is not None else None, headers=h)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


code, page = http("/")
check("web page served", code == 200 and "Coshift" in page, code)
code, st = http("/api/board")
st = json.loads(st)
check("board API lists both sessions", {x["account"] for x in st["sessions"]} == {"a@x.com", "b@x.com"}, st["sessions"])
check("session shows its claimed task", any(x["task"].startswith("#") for x in st["sessions"]), st["sessions"])
code, _ = http("/api/task", {"title": "from the page"})
check("add task from page", code == 200 and json.loads(http("/api/board")[1])["tasks"][-1]["created_by"] == "you")
code, _ = http("/api/task/4/cancel", {})
txt, err = b.call("claim_task", id=4)
check("cancelled task can't be claimed", err and "cancelled" in txt, txt)
http("/api/message", {"to": "b@x.com", "text": "focus on the login bug"})
txt, _ = a.call("board_status")
check("message to B not shown to A", "login bug" not in txt, txt)
txt, _ = b.call("board_status")
check("message delivered to B once", "MESSAGE FROM THE USER" in txt and "login bug" in txt, txt)
txt, _ = b.call("board_status")
check("message not repeated", "login bug" not in txt, txt)
code, _ = http("/api/board", headers={"Host": "evil.example:80"})
check("wrong Host rejected (DNS rebinding)", code == 403, code)
code, _ = http("/api/message", {"text": "x"}, headers={"Origin": "https://evil.example"})
check("other website's POST rejected", code == 403, code)
req = urllib.request.Request(f"http://127.0.0.1:{PORT}/api/message", data=b"text=x", method="POST",
                             headers={"Content-Type": "application/x-www-form-urlencoded"})
try:
    urllib.request.urlopen(req); form_code = 200
except urllib.error.HTTPError as e:
    form_code = e.code
check("non-JSON POST rejected", form_code == 403, form_code)

# ---- guidance: standing rules, for both or one account ----
http("/api/guidance", {"to": "all", "text": "use pnpm"})
http("/api/guidance", {"to": "a@x.com", "text": "only touch the api folder"})
txt, _ = b.call("board_status")
check("B sees shared guidance, not A's", "use pnpm" in txt and "api folder" not in txt, txt)
check("new guidance also flagged once as NEW", "NEW GUIDANCE" in txt, txt)
txt, _ = b.call("board_status")
check("guidance stays on later checks, NEW flag only once", "use pnpm" in txt and "NEW GUIDANCE" not in txt, txt)
a.call("report_usage", five_hour_pct=10, weekly_pct=31)
http("/api/task", {"title": "for A"})
txt, _ = a.call("claim_task")
check("A's claim shows both guidance lines", "use pnpm" in txt and "api folder" in txt, txt)
gid = json.loads(http("/api/board")[1])["guidance"][0]["id"]
http(f"/api/guidance/{gid}/remove", {})
txt, _ = b.call("board_status")
check("removed guidance no longer shown", "use pnpm" not in txt, txt)

# ---- merging an existing task list: done_summary, and Bash access for older sessions ----
txt, _ = a.call("add_task", title="old work", done_summary="built the schema")
check("add_task with done_summary records it as done", "(done)" in txt, txt)
r = subprocess.run([sys.executable, BOARD, "call", "add_task", '{"title": "from bash"}'], capture_output=True, text=True,
                   env=dict(os.environ, COSHIFT_HOME=HOME, CLAUDE_CODE_USER_EMAIL="b@x.com", CLAUDE_CODE_SESSION_ID="s-bash"))
st = json.loads(http("/api/board")[1])
check("board.py call works as the session's account", r.returncode == 0 and st["tasks"][-1]["created_by"] == "b@x.com"
      and any(x["id"] == "s-bash" for x in st["sessions"]), r.stdout + r.stderr)
r = subprocess.run([sys.executable, BOARD, "call", "help"], capture_output=True, text=True, env=dict(os.environ, COSHIFT_HOME=HOME))
check("call help lists the tools", "claim_task" in r.stdout and "done_summary" in r.stdout, r.stdout[:200])
web.terminate(); web.wait()

# ---- accounts come from the app's own usage files too, merged with session reports by org ----
sys.path.insert(0, os.path.dirname(BOARD))
import importlib
fake = tempfile.mkdtemp(prefix="coshift-apps.")
for folder, org, fh, sd, t in (("live", "org-a", 5, 20, 1000), ("Profiles/second/data", "org-b", 0, 86, time.time())):
    os.makedirs(os.path.join(fake, folder))
    json.dump({"version": 2, "samples": [{"t": t * 1000, "org": org, "u": {"fh": fh, "sd": sd}}]},
              open(os.path.join(fake, folder, "plan-usage-history.json"), "w"))
open(os.path.join(fake, "Profiles", ".active"), "w").write("main")
json.dump({"main": {"name": "Work"}}, open(os.path.join(fake, "names.json"), "w"))
os.environ.update(CLAUDE_SWITCH_LIVE=os.path.join(fake, "live"), CLAUDE_SWITCH_HOME=os.path.join(fake, "Profiles"),
                  CLAUDE_SWITCH_MENU_NAMES=os.path.join(fake, "names.json"), COSHIFT_HOME=HOME)
bmod = importlib.import_module("board")
cards = bmod.accounts_view({})
check("both accounts shown with no session reports", sorted(c["profile"] for c in cards) == ["Work", "second"], cards)
cards = bmod.accounts_view({"a@x.com": {"five_hour_pct": 50, "weekly_pct": 33, "org": "org-a", "at": time.time()}})
work = next(c for c in cards if c["profile"] == "Work")
check("newer session report replaces the app's sample, same card", len(cards) == 2 and work["email"] == "a@x.com"
      and work["five_hour_pct"] == 50 and work["source"] == "session", cards)
second = next(c for c in cards if c["profile"] == "second")
check("app sample under the weekly line (86 < 90) is not flagged", second["stop"] == "" and second["weekly_pct"] == 86, second)

# ---- Claude Usage app: live numbers win when newer; secret fields are never returned ----
import plistlib, types
fake_profiles = [{"name": "Forge (Claude)", "organizationId": "org-b", "sessionKey": "SECRET",
                  "claudeUsage": {"lastUpdated": time.time() - bmod.APPLE_EPOCH, "sessionPercentage": 91,
                                  "weeklyPercentage": 87, "sessionResetTime": time.time() + 3600 - bmod.APPLE_EPOCH}}]
blob = plistlib.dumps({"profiles_v3": json.dumps(fake_profiles).encode()})
real_run = bmod.subprocess.run
bmod.subprocess.run = lambda *a, **k: types.SimpleNamespace(stdout=blob, returncode=0)
bmod.USAGE_APP = "fake.domain"
live = bmod.usage_app_usage()
check("usage app parsed by org, no secrets", live["org-b"]["five_hour_pct"] == 91 and "SECRET" not in json.dumps(live), live)
cards = bmod.accounts_view({})
second = next(c for c in cards if c["profile"] == "second")
check("live usage-app numbers beat the older app sample, menu name kept", second["source"] == "usage-app"
      and second["five_hour_pct"] == 91 and second["stop"].startswith("5-hour"), second)
bmod.subprocess.run, bmod.USAGE_APP = real_run, ""

for x in (a, b):
    x.p.stdin.close(); x.p.wait()
print(f"== failures: {FAILS}  (board at {HOME})")
sys.exit(1 if FAILS else 0)
