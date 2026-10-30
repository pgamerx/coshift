#!/usr/bin/env python3
"""0.2 board features, driven in-process as two accounts: file ownership, dependencies, ask_user + answer,
board settings, port leases, stale flags. Run: python3 tests/test-features.py"""
import json, os, sys, tempfile, time

HOME = tempfile.mkdtemp(prefix="coshift-features.")
for k in ("KV_REST_API_URL", "UPSTASH_REDIS_REST_URL", "CLAUDE_CODE_ORGANIZATION_UUID", "COSHIFT_AS"):
    os.environ.pop(k, None)
os.environ.update(COSHIFT_HOME=HOME, COSHIFT_USAGE_APP="", CLAUDE_SWITCH_LIVE=os.path.join(HOME, "x"),
                  CLAUDE_SWITCH_HOME=os.path.join(HOME, "x"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "board"))
import board as B  # noqa: E402

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

print(f"== failures: {FAILS}")
sys.exit(1 if FAILS else 0)
