#!/usr/bin/env python3
"""The hosted storage (Redis split into small keys) against an in-memory fake Upstash: runs the other test files on it,
migrates a big old one-document board, and checks what calls cost in bytes. Run: python3 tests/test-redis.py"""
import json, os, random, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fake_redis  # noqa: E402

URL = fake_redis.start()
FAILS = 0


def check(desc, cond, detail=""):
    global FAILS
    print(("PASS: " if cond else "FAIL: ") + desc + ("" if cond else f"\n      {str(detail)[:400]}"))
    FAILS += 0 if cond else 1


env = dict(os.environ, KV_REST_API_URL=URL, KV_REST_API_TOKEN="x", COSHIFT_TEST_REDIS="1", COSHIFT_USAGE_APP="",
           COSHIFT_REQUIRE_USAGE="1")  # the default off Redis, which the tests expect
for name in ("test-features.py", "test-cloud.py"):  # test-board.py inspects the local board file
    fake_redis.DB.clear()
    r = subprocess.run([sys.executable, os.path.join(HERE, name)], env=env, capture_output=True, text=True, timeout=300)
    fails = [l for l in r.stdout.splitlines() if l.startswith("FAIL")]
    check(f"{name} passes on Redis", r.returncode == 0 and not fails, "\n".join(fails) or r.stdout[-800:] + r.stderr[-800:])

# ---- a big board from before the split: 150 tasks, most done, notes on each ----
fake_redis.DB.clear()
os.environ.update(KV_REST_API_URL=URL, KV_REST_API_TOKEN="x", COSHIFT_HOME=tempfile.mkdtemp(prefix="coshift-redis."),
                  COSHIFT_USAGE_APP="", VERCEL="1")  # VERCEL: the cache lives in memory only, as on the server
for k in ("CLAUDE_CODE_ORGANIZATION_UUID", "COSHIFT_AS", "UPSTASH_REDIS_REST_URL"):
    os.environ.pop(k, None)
sys.path.insert(0, os.path.join(HERE, "..", "board"))
import board as B  # noqa: E402

rnd, T = random.Random(1), B.now()
words = lambda n: " ".join(rnd.choice(["auth", "page", "fix", "test", "api", "the", "with", "form", "cache", "db"])  # noqa: E731
                           for _ in range(n))
tasks = []
for i in range(1, 151):
    st = "done" if i <= 130 else "claimed" if i % 5 == 0 else "open"  # 20 live tasks
    tasks.append({"id": i, "title": words(6), "detail": words(50), "status": st, "owner": "ATLAS" if st != "open" else "",
                  "created_by": "ATLAS", "updated": T - (150 - i) * 600, "files": [f"src/{i}/"], "depends_on": [], "for": "",
                  "notes": [{"t": T - j, "by": "ATLAS", "text": words(30)} for j in range(8)]})
old = {"next_id": 151, "tasks": tasks, "usage": {"ATLAS": {"five_hour_pct": 10, "weekly_pct": 20, "at": T}},
       "sessions": {"s1": {"account": "ATLAS", "last": T, "cwd": "x"}}, "messages": [], "guidance": [],
       "team": {"lead": "", "roles": {}, "instructions": words(1000)}, "contexts": {"ATLAS": [{"t": T, "session": "s1", "text": "old summary"}]}}
fake_redis.DB["board"] = json.dumps(old)
check("the old document is big (as in production)", len(fake_redis.DB["board"]) > 150_000, len(fake_redis.DB["board"]))


def cost(tool, args=None, cold=True, me="ATLAS", sid="s1"):
    if cold:
        B._CACHE = {}
    B.IO[:] = [0, 0]
    B.ME, B.SID = me, sid
    text, err = B.run_tool(tool, args or {})
    return text, err, B.IO[0], B.IO[1]


cost("board_status")  # first use migrates
check("old document kept as it was", json.loads(fake_redis.DB["board"]) == old)
with B.board() as b:
    every = B.all_tasks(b)
    B.load_notes(b, every)
    check("migration keeps every task and note", len(every) == 150 and sum(len(t["notes"]) for t in every) == 1200,
          (len(every), sum(len(t["notes"]) for t in every)))
    check("migration keeps usage and saved context", b["usage"]["ATLAS"]["weekly_pct"] == 20
          and b["contexts"]["ATLAS"][-1]["text"] == "old summary")

first, err, rd, wr = cost("board_status", sid="s2")
check("board_status shows the 8 KB project instructions the first time", "always follow" in first and not err)
text, err, rd, wr = cost("board_status", sid="s2")
check(f"board_status from a cold instance reads < 20 KB ({rd} B)", rd < 20_000 and "#150" in text and not err, text[:300])
check("and skips the instructions this session already got", "unchanged since this session" in text
      and len(text) < len(first) - 4000, (len(first), len(text)))
text, err, rd, wr = cost("board_status", cold=False, sid="s2")
check(f"warm board_status reads < 1 KB ({rd} B)", rd < 1000, rd)
text, err, rd, wr = cost("resume", cold=False, sid="s2")
check("resume always sends the instructions", "always follow" in text)

before = {k: v for k, v in fake_redis.DB.items() if ":t:" in k or k.endswith(":meta")}
_, err, rd, wr = cost("report_usage", {"five_hour_pct": 11, "weekly_pct": 21})
check(f"report_usage moves < 3 KB ({rd} B read, {wr} B written)", not err and rd + wr < 3000, (rd, wr))
_, err, rd2, wr2 = cost("report_context", {"tokens": 50000}, cold=False)
check(f"report_context moves < 2 KB ({rd2} B read, {wr2} B written)", not err and rd2 + wr2 < 2000, (rd2, wr2))
check("hot paths leave tasks and the board document alone",
      before == {k: v for k, v in fake_redis.DB.items() if ":t:" in k or k.endswith(":meta")})
_, _, _, wr3 = cost("report_usage", {"five_hour_pct": 11, "weekly_pct": 21}, cold=False)
_, _, _, wr4 = cost("report_usage", {"five_hour_pct": 11, "weekly_pct": 21}, cold=False)
check("an unchanged usage report isn't written again", wr4 < wr3 or wr4 < 600, (wr3, wr4))

text, err, rd, wr = cost("claim_task", {"id": 140})
check(f"claim_task shows the last 20 notes and moves < 25 KB ({rd} B read, {wr} B written)",
      not err and "#140" in text and rd + wr < 25_000, text[:300])
_, err, rd, wr = cost("add_note", {"id": 140, "text": "progress"}, cold=False)
check(f"add_note writes only that task ({wr} B written)", not err and wr < 3000, (rd, wr))
_, err, rd, wr = cost("complete_task", {"id": 140, "text": "done it"}, cold=False)
with B.board() as b:
    t = B.find(b, 140)
    check("completed task leaves the open index, joins the done list", t["status"] == "done"
          and "140" not in fake_redis.DB["cs:default:open"] and fake_redis.DB["cs:default:done"][0] == "140")
    check("its notes are all there", t["n_notes"] == 10 and t["last_note"]["text"] == "done: done it", t)
text, err = B.run_tool("add_task", {"title": "after", "depends_on": [3]})[0], None
check("a task can depend on one finished long ago (outside the hot index)", "Added task #151" in text, text)

print(f"\n== failures: {FAILS}")
sys.exit(1 if FAILS else 0)
