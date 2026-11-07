#!/usr/bin/env python3
"""0.2 board features, driven in-process as two accounts: file ownership, dependencies, ask_user + answer,
board settings, port leases, stale flags. Run: python3 tests/test-features.py"""
import json, os, sys, tempfile, time

HOME = tempfile.mkdtemp(prefix="coshift-features.")
for k in ("KV_REST_API_URL", "UPSTASH_REDIS_REST_URL", "CLAUDE_CODE_ORGANIZATION_UUID", "COSHIFT_AS"):
    if not os.environ.get("COSHIFT_TEST_REDIS"):  # test-redis.py runs this against a fake Redis
        os.environ.pop(k, None)
os.environ.update(COSHIFT_HOME=HOME, COSHIFT_USAGE_APP="", CLAUDE_SWITCH_LIVE=os.path.join(HOME, "x"),
                  CLAUDE_SWITCH_HOME=os.path.join(HOME, "x"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "board"))
import board as B  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

FAILS = 0


def check(desc, cond, detail=""):
    global FAILS
    print(("PASS: " if cond else "FAIL: ") + desc + ("" if cond else f"\n      {str(detail)[:400]}"))
    FAILS += 0 if cond else 1


def as_(who, sid, tool, **args):
    B.ME, B.SID = who, sid
    return B.run_tool(tool, args)


for who in ("A", "F"):
    as_(who, who.lower(), "report_usage", five_hour_pct=10, weekly_pct=10)

# ---- file ownership ----
as_("A", "a", "add_task", title="auth", files=["src/auth/"])
as_("A", "a", "add_task", title="login form", files=["src/auth/login.tsx"])
as_("A", "a", "add_task", title="styles", files="styles/*.css, README.md")
txt, err = as_("A", "a", "claim_task")
check("A claims #1 (src/auth/)", "#1" in txt and "edit only these" in txt, txt)
txt, err = as_("F", "f", "claim_task")
check("F skips #2 (inside src/auth/, owned by #1) and gets #3", "#3" in txt, txt)
txt, err = as_("F", "f2", "claim_task", id=2)
check("claiming #2 directly is refused, naming the owner", err and "#1 (A) is editing src/auth" in txt, txt)
check("glob overlap detected", B.paths_overlap(["styles/main.css"], ["styles/*.css"]) is not None)
check("unrelated paths don't overlap", B.paths_overlap(["src/a"], ["src/ab"]) is None)
as_("A", "a", "complete_task", id=1, text="done")
txt, err = as_("F", "f2", "claim_task", id=2)
check("#2 claimable once #1 is done", not err and "#2" in txt, txt)

# ---- dependencies ----
as_("A", "a", "add_task", title="deploy", depends_on=[2])
txt, err = as_("A", "a", "claim_task", id=4)
check("task waiting on #2 is refused", err and "waits for #2" in txt, txt)
txt, err = as_("A", "a", "add_task", title="bad", depends_on=[99])
check("depending on a missing task is refused", err and "no task #99" in txt, txt)
txt, err = as_("A", "a", "update_task", id=4, depends_on=[4])
check("self-dependency is refused", err and "itself" in txt, txt)
txt, _ = as_("A", "a", "claim_task")
check("with only blocked tasks left, claim explains why", "blocked" in txt and "#4" in txt, txt)
as_("F", "f2", "complete_task", id=2, text="done")
txt, err = as_("A", "a", "claim_task")
check("dependency done: #4 is claimable", not err and "#4" in txt, txt)

# ---- ask_user + answer from the page ----
txt, err = as_("A", "a", "ask_user", id=4, question="Deploy to staging or prod?")
check("ask_user accepted", not err and "highlighted" in txt, txt)
state = B.web_state()
t4 = next(t for t in state["tasks"] if t["id"] == 4)
check("page sees the question", t4["needs_input"]["q"] == "Deploy to staging or prod?", t4)
B.web_post("/api/task/4/answer", {"text": "staging"})
txt, _ = as_("A", "a", "board_status")
check("answer delivered to the task owner only", "Answer to your question on task #4" in txt and "staging" in txt, txt)
txt, _ = as_("F", "f", "board_status")
check("other account doesn't get the message", "MESSAGE FROM THE USER" not in txt, txt)
check("question cleared after answer", "needs_input" not in next(t for t in B.web_state()["tasks"] if t["id"] == 4))

# ---- settings on the board ----
B.web_post("/api/settings", {"stop_5h": 50})
txt, _ = as_("F", "f", "report_usage", five_hour_pct=55, weekly_pct=10)
check("lowered stop line applies at once", "STOP" in txt and "50%" in txt, txt)
for bad in ({"stop_5h": 0}, {"stop_5h": "x"}, {"nope": 1}, {"ntfy_topic": "bad topic!"}):
    try:
        B.web_post("/api/settings", bad)
        check(f"bad setting {bad} refused", False)
    except ValueError:
        check(f"bad setting {bad} refused", True)
B.web_post("/api/settings", {"stop_5h": 85})

# ---- port leases ----
p1, _ = as_("A", "a", "lease_port")
p1b, _ = as_("A", "a", "lease_port")
p2, _ = as_("F", "f", "lease_port")
check("same session keeps its ports", p1 == p1b, (p1, p1b))
check("different sessions get different ranges", p1.split()[1] != p2.split()[1], (p1, p2))

# ---- stale flag ----
with B.board(write=True) as b:
    t3 = next(t for t in b["tasks"] if t["id"] == 3)
    t3["updated"] = time.time() - 3600
    b["sessions"][t3["session"]]["last"] = time.time() - 3600
check("claimed task whose session went silent an hour ago is flagged stale",
      next(t for t in B.web_state()["tasks"] if t["id"] == 3)["stale"])

# ---- a dead session's claim frees itself; a live, quiet one doesn't ----
as_("A", "a9", "add_task", title="long job")
txt, _ = as_("A", "a9", "claim_task")
jid = int(txt.split("#")[1].split(":")[0])
with B.board(write=True) as b:
    next(t for t in b["tasks"] if t["id"] == jid)["updated"] = time.time() - 3600  # task untouched for an hour
txt, err = as_("F", "f9", "claim_task", id=jid)
check("quiet task but its session still active: no takeover", err and "claimed by A" in txt, txt)
with B.board(write=True) as b:
    b["sessions"]["a9"]["last"] = time.time() - 3600  # the session itself has gone silent
txt, err = as_("F", "f9", "claim_task", id=jid)
check("session silent past the stale time: takeover allowed", not err and "taken over" in txt, txt)

# ---- per-account context window ----
with B.board(write=True) as b:
    B.set_setting(b, "context_window", 1000000, "A")
txt, _ = as_("A", "a", "report_context", tokens=500000)
check("A on 1M window: 500k tokens = 50%, under the line", "Context 50%" in txt, txt)
txt, _ = as_("F", "f", "report_context", tokens=150000)
check("F on default 200K: 150k tokens = 75%, CONTEXT LIMIT", txt.startswith("CONTEXT LIMIT") and "75%" in txt, txt)

# ---- five accounts at once ----
five = ["ONE", "TWO", "THREE", "FOUR", "FIVE"]
first = None
for i, n in enumerate(five):
    as_(n, f"s5-{n}", "report_usage", five_hour_pct=5, weekly_pct=5)
    txt, _ = as_(n, f"s5-{n}", "add_task", title=f"job {n}", files=[f"pkg/{n.lower()}/"])
    first = first or int(txt.split("#")[1].split(":")[0])
got = {}
for n in five:
    txt, err = as_(n, f"s5-{n}", "claim_task")
    got[n] = txt.split("You own task #")[1].split(":")[0] if "You own task" in txt else txt[:80]
check("five accounts each get a different task", len(set(got.values())) == 5, got)
txt, _ = as_("FIVE", "s5-FIVE", "board_status")
check("status lists all five accounts", all(f"{n}: 5h" in txt for n in five), txt[:300])

# ---- a running task can't take files another running task owns ----
B.PROJECT = ""
for who in ("X1", "X2"):
    as_(who, who.lower(), "report_usage", five_hour_pct=5, weekly_pct=5)
txt, _ = as_("X1", "x1", "add_task", title="api work", files=["svc/api/"])
api_id = int(txt.split("#")[1].split(":")[0])
txt, _ = as_("X2", "x2", "add_task", title="ui work", files=["svc/ui/"])
ui_id = int(txt.split("#")[1].split(":")[0])
as_("X1", "x1", "claim_task", id=api_id)
as_("X2", "x2", "claim_task", id=ui_id)
txt, err = as_("X2", "x2", "update_task", id=ui_id, files=["svc/ui/", "svc/api/client.ts"])
check("adding a file another running task owns is refused", err and f"#{api_id} (X1) is editing" in txt, txt)
txt, err = as_("X2", "x2", "update_task", id=ui_id, files=["svc/ui/", "svc/shared/"])
check("adding a free file works", not err, txt)

# ---- activity per account, across projects ----
with B.board(write=True) as b:
    b["sessions"]["x2"]["last"] = B.now() - 20 * 60  # X2 holds a task but has been silent 20 minutes
act = B.activity(list(B.each_board()))
check("activity counts sessions and flags a silent one holding a task",
      act["X1"]["sessions"] >= 1 and act["X2"]["quiet"] == 1 and act["X2"]["last_min"] >= 20, act.get("X2"))

# ---- account mix-up: the desktop app signed in as another account than the profile's label ----
prof, live = os.path.join(HOME, "profiles"), os.path.join(HOME, "live")
os.makedirs(prof, exist_ok=True); os.makedirs(live, exist_ok=True)
B.PROFILES, B.LIVE, B.NAMES = prof, live, os.path.join(HOME, "names.json")
B.REMOTE = {"accounts": {"org-a": "ATLAS", "org-f": "FORGE"}}
with open(os.path.join(prof, ".active"), "w") as f:
    f.write("main")
with open(B.NAMES, "w") as f:
    json.dump({"main": {"name": "ATLAS"}}, f)
def sample(org):
    with open(os.path.join(live, "plan-usage-history.json"), "w") as f:
        json.dump({"samples": [{"org": org, "t": (time.time() + 5) * 1000, "u": {}}]}, f)
sample("org-a")
check("no warning when the app's account matches the label", B.account_mismatch() == "")
sample("org-f")
check("warning when the app is signed in as FORGE but labelled ATLAS",
      "signed in as FORGE" in B.account_mismatch() and "calls this profile ATLAS" in B.account_mismatch(), B.account_mismatch())
B.REMOTE = {}

# ---- renaming an account: everywhere, every project, and the old name keeps working ----
B.PROJECT = ""
as_("OLDNAME", "on1", "report_usage", five_hour_pct=7, weekly_pct=7)
txt, _ = as_("OLDNAME", "on1", "add_task", title="renamed owner's task")
rid = int(txt.split("#")[1].split(":")[0])
as_("OLDNAME", "on1", "claim_task", id=rid)
as_("OLDNAME", "on1", "add_note", id=rid, text="halfway")
with B.board(write=True) as b:
    b["messages"].append({"t": B.now(), "to": "OLDNAME", "text": "hi", "read_by": []})
B.rename_account("oldname", "newname")
with B.board() as b:
    t = B.find(b, rid)
    check("rename rewrites usage, owner, notes and messages", "NEWNAME" in b["usage"] and "OLDNAME" not in b["usage"]
          and t["owner"] == "NEWNAME" and B.last_note(t)["by"] == "NEWNAME"
          and any(m["to"] == "NEWNAME" for m in b["messages"]), (t["owner"], list(b["usage"])))
txt, err = as_("OLDNAME", "on1", "claim_task")  # a session still configured with the old name
check("a session using the old name works as the new one", not err and f"#{rid}" in txt and B.ME == "NEWNAME", txt[:120])
check("repeating a finished rename is a no-op (a computer catching up)", B.rename_account("OLDNAME", "NEWNAME") == "NEWNAME")
B.rename_account("NEWNAME", "THIRD")
check("renaming again sends the oldest name straight to the newest", B.canon("OLDNAME") == "THIRD" and B.canon("NEWNAME") == "THIRD")
try:
    B.rename_account("THIRD", "X1")  # X1 is an existing account from an earlier section
    check("renaming onto an existing account is refused", False)
except ValueError:
    check("renaming onto an existing account is refused", True)

# ---- context window changes apply to stored token counts at once; 1M / 200K accepted ----
B.PROJECT = ""
as_("CW", "cw1", "report_usage", five_hour_pct=5, weekly_pct=5)
txt, _ = as_("CW", "cw1", "report_context", tokens=180000)
check("180k tokens on the 200K default is a context stop", txt.startswith("CONTEXT LIMIT"), txt)
with B.board(write=True) as b:
    B.set_setting(b, "context_window", "1M", "CW")
as_("CW", "cw1", "add_task", title="after the window change")
txt, err = as_("CW", "cw1", "claim_task")
check("after setting 1M the same session can claim again (18%)", not err and "You own task" in txt, txt)
with B.board() as b:
    check("page shows the recomputed 18%", B.ctx_pct(b, b["sessions"]["cw1"]) == 18, b["sessions"]["cw1"])
check("'200K' and '1,000,000' parse", B._whole("200K") == 200000 and B._whole("1,000,000") == 1000000)

# ---- projects: own tasks per repo, shared usage/settings, main board for repos without one ----
B.PROJECT = "shop"
txt, _ = as_("A", "pa", "add_task", title="main-board task (no shop project yet)")
main_id = int(txt.split("#")[1].split(":")[0])
check("a repo without a project uses the main board", main_id > 1, txt)
B.add_project("shop")
txt, _ = as_("A", "pa", "add_task", title="shop task")
check("a project's board numbers its own tasks from 1", "#1:" in txt, txt)
as_("A", "pa", "report_usage", five_hour_pct=33, weekly_pct=44)
txt, _ = as_("A", "pa", "board_status")
check("project status says which project, only its tasks", "Project: shop" in txt and "shop task" in txt
      and "main-board task" not in txt, txt[:400])
B.PROJECT = B.MAIN
with B.board() as b:
    check("usage reported in a project lands on the shared usage", b["usage"]["A"]["five_hour_pct"] == 33, b["usage"])
    check("main board keeps its tasks", any(t["title"].startswith("main-board") for t in b["tasks"]))
with B.board(write=True) as b:
    B.set_setting(b, "stop_week", 77)
B.PROJECT = "shop"
with B.board() as b:
    check("settings are shared with projects", B.settings_of(b)["stop_week"] == 77)
st = B.web_state()
check("page state lists projects with counts", st["project"] == "shop" and
      {p["name"] for p in st["projects"]} == {"default", "shop"}, st["projects"])
check("page state has setup steps", any(x["id"] == "usage" and x["done"] for x in st["setup"]), st["setup"])
txt, err = as_("A", "pa", "claim_task")
check("claiming in a project only offers its tasks", "shop task" in txt, txt)
try:
    B.add_project("default")
    check("'default' can't be a project name", False)
except ValueError:
    check("'default' can't be a project name", True)
B.PROJECT = ""

# ---- Codex accounts: live limits from Codex's own session log ----
logdir = os.path.join(HOME, "accounts", "CODY", "sessions", "2026", "11", "02")
os.makedirs(logdir)
open(os.path.join(HOME, "accounts", "CODY", "config.toml"), "w").close()
win = lambda pct, mins, reset: {"used_percent": pct, "window_minutes": mins, "resets_at": reset}
with open(os.path.join(logdir, "rollout-x.jsonl"), "w") as f:
    f.write(json.dumps({"type": "session_meta", "payload": {"cwd": "/x"}}) + "\n")
    f.write(json.dumps({"type": "event_msg", "payload": {"type": "token_count",
        "info": {"last_token_usage": {"total_tokens": 190000}, "model_context_window": 258400},
        "rate_limits": {"primary": win(42.4, 300, time.time() + 3600), "secondary": win(61, 10080, time.time() + 86400)}}}) + "\n")
cu = B.codex_usage().get("codex:CODY") or {}
check("Codex log: 5-hour and weekly windows read", cu.get("five_hour_pct") == 42 and cu.get("weekly_pct") == 61, cu)
check("Codex log: context % from the last turn", cu.get("context_pct") == 74, cu)
B.ORG = "codex:CODY"
txt, err = as_("CODY", "c1", "claim_task")
check("a Codex session over the context stop line can't claim", err and "context is at 74%" in txt, txt)
B.ORG = ""


def codex_log(home, name, acct, at, five, week, failing_turns=False):
    d = os.path.join(home, "sessions", "2026", "11", "03")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, name), "w") as f:
        f.write(json.dumps({"type": "session_meta", "payload": {"creator_account_id": acct}}) + "\n")
        f.write(json.dumps({"timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(at)), "type": "event_msg",
                            "payload": {"type": "token_count", "rate_limits": {
                                "primary": win(five, 300, time.time() + 3600), "secondary": win(week, 10080, time.time() + 86400)}}}) + "\n")
        if failing_turns:  # later turns that never reached the model (e.g. a login gone stale): no limits logged
            f.write(json.dumps({"type": "event_msg", "payload": {"type": "task_complete", "error": {"message": "401"}}}) + "\n")


dob, app = os.path.join(HOME, "accounts", "DOB"), os.path.join(HOME, "codex-app")
os.makedirs(dob)
open(os.path.join(dob, "config.toml"), "w").close()
codex_log(dob, "rollout-old.jsonl", "acct-1", time.time() - 7 * 3600, 35, 17, failing_turns=True)
B.CODEX_DEFAULT_HOME = app
cu = B.codex_usage()["codex:DOB"]
check("Codex limits are dated by their event, not by later failing turns", 7 * 60 - 2 <= (time.time() - cu["at"]) / 60 <= 7 * 60 + 2
      and cu["weekly_pct"] == 17, cu)
codex_log(app, "rollout-app.jsonl", "acct-1", time.time() - 600, 16, 3)
cu = B.codex_usage()["codex:DOB"]
check("the same ChatGPT account used from the Codex app (~/.codex) gives the newer numbers",
      cu["five_hour_pct"] == 16 and cu["weekly_pct"] == 3 and time.time() - cu["at"] < 700, cu)
codex_log(app, "rollout-app.jsonl", "acct-other", time.time() - 60, 90, 90)
check("another ChatGPT account in ~/.codex doesn't count", B.codex_usage()["codex:DOB"]["weekly_pct"] == 17)
B.CODEX_DEFAULT_HOME = os.path.join(HOME, "no-codex-app")

# ---- Antigravity: limits from the running app's GetUserStatus; connected accounts show even without numbers ----
os.makedirs(os.path.join(HOME, "accounts", "HED"), exist_ok=True)
open(os.path.join(HOME, "accounts", "HED", "antigravity"), "w").close()
iso_at = lambda t: datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
real_status, B._AGY[:] = B._antigravity_status, [0.0, {}]
B._antigravity_status = lambda: {"cascadeModelConfigData": {"clientModelConfigs": [
    {"quotaInfo": {"remainingFraction": 0.6, "resetTime": iso_at(time.time() + 3 * 3600)}},
    {"quotaInfo": {"remainingFraction": 0.1, "resetTime": iso_at(time.time() - 60)}},  # reset since: 0%
    {"quotaInfo": {}}]}}
au = B.antigravity_usage().get("antigravity:HED") or {}
check("Antigravity: the most used model that hasn't reset counts", au.get("five_hour_pct") == 40 and au.get("five_hour_resets", "").startswith("2h"), au)
check("Antigravity limits reach outside_usage", "antigravity:HED" in B.outside_usage())
B._antigravity_status, B._AGY[:] = (lambda: None), [0.0, {}]
check("Antigravity app closed: no numbers", B.antigravity_usage() == {})
cards = B.accounts_view({}, ["HED", "ZED", ""])
check("connected accounts without numbers get an unknown card", sorted(c["email"] for c in cards if c.get("unknown")) == ["HED", "ZED"], cards)
B._antigravity_status = real_status

# ---- team: a lead, roles, tasks assigned to one account ----
with B.board(write=True) as b:
    B.set_team(b, lead="A", role_for="F", role="Frontend only")
txt, _ = as_("F", "f", "board_status")
check("non-lead sees who leads and its own role", "A LEADS this project" in txt and "YOUR ROLE: Frontend only" in txt, txt[:600])
txt, _ = as_("A", "a", "board_status")
check("lead is told it leads, and sees F's role", "YOU ARE THE LEAD" in txt and "F's role: Frontend only" in txt, txt[:600])
check("everyone gets the keep-off-their-files rule", "Never edit, revert" in txt)
for who in ("A", "F"):
    as_(who, who.lower(), "report_usage", five_hour_pct=10, weekly_pct=10)
    with B.board(write=True) as b:
        for t in b["tasks"]:
            if t["status"] == "claimed":
                t["status"] = "done"
txt, _ = as_("A", "a", "add_task", title="ui polish", for_account="F")
tid = int(txt.split("#")[1].split()[0])
txt, err = as_("A", "a", "claim_task", id=tid)
check("a task assigned to F is refused to A", err and "assigned to F" in txt, txt)
txt, err = as_("F", "f9", "claim_task")
check("F gets its assigned task first", not err and f"#{tid}" in txt, txt)
with B.board(write=True) as b:
    B.set_team(b, lead="")
txt, _ = as_("F", "f", "board_status")
check("no lead: peers", "No lead" in txt, txt[:400])

# ---- shared instructions and delegation ----
with B.board(write=True) as b:
    B.set_team(b, instructions="Use pnpm. Tests: pnpm test.")
txt, _ = as_("A", "a9", "board_status")
check("shared instructions reach every account", "PROJECT INSTRUCTIONS FROM THE USER" in txt and "Use pnpm" in txt, txt[:400])
txt, _ = as_("A", "a9", "add_task", title="api docs")
did = int(txt.split("#")[1].split(":")[0])
as_("A", "a9", "claim_task", id=did)
txt, err = as_("F", "f9", "update_task", id=did, for_account="F")
check("can't hand on another account's running task", err and "only it can hand it on" in txt, txt)
txt, err = as_("A", "a9", "update_task", id=did, for_account="F")
check("A delegates its running task to F", not err and "for F" in txt, txt)
with B.board() as b:
    t = B.find(b, did)
check("delegated task is back in the queue, held for F", t["status"] == "open" and t["owner"] == "" and t["for"] == "F", t)
txt, err = as_("A", "a9", "claim_task", id=did)
check("A can't take it back", err and "assigned to F" in txt, txt)

# ---- assigned tasks only: the board, not just the instructions, keeps an implementer to its own tasks ----
with B.board(write=True) as b:
    B.set_team(b, role_for="F", assigned_only=True)
    for t in b["tasks"]:
        if t["status"] == "claimed" and t["owner"] == "F":
            t["status"] = "done"  # F's earlier task, so claim_task doesn't just resume it
txt, err = as_("F", "f9", "claim_task")
check("assigned-only F still gets its assigned task", not err and f"#{did}" in txt, txt)
with B.board(write=True) as b:
    B.find(b, did)["status"] = "done"
txt, _ = as_("A", "a9", "add_task", title="unassigned chore")
uid = int(txt.split("#")[1].split(":")[0])
txt, err = as_("F", "f9", "claim_task")
check("assigned-only F isn't handed an unassigned task", not err and "No open tasks are assigned to you" in txt, txt)
txt, err = as_("F", "f9", "claim_task", id=uid)
check("assigned-only F can't claim an unassigned task by id", err and "isn't assigned to you" in txt, txt)
with B.board(write=True) as b:
    B.set_team(b, role_for="F", assigned_only=False)
txt, err = as_("F", "f9", "claim_task", id=uid)
check("switched off, F can claim it", not err and f"#{uid}" in txt, txt)

print(f"== failures: {FAILS}")
sys.exit(1 if FAILS else 0)
