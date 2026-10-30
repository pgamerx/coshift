#!/usr/bin/env python3
"""Coshift: a shared task board for Claude Code sessions on several accounts, working side by side.

Runs as a stdio MCP server inside each Claude Code session (both desktop windows),
as a web page for you (board.py web --open, or "Open Coshift" in the menu bar),
and as a small CLI:  board.py show | add "title" ["detail"] | reopen <id>
Sessions that started before the board was registered can use every tool through Bash:
board.py call help, then board.py call <tool> '<json args>'.

State is one JSON file (~/.coshift/board.json) guarded by a file lock, so any
number of sessions from either account can read and write it safely.
No network calls, no credentials: each session reports its own plan usage, which
Claude reads with the desktop app's get_usage tool.
"""
import json, os, plistlib, re, socket, subprocess, sys, tempfile, time, urllib.request, uuid, webbrowser
from fnmatch import fnmatch

try:  # exclusive lock on the local board file: fcntl on macOS/Linux, msvcrt on Windows
    import fcntl

    def _lock(f):
        fcntl.flock(f, fcntl.LOCK_EX)
except ImportError:
    import msvcrt

    def _lock(f):
        f.seek(0)
        while True:
            try:
                msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
                return
            except OSError:
                time.sleep(0.05)
from contextlib import contextmanager
from datetime import datetime, timezone

HOME = os.environ.get("COSHIFT_HOME", os.path.expanduser("~/.coshift"))
BOARD = os.path.join(HOME, "board.json")
LOCK = os.path.join(HOME, "board.lock")
STOP_5H = int(os.environ.get("COSHIFT_STOP_5H", "85"))      # % of the 5-hour limit
STOP_WEEK = int(os.environ.get("COSHIFT_STOP_WEEK", "90"))  # % of the weekly limit
PORT = int(os.environ.get("COSHIFT_PORT", "7777"))
SWITCH = os.environ.get("CLAUDE_SWITCH_BIN", os.path.expanduser("~/bin/claude-switch"))
_APP_DIR = {"darwin": "~/Library/Application Support/Claude", "win32": os.path.join(os.environ.get("APPDATA", "~"), "Claude")}
LIVE = os.environ.get("CLAUDE_SWITCH_LIVE",
                      os.path.expanduser(_APP_DIR.get(sys.platform, "~/.config/Claude")))  # the Claude desktop app's data
PROFILES = os.environ.get("CLAUDE_SWITCH_HOME", os.path.expanduser("~/ClaudeProfiles"))
NAMES = os.environ.get("CLAUDE_SWITCH_MENU_NAMES",
                       os.path.expanduser("~/Library/Application Support/ClaudeSwitchMenu/names.json"))
USAGE_APP = os.environ.get("COSHIFT_USAGE_APP", "HamedElfayome.Claude-Usage")  # "" turns it off
APPLE_EPOCH = 978307200  # Cocoa timestamps count from 2001-01-01
PAGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard.html")
# Shared cloud storage (Upstash Redis REST). On Vercel it comes from env vars; on the Mac from
# ~/.coshift/remote.json, which also maps org ids to account names (ATLAS/FORGE). Without it,
# the board is the local file only.
def _remote_config():
    try:
        with open(os.path.join(HOME, "remote.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


REMOTE = _remote_config()
REDIS_URL = os.environ.get("KV_REST_API_URL") or os.environ.get("UPSTASH_REDIS_REST_URL") or REMOTE.get("redis_url", "")
REDIS_TOKEN = (os.environ.get("KV_REST_API_TOKEN") or os.environ.get("UPSTASH_REDIS_REST_TOKEN")
               or REMOTE.get("redis_token", ""))
# Without fresh usage (e.g. the Mac is off), cloud claims go ahead with a warning instead of being refused.
REQUIRE_USAGE = os.environ.get("COSHIFT_REQUIRE_USAGE", "0" if REDIS_URL else "1") == "1"
STOP_CONTEXT = int(os.environ.get("COSHIFT_STOP_CONTEXT", "70"))  # % of the session's context window
FRESH_MIN = 20     # a usage report older than this must be refreshed before claiming
STALE_CLAIM_MIN = 45  # a claimed task untouched this long can be taken over

# Settings live on the board itself (changed from the page or `coshift config`), so they take effect at
# once everywhere without a redeploy. Env vars only set the defaults.
DEFAULTS = {"stop_5h": STOP_5H, "stop_week": STOP_WEEK, "stop_context": STOP_CONTEXT, "stale_min": STALE_CLAIM_MIN,
            "fresh_min": FRESH_MIN, "ntfy_topic": os.environ.get("COSHIFT_NTFY_TOPIC", ""),
            "port_base": 4100, "port_block": 10,
            "context_window": int(os.environ.get("COSHIFT_CONTEXT_WINDOW") or 200000)}
SETTING_RANGES = {"stop_5h": (1, 100), "stop_week": (1, 100), "stop_context": (5, 100), "stale_min": (5, 1440),
                  "fresh_min": (1, 1440), "port_base": (1024, 60000), "port_block": (2, 1000),
                  "context_window": (50000, 2000000)}

ORG = os.environ.get("CLAUDE_CODE_ORGANIZATION_UUID", "")
ME = (os.environ.get("COSHIFT_AS") or os.environ.get("CLAUDE_CODE_USER_EMAIL")
      or os.environ.get("CLAUDE_CODE_ACCOUNT_UUID") or "")
if REMOTE.get("accounts", {}).get(ORG):
    ME = REMOTE["accounts"][ORG]  # same name the cloud uses for this account, e.g. ATLAS
SID = os.environ.get("CLAUDE_CODE_SESSION_ID") or f"pid{os.getpid()}"
CWD = os.getcwd()

INSTRUCTIONS = f"""Shared task board for several Claude accounts (two or more) working on the same project in parallel.
You are one of them; the others work in their own sessions. Follow this protocol:
1. Before starting work and after finishing each task, call get_usage (desktop app tool) and pass the
   plan numbers to report_usage. Claiming needs a report from the last {FRESH_MIN} minutes.
2. Call board_status, then claim_task to take the next open task (or a specific id). Work only on
   tasks you have claimed, so no two sessions ever do the same thing.
3. While working, call add_note with short progress notes (what's done, what's next, files touched),
   so another account can continue if you stop.
4. When done: complete_task with a summary, report usage again, then claim the next task.
5. If your 5-hour usage reaches {STOP_5H}% or weekly reaches {STOP_WEEK}% (report_usage will say so),
   finish the current small step, then release_task with a full handover (what's done, what's left,
   exact next step, files, branch) and stop. Another account picks it up.
6. Split big requests from the user into tasks with add_task so every account has work.
7. Tool results may end with MESSAGE FROM THE USER: those come from the user's board page. Follow them.
8. board_status and claim_task show GUIDANCE FROM THE USER: standing rules the user wrote for this
   project (for every account or just you). They always apply, like instructions from the user.
9. Already have your own task list from before? Put it on the board: add_task each item (pass
   done_summary for items already finished), then claim the one you're working on.
10. Context: call get_usage and pass its context percent to report_context after each task. At {STOP_CONTEXT}%
   take no new task: finish the current one, then save_context with a full summary for your next session
   and give the user this two-line prompt to start it:
     Run: curl -sS "$COSHIFT_URL/api/help" -H "Authorization: Bearer $COSHIFT_TOKEN" and follow it.
     Start with board resume and continue from your saved context.
   (desktop sessions with the board tools: just call resume).
11. A new session starts with resume: it returns your account's saved context summary and your tasks.
12. When you add tasks, pass files (the paths each will edit) and depends_on (ids that must finish first).
   claim_task never gives you a task whose files another running task is editing, or whose dependencies
   aren't done. Edit only the files of the task you own.
13. Blocked on a decision only the user can make? ask_user, then keep going on something else.
14. Before starting a dev server or database, lease_port and use the ports it gives you.
Work on your own git branch or worktree; never commit to another account's branch."""


def now():
    return time.time()


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")


def ago(t):
    m = int((now() - t) // 60)
    return f"{m}m ago" if m < 120 else f"{m // 60}h ago"


def redis(*cmd):
    req = urllib.request.Request(REDIS_URL, data=json.dumps(cmd).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {REDIS_TOKEN}"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())["result"]


def _fresh(b):
    b = b or {"next_id": 1, "tasks": [], "usage": {}}
    for k, v in (("sessions", {}), ("messages", []), ("guidance", [])):
        b.setdefault(k, v)
    return b


@contextmanager
def _redis_board(write):
    if not write:
        raw = redis("GET", "board")
        yield _fresh(json.loads(raw) if raw else None)
        return
    me, deadline = uuid.uuid4().hex, time.time() + 15
    while not redis("SET", "board:lock", me, "NX", "PX", "10000"):
        if time.time() > deadline:
            raise ValueError("board is busy, try again")
        time.sleep(0.05)
    try:
        raw = redis("GET", "board")
        b = _fresh(json.loads(raw) if raw else None)
        yield b
        redis("SET", "board", json.dumps(b))
    finally:  # release only our own lock
        redis("EVAL", "if redis.call('get',KEYS[1])==ARGV[1] then return redis.call('del',KEYS[1]) end return 0",
              "1", "board:lock", me)


@contextmanager
def board(write=False):
    """Yields the board dict under an exclusive lock; saves atomically if write=True."""
    if REDIS_URL:
        with _redis_board(write) as b:
            _apply_settings(b)
            yield b
        return
    os.makedirs(HOME, mode=0o700, exist_ok=True)
    with open(LOCK, "a+") as lk:
        _lock(lk)
        try:
            with open(BOARD, encoding="utf-8") as f:
                b = json.load(f)
        except FileNotFoundError:
            b = {"next_id": 1, "tasks": [], "usage": {}}
        b.setdefault("sessions", {})
        b.setdefault("messages", [])
        b.setdefault("guidance", [])
        _apply_settings(b)
        yield b
        if write:
            fd, tmp = tempfile.mkstemp(dir=HOME, prefix=".board.")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(b, f, indent=1)
            os.replace(tmp, BOARD)


def settings_of(b):
    return {**DEFAULTS, **{k: v for k, v in b.get("settings", {}).items() if k in DEFAULTS}}


def _apply_settings(b):
    global STOP_5H, STOP_WEEK, STOP_CONTEXT, STALE_CLAIM_MIN, FRESH_MIN
    s = settings_of(b)
    STOP_5H, STOP_WEEK, STOP_CONTEXT = s["stop_5h"], s["stop_week"], s["stop_context"]
    STALE_CLAIM_MIN, FRESH_MIN = s["stale_min"], s["fresh_min"]


def window_for(b, account):
    """Context window (tokens) of an account's sessions: its own setting, else the board-wide one."""
    return b.get("settings", {}).get("context_windows", {}).get(account) or settings_of(b)["context_window"]


def last_seen(b, t):
    """When the task's owner was last active: a task update, or its session reporting in (the hook, any tool)."""
    return max(t.get("updated", 0), b["sessions"].get(t.get("session") or "", {}).get("last", 0))


def set_setting(b, key, value, account=None):
    """Validates and stores one setting on the board (context_window can be per account). Returns the value."""
    if key not in DEFAULTS:
        raise ValueError(f"unknown setting {key}. Settings: {', '.join(DEFAULTS)}")
    if key == "ntfy_topic":
        value = str(value or "").strip()
        if value and not re.fullmatch(r"[A-Za-z0-9_-]{4,64}", value):
            raise ValueError("ntfy_topic: 4-64 letters, digits, - or _ (or empty to turn notifications off)")
    else:
        lo, hi = SETTING_RANGES[key]
        try:
            value = int(value)
        except (TypeError, ValueError):
            raise ValueError(f"{key} must be a whole number")
        if not lo <= value <= hi:
            raise ValueError(f"{key} must be between {lo} and {hi}")
    if account and key == "context_window":
        b.setdefault("settings", {}).setdefault("context_windows", {})[account.upper()] = value
    elif account:
        raise ValueError("only context_window can be set per account")
    else:
        b.setdefault("settings", {})[key] = value
    _apply_settings(b)
    return value


def notify_phone(topic, title, text):
    """Optional push notification through ntfy.sh (the user subscribes to their topic in the ntfy app)."""
    if not topic:
        return
    try:
        req = urllib.request.Request(f"https://ntfy.sh/{topic}", data=text.encode()[:3000], method="POST",
                                     headers={"Title": title[:200], "Tags": "baton"})
        urllib.request.urlopen(req, timeout=5).read()
    except Exception:
        pass  # a notification must never break the board


def _paths(v):
    if isinstance(v, str):
        v = v.split(",")
    out = [str(p).strip().strip("/") for p in (v or [])]
    return [p for p in out if p and p not in (".", "*", "**")] if out else []


def paths_overlap(xs, ys):
    """First overlapping pair of path patterns (same path, one inside the other, or a glob match), else None."""
    for x in xs:
        for y in ys:
            if x == y or x.startswith(y + "/") or y.startswith(x + "/") or fnmatch(x, y) or fnmatch(y, x):
                return x, y
    return None


def blockers(b, t):
    """Why task t can't start now: unfinished dependencies, or files another running task owns."""
    out = []
    for d in t.get("depends_on", []):
        dt = next((x for x in b["tasks"] if x["id"] == d), None)
        if dt and dt["status"] not in ("done", "cancelled"):
            out.append(f"waits for #{d} ({dt['status']})")
    for o in b["tasks"]:
        if o["id"] != t["id"] and o["status"] == "claimed":
            hit = paths_overlap(t.get("files", []), o.get("files", []))
            if hit:
                out.append(f"#{o['id']} ({o['owner']}) is editing {hit[1]}")
    return out


def _deps(b, v, self_id=None):
    if isinstance(v, str):
        v = [x for x in re.split(r"[,\s#]+", v) if x]
    ids = []
    for x in v or []:
        i = int(x)
        if i == self_id:
            raise ValueError("a task can't depend on itself")
        find(b, i)  # must exist
        ids.append(i)
    return ids


def find(b, tid):
    for t in b["tasks"]:
        if t["id"] == tid:
            return t
    raise ValueError(f"no task #{tid}")


def over_limit(u):
    """Reason string if this usage report is at/over a stop threshold, else ''."""
    if not u:
        return ""
    if u.get("five_hour_pct", 0) >= STOP_5H:
        return f"5-hour usage {u['five_hour_pct']}% >= {STOP_5H}%"
    if u.get("weekly_pct", 0) >= STOP_WEEK:
        return f"weekly usage {u['weekly_pct']}% >= {STOP_WEEK}%"
    return ""


def note(t, by, text):
    t.setdefault("notes", []).append({"t": now(), "by": by, "text": text})
    t["updated"] = now()


def render(b, me=""):
    out = []
    out.append(f"Stop thresholds: 5-hour {STOP_5H}%, weekly {STOP_WEEK}%")
    out.append("Accounts:")
    if not b["usage"]:
        out.append("  (no usage reported yet)")
    for acct, u in sorted(b["usage"].items()):
        flag = over_limit(u)
        status = f"STOP ({flag})" if flag else "ok to work"
        you = "  <- you" if acct == me else ""
        out.append(f"  {acct}: 5h {u['five_hour_pct']}% (resets {u.get('five_hour_resets', '?')}), "
                   f"weekly {u['weekly_pct']}% (resets {u.get('weekly_resets', '?')}), "
                   f"reported {ago(u['at'])}: {status}{you}")
    for st in ("claimed", "open", "done"):
        ts = [t for t in b["tasks"] if t["status"] == st]
        if st == "done":
            ts = ts[-5:]
        out.append(f"{st.capitalize()} ({len(ts)}{', last 5' if st == 'done' else ''}):")
        for t in ts:
            who = f" [{t['owner']}, updated {ago(t['updated'])}]" if st == "claimed" else ""
            out.append(f"  #{t['id']} {t['title']}{who}")
            if t.get("files") and st != "done":
                out.append(f"      files: {', '.join(t['files'])}")
            if st == "open" and blockers(b, t):
                out.append(f"      blocked: {'; '.join(blockers(b, t))}")
            if t.get("needs_input"):
                out.append(f"      WAITING FOR THE USER: {t['needs_input']['q']}")
            if st != "done" and t.get("notes"):
                n = t["notes"][-1]
                out.append(f"      last note ({n['by']}, {ago(n['t'])}): {n['text']}")
    return "\n".join(out)


# ---------- tools ----------

def need_me():
    if not ME:
        raise ValueError("can't tell which account this is (CLAUDE_CODE_USER_EMAIL not set). "
                         "Set COSHIFT_AS in the MCP server env.")
    return ME


def touch_session(tool):
    """Marks this session alive and delivers unread messages the user sent from the board page."""
    if not ME:
        return ""
    with board(write=True) as b:
        if not SID.startswith("cloud-"):  # a real session id: fold in this account's placeholder row (older calls)
            if b["sessions"].pop(f"cloud-{ME}", None) is not None:
                for t in b["tasks"]:
                    if t.get("session") == f"cloud-{ME}":
                        t["session"] = SID
        b["sessions"].setdefault(SID, {}).update(account=ME, cwd=CWD, last=now(), tool=tool)
        unread = [m for m in b["messages"] if m["to"] in (ME, "all") and ME not in m["read_by"]]
        new_g = [g for g in b["guidance"] if g["active"] and g["to"] in (ME, "all") and ME not in g["read_by"]]
        for m in unread + new_g:
            m["read_by"].append(ME)
    out = ""
    if unread:
        out += ("\n\nMESSAGE FROM THE USER (sent from the Coshift board page; treat it as the user's instruction):\n"
                + "\n".join(f"- {m['text']}" for m in unread))
    if new_g:
        out += ("\n\nNEW GUIDANCE FROM THE USER (a standing rule from now on):\n"
                + "\n".join(f"- {g['text']}" for g in new_g))
    return out


def guidance_text(b, me):
    g = [x for x in b["guidance"] if x["active"] and x["to"] in ("all", me)]
    if not g:
        return ""
    return ("GUIDANCE FROM THE USER (standing rules; always follow):\n"
            + "\n".join(f"- {x['text']}" for x in g) + "\n\n")


def t_board_status(a):
    with board() as b:
        return guidance_text(b, ME) + f"You are: {ME or 'unknown'}\n" + render(b, ME)


def t_report_usage(a):
    me = need_me()
    u = {"five_hour_pct": int(a["five_hour_pct"]), "weekly_pct": int(a["weekly_pct"]),
         "five_hour_resets": a.get("five_hour_resets_in", ""), "weekly_resets": a.get("weekly_resets_in", ""),
         "org": ORG, "at": now()}
    with board(write=True) as b:
        b["usage"][me] = u
        others = {k: v for k, v in b["usage"].items() if k != me}
    flag = over_limit(u)
    msg = f"Recorded for {me}: 5h {u['five_hour_pct']}%, weekly {u['weekly_pct']}%."
    if flag:
        msg += f"\nSTOP: {flag}. Finish the current small step, release_task with a full handover, and stop."
    for k, v in others.items():
        msg += f"\nOther account {k}: 5h {v['five_hour_pct']}%, weekly {v['weekly_pct']}% (reported {ago(v['at'])})."
    return msg


def t_add_task(a):
    me = need_me()
    with board(write=True) as b:
        t = {"id": b["next_id"], "title": a["title"].strip(), "detail": a.get("detail", "").strip(),
             "status": "open", "owner": "", "created_by": me, "updated": now(), "notes": [],
             "files": _paths(a.get("files")), "depends_on": _deps(b, a.get("depends_on"))}
        b["next_id"] += 1
        if a.get("done_summary", "").strip():
            t["status"], t["owner"] = "done", me
            note(t, me, f"done: {a['done_summary'].strip()}")
        b["tasks"].append(t)
    return f"Added task #{t['id']}{' (done)' if t['status'] == 'done' else ''}: {t['title']}"


def t_claim_task(a):
    me = need_me()
    with board(write=True) as b:
        u = b["usage"].get(me)
        live = outside_usage().get(ORG) if ORG else None
        if live and (not u or live["at"] > u["at"]):
            u = live  # e.g. the Claude Usage app's live numbers, so no manual report is needed
        warn = ""
        if not u or now() - u["at"] > FRESH_MIN * 60:
            if REQUIRE_USAGE:
                raise ValueError(f"report your usage first (get_usage, then report_usage); last report "
                                 f"{ago(u['at']) if u else 'never'}.")
            warn = (f"WARNING: your usage is unknown (last update {ago(u['at']) if u else 'never'}; the user's Mac "
                    "may be off). Keep tasks small and leave notes often.\n\n")
        flag = over_limit(u) if u else ""
        if flag:
            raise ValueError(f"you're at your limit ({flag}). Don't claim new work; another account will.")
        mine = [t for t in b["tasks"] if t["status"] == "claimed" and t["owner"] == me]
        ctx = b["sessions"].get(SID, {}).get("context_pct", 0)
        if ctx >= STOP_CONTEXT and not (mine and a.get("id") in (None, mine[0]["id"])):
            raise ValueError(f"this session's context is at {ctx}% (stop line {STOP_CONTEXT}%). Take no new task: finish "
                             "your current one, then save_context and give the user the two-line restart prompt.")
        if "id" in a and a["id"] is not None:
            t = find(b, int(a["id"]))
        elif mine:
            t = mine[0]  # resume your own unfinished task first
        else:
            opens = [t for t in b["tasks"] if t["status"] == "open"]
            t = next((t for t in opens if not blockers(b, t)), None)
            if not t:
                if opens:
                    return ("Every open task is blocked right now:\n" + "\n".join(
                        f"  #{o['id']} {o['title']}: {'; '.join(blockers(b, o))}" for o in opens)
                        + "\nWait, or ask the user what to do next.")
                return "No open tasks. Ask the user what's next, or split the current goal with add_task."
        if not (t["status"] == "claimed" and t["owner"] == me):
            br = blockers(b, t)
            if br:
                raise ValueError(f"task #{t['id']} can't start yet: {'; '.join(br)}.")
        if t["status"] in ("done", "cancelled"):
            raise ValueError(f"task #{t['id']} is {t['status']}.")
        if t["status"] == "claimed" and t["owner"] != me:
            owner_u = b["usage"].get(t["owner"])
            stale = now() - last_seen(b, t) > STALE_CLAIM_MIN * 60  # owner's session gone quiet, not just the task
            if not (over_limit(owner_u) or stale):
                raise ValueError(f"task #{t['id']} is claimed by {t['owner']} (active {ago(t['updated'])}). "
                                 "Pick another one.")
            note(t, me, f"taken over from {t['owner']} ({'at limit' if over_limit(owner_u) else 'inactive'})")
        t["status"], t["owner"], t["session"] = "claimed", me, SID
        t["updated"] = now()
        notes = "\n".join(f"  - {n['by']} ({iso(n['t'])}): {n['text']}" for n in t.get("notes", []))
        guide = guidance_text(b, me)
        files = f"Files you own for this task (edit only these): {', '.join(t['files'])}\n" if t.get("files") else ""
    return warn + guide + (f"You own task #{t['id']}: {t['title']}\n{t['detail']}\n" + files
            + (f"Notes / handover so far:\n{notes}" if notes else "No notes yet."))


def t_add_note(a):
    me = need_me()
    with board(write=True) as b:
        t = find(b, int(a["id"]))
        note(t, me, a["text"].strip())
    return f"Note added to #{t['id']}."


def _finish(a, status, label):
    me = need_me()
    with board(write=True) as b:
        t = find(b, int(a["id"]))
        if t["status"] != "claimed" or t["owner"] != me:
            raise ValueError(f"task #{t['id']} isn't claimed by you (status {t['status']}, owner {t['owner'] or 'none'}).")
        note(t, me, f"{label}: {a['text'].strip()}")
        t.pop("needs_input", None)
        t["status"] = status
        if status == "open":
            t["owner"] = ""
    return f"Task #{t['id']} {'completed' if status == 'done' else 'released with handover'}."


def t_complete_task(a):
    return _finish(a, "done", "done")


def t_release_task(a):
    return _finish(a, "open", "HANDOVER")


def t_update_task(a):
    me = need_me()
    with board(write=True) as b:
        t = find(b, int(a["id"]))
        changed = []
        for k in ("title", "detail"):
            if a.get(k, "").strip():
                t[k] = a[k].strip()
                changed.append(k)
        if "files" in a:
            t["files"] = _paths(a["files"])
            changed.append("files")
        if "depends_on" in a:
            t["depends_on"] = _deps(b, a["depends_on"], t["id"])
            changed.append("depends_on")
        if not changed:
            raise ValueError("nothing to change: pass title, detail, files or depends_on")
        note(t, me, f"updated {', '.join(changed)}")
    return f"Task #{t['id']} updated ({', '.join(changed)})."


def t_ask_user(a):
    me = need_me()
    q = a["question"].strip()
    if not q:
        raise ValueError("question is empty")
    with board(write=True) as b:
        t = find(b, int(a["id"]))
        t["needs_input"] = {"q": q, "t": now(), "by": me}
        note(t, me, f"QUESTION for the user: {q}")
        topic = settings_of(b)["ntfy_topic"]
    notify_phone(topic, f"{me} needs you on #{t['id']}", q)
    return ("Asked. The user sees it highlighted on the board (and on their phone if notifications are on). "
            "Their answer arrives as MESSAGE FROM THE USER on a later board call. Meanwhile do any part that "
            "doesn't depend on the answer, or claim another unblocked task.")


def t_lease_port(a):
    need_me()
    with board(write=True) as b:
        s, leases = settings_of(b), b.setdefault("leases", {})
        for sid in [k for k in leases if now() - b["sessions"].get(k, {}).get("last", 0) > 24 * 3600]:
            if sid != SID:
                del leases[sid]  # free ranges of sessions gone for a day
        if SID not in leases:
            used, n = set(leases.values()), 0
            while s["port_base"] + n * s["port_block"] in used:
                n += 1
            leases[SID] = s["port_base"] + n * s["port_block"]
        base, size = leases[SID], s["port_block"]
    return (f"Ports {base}-{base + size - 1} are yours for this session. Use {base} for the dev server and the next "
            f"ones for databases or other services (e.g. PORT={base}). Other sessions get different ranges, so "
            "your servers won't collide.")


RESTART_PROMPT = ('Run: curl -sS "$COSHIFT_URL/api/help" -H "Authorization: Bearer $COSHIFT_TOKEN" and follow it.\n'
                  'Start with board resume and continue from your saved context.')


def t_report_context(a):
    me, pct = need_me(), int(a.get("pct") or 0)
    with board(write=True) as b:
        if a.get("tokens"):  # the hook sends raw tokens; the board knows each account's window
            pct = min(100, int(a["tokens"]) * 100 // window_for(b, me))
        b["sessions"].setdefault(SID, {}).update(account=me, context_pct=pct, context_tokens=int(a.get("tokens") or 0),
                                                 context_at=now())
    if pct >= STOP_CONTEXT:
        return (f"CONTEXT LIMIT: this session is at {pct}% of its context window (stop line {STOP_CONTEXT}%). "
                "Take no new task. Finish the current one, then call save_context with a full summary for your next "
                "session, and give the user this two-line prompt to start it (in a code block):\n" + RESTART_PROMPT)
    return f"Context {pct}% recorded."


def t_save_context(a):
    me, text = need_me(), a["text"].strip()
    if len(text) < 200:
        raise ValueError("that's too short to continue from. Include: goal, decisions made, current state, branch and "
                         "commits, your claimed task and its next step, open questions, gotchas, files that matter.")
    with board(write=True) as b:
        hist = b.setdefault("contexts", {}).setdefault(me, [])
        hist.append({"t": now(), "session": SID, "text": text})
        del hist[:-5]  # keep the last five summaries per account
    return ("Context saved for " + me + ". Now give the user this prompt for the new session, in a code block, "
            "and stop:\n" + RESTART_PROMPT)


def t_resume(a):
    me = need_me()
    with board() as b:
        hist = b.get("contexts", {}).get(me, [])
        mine = [t for t in b["tasks"] if t["status"] == "claimed" and t["owner"] == me]
        out = guidance_text(b, me) + f"You are {me}.\n\n"
        if hist:
            c = hist[-1]
            out += f"SAVED CONTEXT from your previous session ({iso(c['t'])}, {ago(c['t'])}):\n{c['text']}\n\n"
        else:
            out += "No saved context for this account yet: start from board_status.\n\n"
        for t in mine:
            notes = "\n".join(f"  - {n['by']} ({iso(n['t'])}): {n['text']}" for n in t.get("notes", [])[-8:])
            out += f"YOUR CLAIMED TASK #{t['id']}: {t['title']}\n{t['detail']}\n{notes}\n\n"
        return out + render(b, me)


TOOLS = {
    "board_status": (t_board_status, "Show every account's usage and every task (claimed, open, recent done).", {}, []),
    "report_usage": (t_report_usage, "Record this account's plan usage. Get the numbers from the get_usage tool "
                     "(5-hour limit and 'Weekly · all models'). Says STOP when you're near the limit.",
                     {"five_hour_pct": {"type": "integer"}, "weekly_pct": {"type": "integer"},
                      "five_hour_resets_in": {"type": "string", "description": "e.g. '1h 15m'"},
                      "weekly_resets_in": {"type": "string", "description": "e.g. '6d 1h'"}},
                     ["five_hour_pct", "weekly_pct"]),
    "add_task": (t_add_task, "Add a task to the shared board. Make each task independent and specific "
                 "(goal, files/area, what done looks like). Pass done_summary to record work you already finished.",
                 {"title": {"type": "string"}, "detail": {"type": "string"},
                  "files": {"type": "array", "items": {"type": "string"},
                            "description": "paths or globs this task will edit, e.g. src/auth/ or *.css; no other "
                                           "running task may touch them"},
                  "depends_on": {"type": "array", "items": {"type": "integer"},
                                 "description": "task ids that must be done first"},
                  "done_summary": {"type": "string", "description": "only for a task that's already finished"}},
                 ["title"]),
    "claim_task": (t_claim_task, "Take a task: your own unfinished one first, else the next open one, or a given id. "
                   "Returns its detail and all handover notes. Refuses if your usage report is stale or over the limit.",
                   {"id": {"type": "integer"}}, []),
    "add_note": (t_add_note, "Add a progress note to a task (done so far, next step, files touched).",
                 {"id": {"type": "integer"}, "text": {"type": "string"}}, ["id", "text"]),
    "complete_task": (t_complete_task, "Mark your claimed task done with a short summary of what changed.",
                      {"id": {"type": "integer"}, "text": {"type": "string"}}, ["id", "text"]),
    "release_task": (t_release_task, "Give your claimed task back with a full handover (done, left, exact next step, "
                     "files, branch) so another account can continue. Use when you're near your limit.",
                     {"id": {"type": "integer"}, "text": {"type": "string"}}, ["id", "text"]),
    "report_context": (t_report_context, "Record how full this session's context window is (percent). The cloud hook "
                       "does this automatically; desktop sessions pass get_usage's context percent. Says CONTEXT LIMIT "
                       f"at {STOP_CONTEXT}%.", {"pct": {"type": "integer"}, "tokens": {"type": "integer"}}, []),
    "save_context": (t_save_context, "Save a full context summary for this account's next session (instead of "
                     "compacting): goal, decisions, current state, branch/commits, claimed task and exact next step, "
                     "open questions, gotchas, key files. The next session gets it from resume.",
                     {"text": {"type": "string"}}, ["text"]),
    "update_task": (t_update_task, "Change a task's title, detail, files (paths it owns) or depends_on.",
                    {"id": {"type": "integer"}, "title": {"type": "string"}, "detail": {"type": "string"},
                     "files": {"type": "array", "items": {"type": "string"}},
                     "depends_on": {"type": "array", "items": {"type": "integer"}}}, ["id"]),
    "ask_user": (t_ask_user, "Flag that you need the user's decision on a task. It's highlighted on their board "
                 "(and pushed to their phone if set up); the answer comes back as MESSAGE FROM THE USER.",
                 {"id": {"type": "integer"}, "question": {"type": "string"}}, ["id", "question"]),
    "lease_port": (t_lease_port, "Get a port range for this session's dev servers and databases, so parallel "
                   "sessions never fight over the same port.", {}, []),
    "resume": (t_resume, "Start of a new session: returns this account's last saved context summary, your claimed "
               "tasks with notes, guidance, and the board.", {}, []),
}


def run_tool(name, args):
    try:
        text, err = TOOLS[name][0](args), False
    except (ValueError, KeyError, TypeError) as e:
        text, err = f"Error: {e}", True
    return text + touch_session(name), err


# ---------- MCP stdio (newline-delimited JSON-RPC) ----------

def reply(i, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": i}
    if error:
        msg["error"] = error
    else:
        msg["result"] = result
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def handle(m):
    meth, i, p = m.get("method"), m.get("id"), m.get("params") or {}
    if i is None:
        return  # notification
    if meth == "initialize":
        reply(i, {"protocolVersion": p.get("protocolVersion", "2025-06-18"),
                  "capabilities": {"tools": {}},
                  "serverInfo": {"name": "coshift", "version": "1.0"},
                  "instructions": INSTRUCTIONS})
    elif meth == "ping":
        reply(i, {})
    elif meth == "tools/list":
        reply(i, {"tools": [{"name": n, "description": d,
                             "inputSchema": {"type": "object", "properties": props, "required": req}}
                            for n, (_, d, props, req) in TOOLS.items()]})
    elif meth == "tools/call":
        if p.get("name") not in TOOLS:
            return reply(i, error={"code": -32602, "message": f"unknown tool {p.get('name')}"})
        text, err = run_tool(p["name"], p.get("arguments") or {})
        reply(i, {"content": [{"type": "text", "text": text}], "isError": err})
    else:
        reply(i, error={"code": -32601, "message": f"method not found: {meth}"})


def serve():
    for line in sys.stdin:
        if line.strip():
            try:
                handle(json.loads(line))
            except json.JSONDecodeError:
                pass


# ---------- web page for the user (127.0.0.1 only) ----------

def second_window_open():
    try:
        out = subprocess.run([SWITCH, "status"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    return any(l.startswith("Side-by-side") and "running" in l for l in out.splitlines())


def app_usage():
    """Latest usage sample the desktop app itself saved for each profile (plan-usage-history.json),
    keyed by org id, so the page shows every account before any session reports."""
    try:
        with open(os.path.join(PROFILES, ".active"), encoding="utf-8") as f:
            active = f.read().strip() or "active"
    except OSError:
        active = "active"
    try:
        with open(NAMES, encoding="utf-8") as f:
            names = json.load(f)
    except (OSError, ValueError):
        names = {}
    folders = [(active, LIVE)]
    if os.path.isdir(PROFILES):
        folders += [(n, os.path.join(PROFILES, n, "data")) for n in sorted(os.listdir(PROFILES))
                    if not n.startswith((".", "_"))]
    out = {}
    for name, d in folders:
        try:
            with open(os.path.join(d, "plan-usage-history.json"), encoding="utf-8") as f:
                smp = json.load(f)["samples"][-1]
            org, u, at = smp["org"], smp["u"], smp["t"] / 1000
        except (OSError, ValueError, KeyError, IndexError, TypeError):
            continue
        shown = names.get(name, name)
        shown = shown.get("name", name) if isinstance(shown, dict) else shown
        if org not in out or at > out[org]["at"]:
            out[org] = {"profile": shown, "five_hour_pct": int(u.get("fh", 0)), "weekly_pct": int(u.get("sd", 0)),
                        "five_hour_resets": "", "weekly_resets": "", "at": at}
    return out


def resets_in(t):
    m = max(0, int((t - now()) // 60))
    return f"{m // 1440}d {m % 1440 // 60}h" if m >= 1440 else f"{m // 60}h {m % 60}m"


def usage_app_usage():
    """Live numbers from the Claude Usage menu bar app (it refreshes every ~30 s), keyed by org id.
    Reads only each profile's name, org id and usage percentages/reset times, never its keys."""
    if not USAGE_APP:
        return {}
    try:
        raw = subprocess.run(["/usr/bin/defaults", "export", USAGE_APP, "-"], capture_output=True, timeout=5).stdout
        profiles = plistlib.loads(raw).get("profiles_v3")
        profiles = json.loads(profiles) if isinstance(profiles, (bytes, str)) else profiles
    except (OSError, ValueError, subprocess.TimeoutExpired, plistlib.InvalidFileException):
        return {}
    out = {}
    for p in profiles or []:
        u, org = p.get("claudeUsage") or {}, p.get("organizationId")
        if not org or "lastUpdated" not in u:
            continue
        out[org] = {"profile": str(p.get("name", "")).replace(" (Claude)", ""),
                    "five_hour_pct": int(u.get("sessionPercentage", 0)), "weekly_pct": int(u.get("weeklyPercentage", 0)),
                    "five_hour_resets": resets_in(u["sessionResetTime"] + APPLE_EPOCH) if "sessionResetTime" in u else "",
                    "weekly_resets": resets_in(u["weeklyResetTime"] + APPLE_EPOCH) if "weeklyResetTime" in u else "",
                    "at": u["lastUpdated"] + APPLE_EPOCH, "source": "usage-app"}
    return out


def outside_usage():
    """Newest usage per org from outside the board: the Claude Usage app, else the desktop app's own samples."""
    best = {}
    for org, u in app_usage().items():
        best[org] = dict(u, source="desktop")
    for org, u in usage_app_usage().items():
        label = best.get(org, {}).get("profile") or u["profile"]  # keep the menu bar's display name
        if org not in best or u["at"] > best[org]["at"]:
            best[org] = dict(u, profile=label)
    return best


def accounts_view(usage):
    """One card per account: whichever is newest of the session's own report and the outside sources."""
    apps, cards = outside_usage(), []
    for email, u in usage.items():
        app = apps.pop(u.get("org"), None) if u.get("org") else None
        src = app if app and app["at"] > u["at"] else u
        cards.append(dict(src, email=email, profile=(app or {}).get("profile", ""),
                          source=src["source"] if src is app else "session"))
    cards += [dict(a, email="") for a in apps.values()]
    for c in cards:
        c["stop"], c["age_min"] = over_limit(c), int((now() - c["at"]) // 60)
    return cards


def web_state():
    with board() as b:
        usage = {k: dict(v, stop=over_limit(v), age_min=int((now() - v["at"]) // 60)) for k, v in b["usage"].items()}
        sessions = sorted(({"id": k, **v, "age_min": int((now() - v["last"]) // 60),
                            "task": next((f"#{t['id']} {t['title']}" for t in b["tasks"]
                                          if t["status"] == "claimed" and t.get("session") == k), "")}
                           for k, v in b["sessions"].items() if now() - v["last"] < 3 * 3600),
                          key=lambda x: x["last"], reverse=True)
        tasks = [dict(t, stale=t["status"] == "claimed" and now() - last_seen(b, t) > STALE_CLAIM_MIN * 60,
                      blocked=blockers(b, t) if t["status"] == "open" else []) for t in b["tasks"]]
        return {"stop_5h": STOP_5H, "stop_week": STOP_WEEK, "usage": usage, "accounts": accounts_view(b["usage"]),
                "sessions": sessions,
                "settings": dict(settings_of(b), context_windows=b.get("settings", {}).get("context_windows", {})),
                "tasks": tasks, "messages": b["messages"][-20:],
                "guidance": [g for g in b["guidance"] if g["active"]], "second_window": second_window_open(),
                "stop_context": STOP_CONTEXT,
                "contexts": {k: v[-1] for k, v in b.get("contexts", {}).items() if v}}


def web_post(path, a):
    """Actions from the page. Never deletes: cancel just hides a task from the queue."""
    if path == "/api/task":
        if not a.get("title", "").strip():
            raise ValueError("title is required")
        global ME
        me, ME = ME, "you"
        try:
            return t_add_task(a)
        finally:
            ME = me
    if path == "/api/message":
        if not a.get("text", "").strip():
            raise ValueError("message is empty")
        with board(write=True) as b:
            b["messages"].append({"t": now(), "to": a.get("to") or "all", "text": a["text"].strip(), "read_by": []})
        return "Sent. It's delivered with that account's next board tool call."
    if path == "/api/guidance":
        if not a.get("text", "").strip():
            raise ValueError("guidance is empty")
        with board(write=True) as b:
            gid = b.setdefault("next_gid", 1)
            b["next_gid"] = gid + 1
            b["guidance"].append({"id": gid, "t": now(), "to": a.get("to") or "all", "text": a["text"].strip(),
                                  "active": True, "read_by": []})
        return "Guidance saved. It applies from each account's next board action."
    if path.startswith("/api/guidance/") and path.endswith("/remove"):
        gid = path.split("/")[3]
        with board(write=True) as b:
            g = next((x for x in b["guidance"] if str(x["id"]) == gid), None)
            if not g:
                raise ValueError("no such guidance")
            g["active"] = False  # kept in the file, just no longer shown to sessions
        return "Guidance removed."
    if path == "/api/settings":
        with board(write=True) as b:
            wins = a.pop("context_windows", {}) or {}
            done = {k: set_setting(b, k, v) for k, v in a.items()}
            done.update({f"context_window[{acct}]": set_setting(b, "context_window", v, acct) for acct, v in wins.items()})
        return "Saved: " + ", ".join(f"{k} = {v}" for k, v in done.items()) if done else "Nothing to change."
    if path == "/api/open-second":
        r = subprocess.run([SWITCH, "side-by-side"], capture_output=True, text=True, timeout=60)
        if r.returncode:
            raise ValueError((r.stdout + r.stderr).strip() or "claude-switch failed")
        return r.stdout.strip()
    parts = path.strip("/").split("/")  # api/task/<id>/<action>
    if len(parts) == 4 and parts[:2] == ["api", "task"] and parts[2].isdigit():
        with board(write=True) as b:
            t = find(b, int(parts[2]))
            if parts[3] == "note":
                if not a.get("text", "").strip():
                    raise ValueError("note is empty")
                note(t, "you", a["text"].strip())
            elif parts[3] == "reopen":
                t["status"], t["owner"] = "open", ""
                note(t, "you", "reopened by user")
            elif parts[3] == "cancel":
                t["status"], t["owner"] = "cancelled", ""
                note(t, "you", "cancelled by user")
            elif parts[3] == "answer":
                ans = a.get("text", "").strip()
                if not ans:
                    raise ValueError("answer is empty")
                q = (t.get("needs_input") or {}).get("q", "")
                b["messages"].append({"t": now(), "to": t["owner"] or "all", "read_by": [],
                                      "text": f"Answer to your question on task #{t['id']}"
                                              + (f' ("{q}")' if q else "") + f": {ans}"})
                note(t, "you", f"answer: {ans}")
                t.pop("needs_input", None)
            else:
                raise ValueError("unknown action")
        return f"Task #{t['id']} updated."
    raise ValueError("unknown endpoint")


def web(port):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    allowed = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send(self, code, body, ctype="application/json"):
            data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def trusted(self):
            # Blocks DNS-rebinding (Host) and other websites posting here (Origin + JSON-only bodies).
            if self.headers.get("Host") not in allowed:
                return False
            origin = self.headers.get("Origin")
            return origin is None or origin.split("//", 1)[-1] in allowed

        def do_GET(self):
            if not self.trusted():
                return self.send(403, {"error": "forbidden"})
            self.path = self.path.split("?")[0]  # e.g. /?theme=light
            if self.path == "/":
                with open(PAGE, encoding="utf-8") as f:
                    return self.send(200, f.read(), "text/html; charset=utf-8")
            if self.path == "/api/board":
                return self.send(200, web_state())
            self.send(404, {"error": "not found"})

        def do_POST(self):
            self.path = self.path.split("?")[0]
            if not self.trusted() or not self.headers.get("Content-Type", "").startswith("application/json"):
                return self.send(403, {"error": "forbidden"})
            try:
                n = int(self.headers.get("Content-Length") or 0)
                a = json.loads(self.rfile.read(n) or b"{}") if n <= 100_000 else {}
                self.send(200, {"ok": web_post(self.path, a)})
            except (ValueError, KeyError, subprocess.TimeoutExpired) as e:
                self.send(400, {"error": str(e)})

    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()


def web_running(port):
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def web_open(port):
    """Opens the hosted board if remote.json names one; otherwise starts the local page if needed and opens it."""
    if REMOTE.get("url"):
        return webbrowser.open(REMOTE["url"])
    if not web_running(port):
        os.makedirs(HOME, mode=0o700, exist_ok=True)
        with open(os.path.join(HOME, "web.log"), "a") as log:
            subprocess.Popen([sys.executable, os.path.abspath(__file__), "web", str(port)],
                             stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
        for _ in range(50):
            if web_running(port):
                break
            time.sleep(0.1)
    webbrowser.open(f"http://127.0.0.1:{port}/")


def push_usage():
    """Copies every account's live usage (Claude Usage app / desktop app) into the shared board,
    under the account names from remote.json. Run every minute by a LaunchAgent on the Mac."""
    names = REMOTE.get("accounts", {})
    live = {names[org]: u for org, u in outside_usage().items() if org in names}
    if not live:
        print("no usage found for the accounts in remote.json")
        return 1
    with board(write=True) as b:
        for name, u in live.items():
            old = b["usage"].get(name)
            if not old or u["at"] >= old["at"]:
                b["usage"][name] = {k: u[k] for k in ("five_hour_pct", "weekly_pct", "five_hour_resets",
                                                      "weekly_resets", "at")} | {"org": next(o for o, n in names.items() if n == name)}
    print("pushed: " + ", ".join(f"{n} {u['five_hour_pct']}%/{u['weekly_pct']}%" for n, u in live.items()))
    return 0


def tray_accounts(b):
    """Board usage, plus live numbers from this computer (Claude Usage app / Claude desktop app) for accounts the
    board doesn't know yet, labelled with their menu bar display names. Newest wins."""
    acc = {k.upper(): dict(v, name=k) for k, v in b["usage"].items()}
    for u in outside_usage().values():
        name = (u.get("profile") or "").upper()
        if name and (name not in acc or u["at"] > acc[name]["at"]):
            acc[name] = dict(u, name=name)
    return [{"name": v["name"], "five_hour_pct": v.get("five_hour_pct"), "weekly_pct": v.get("weekly_pct"),
             "age_min": int((now() - v["at"]) // 60), "stop": over_limit(v)} for _, v in sorted(acc.items())]


def ingest_statusline(d):
    """One Claude Code status-line update (its documented JSON) for account COSHIFT_AS: plan usage, the session's
    context, and the account's real context window size. Works the same on Windows, macOS and Linux."""
    me = (os.environ.get("COSHIFT_AS") or "").upper()
    if not me:
        return 0
    rl, cw = d.get("rate_limits") or {}, d.get("context_window") or {}
    fh, sd = rl.get("five_hour") or {}, rl.get("seven_day") or {}
    sid = d.get("session_id") or SID
    with board(write=True) as b:
        if fh or sd:
            b["usage"][me] = {"five_hour_pct": round(fh.get("used_percentage") or 0),
                              "weekly_pct": round(sd.get("used_percentage") or 0),
                              "five_hour_resets": resets_in(fh["resets_at"]) if fh.get("resets_at") else "",
                              "weekly_resets": resets_in(sd["resets_at"]) if sd.get("resets_at") else "",
                              "at": now(), "source": "statusline"}
        if cw.get("context_window_size"):
            b.setdefault("settings", {}).setdefault("context_windows", {})[me] = int(cw["context_window_size"])
        if cw.get("used_percentage") is not None:
            b["sessions"].setdefault(sid, {}).update(account=me, cwd=(d.get("workspace") or {}).get("current_dir") or CWD,
                                                     last=now(), context_pct=round(cw["used_percentage"]), context_at=now())
    return 0


# ---------- CLI for the user ----------

def cli(argv):
    global ME
    if argv[:1] == ["call"]:
        # Same tools as the MCP server, for sessions that started before the board was registered.
        if len(argv) < 2 or argv[1] == "help":
            print(INSTRUCTIONS.replace("call get_usage", "use your get_usage tool") + "\n\nTools (run: board.py call <tool> '<json args>'):")
            for n, (_, d, props, req) in TOOLS.items():
                print(f"  {n} {json.dumps({k: v['type'] for k, v in props.items()}) if props else ''}  (required: {', '.join(req) or 'none'})\n      {d}")
            return 0
        if argv[1] not in TOOLS:
            print(f"unknown tool {argv[1]}; run: board.py call help")
            return 1
        try:
            args = json.loads(argv[2]) if len(argv) > 2 else {}
        except ValueError as e:
            print(f"arguments must be JSON: {e}")
            return 1
        text, err = run_tool(argv[1], args)
        print(text)
        return 1 if err else 0
    ME = ME or "you"
    cmd = argv[0] if argv else "show"
    if cmd == "show":
        with board() as b:
            print(render(b))
    elif cmd == "add" and len(argv) >= 2:
        print(t_add_task({"title": argv[1], "detail": argv[2] if len(argv) > 2 else ""}))
    elif cmd == "settings":
        with board(write=len(argv) > 1) as b:
            if len(argv) in (4, 5) and argv[1] == "set":
                acct = argv[4] if len(argv) == 5 else None
                print(f"{argv[2]}{f'[{acct.upper()}]' if acct else ''} = {set_setting(b, argv[2], argv[3], acct)}")
            elif len(argv) == 1:
                print(json.dumps(dict(settings_of(b), context_windows=b.get("settings", {}).get("context_windows", {}))))
            else:
                print("usage: board.py settings [set <key> <value>]")
                return 1
    elif cmd == "usage-json":
        with board() as b:
            print(json.dumps({"usage": b["usage"], "settings": settings_of(b),
                              "windows": b.get("settings", {}).get("context_windows", {})}))
    elif cmd == "tray-json":
        # everything a tray/menu bar shows, in one small JSON
        with board() as b:
            st = settings_of(b)
            print(json.dumps({
                "url": REMOTE.get("url") or f"http://127.0.0.1:{PORT}/",
                "accounts": tray_accounts(b),
                "needs": [{"id": t["id"], "title": t["title"], "by": t["needs_input"]["by"], "q": t["needs_input"]["q"]}
                          for t in b["tasks"] if t.get("needs_input")],
                "claimed": sum(t["status"] == "claimed" for t in b["tasks"]),
                "open": sum(t["status"] == "open" for t in b["tasks"]),
                "stop_5h": st["stop_5h"], "stop_week": st["stop_week"]}))
    elif cmd == "ingest-statusline":
        return ingest_statusline(json.load(sys.stdin))
    elif cmd == "detect-accounts":
        print(json.dumps({org: {k: u[k] for k in ("profile", "five_hour_pct", "weekly_pct")}
                          for org, u in outside_usage().items()}))
    elif cmd == "reopen" and len(argv) == 2:
        with board(write=True) as b:
            t = find(b, int(argv[1]))
            t["status"], t["owner"] = "open", ""
            note(t, "you", "reopened by user")
        print(f"Task #{t['id']} reopened.")
    else:
        print('usage: board.py [show | add "title" ["detail"] | reopen <id> | settings [set k v] | detect-accounts | '
              'call <tool> [json] | serve | web [--open] | push-usage]')
        return 1
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):  # Windows defaults to a legacy code page; task titles may have emoji
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    if sys.argv[1:2] == ["serve"]:
        serve()
    elif sys.argv[1:2] == ["push-usage"]:
        sys.exit(push_usage())
    elif sys.argv[1:2] == ["web"]:
        rest = sys.argv[2:]
        port = int(next((x for x in rest if x.isdigit()), PORT))
        web_open(port) if "--open" in rest else web(port)
    else:
        try:
            sys.exit(cli(sys.argv[1:]))
        except ValueError as e:  # bad input: a clean message, no traceback
            print(e, file=sys.stderr)
            sys.exit(1)
