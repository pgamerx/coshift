#!/usr/bin/env python3
"""coshift setup → "Restore from my Vercel board", with a fake `vercel` CLI and a fake Upstash:
- COSHIFT_TOKENS readable: the same tokens come back, and the board keeps a copy.
- COSHIFT_TOKENS Sensitive (Vercel hands back nothing): a new page key only; COSHIFT_TOKENS is never rewritten,
  accounts added later go to the board's storage, and the hosted API accepts them next to the env's.
Run: python3 tests/test-restore.py"""
import json, os, shutil, stat, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
sys.path.insert(0, HERE)
import fake_redis  # noqa: E402

KV = fake_redis.start()
TMP = tempfile.mkdtemp(prefix="coshift-restore.")
APP, HOME, BIN = (os.path.join(TMP, d) for d in ("app", "home", "bin"))
for d in ("scripts", "board", "api"):
    shutil.copytree(os.path.join(ROOT, d), os.path.join(APP, d))
os.makedirs(os.path.join(APP, ".vercel"))
os.makedirs(BIN)
DOTENV, LOG = os.path.join(TMP, "dotenv"), os.path.join(TMP, "vercel.log")
fake = os.path.join(BIN, "fake_vercel.py")
with open(fake, "w") as f:  # logs every call; `env pull FILE ...` copies DOTENV to FILE
    f.write("import shutil, sys\n"
            f"open({LOG!r}, 'a').write(' '.join(sys.argv[1:]) + '\\n')\n"
            f"if sys.argv[1:3] == ['env', 'pull']: shutil.copy({DOTENV!r}, sys.argv[3])\n")
if os.name == "nt":
    with open(os.path.join(BIN, "vercel.cmd"), "w") as f:
        f.write(f'@"{sys.executable}" "{fake}" %*\n')
else:
    with open(os.path.join(BIN, "vercel"), "w") as f:
        f.write(f'#!/bin/sh\nexec "{sys.executable}" "{fake}" "$@"\n')
    os.chmod(os.path.join(BIN, "vercel"), 0o755)

ENV = {**os.environ, "PATH": BIN + os.pathsep + os.environ["PATH"], "COSHIFT_HOME": HOME}
fails = 0


def check(desc, cond, detail=""):
    global fails
    print(("PASS: " if cond else "FAIL: ") + desc + ("" if cond else f"\n      {str(detail)[:400]}"))
    fails += 0 if cond else 1


def dotenv(tokens_value):
    with open(DOTENV, "w") as f:
        f.write(f'KV_REST_API_URL="{KV}"\nKV_REST_API_TOKEN="x"\n'
                f'COSHIFT_TOKENS="{tokens_value.replace(chr(34), chr(92) + chr(34))}"\n')


def setup(*args):
    return subprocess.run([sys.executable, os.path.join(APP, "scripts", "setup.py"), *args, "--json"], env=ENV,
                          capture_output=True, text=True, stdin=subprocess.DEVNULL)


def home(name):
    return json.load(open(os.path.join(HOME, name)))


def stored():
    return json.loads(fake_redis.DB.get("cs:tokens") or "{}")


def vercel_writes():
    return [l for l in open(LOG).read().splitlines() if l.startswith("env add")] if os.path.exists(LOG) else []


# ---- 1. COSHIFT_TOKENS readable ----
old = {"admin": "tok-admin", "WORK": "tok-work", "GPT": "tok-gpt"}
dotenv(json.dumps({t: n for n, t in old.items()}))
r = setup("--restore", "--url", "https://my-board.vercel.app/")
check("restore exits 0", r.returncode == 0, r.stderr)
out = json.loads(r.stdout or "{}")
check("reports the restored accounts", sorted(out.get("accounts", [])) == ["GPT", "WORK"], r.stdout)
check("tokens.json is the old tokens", home("tokens.json") == old)
rem = home("remote.json")
check("remote.json points at the same board and Redis",
      rem["url"] == "https://my-board.vercel.app" and rem["redis_url"] == KV and "tokens" not in rem, rem)
check("the board keeps a copy of the tokens", stored() == old, stored())
check("tokens.json is private", os.name == "nt" or stat.S_IMODE(os.stat(os.path.join(HOME, "tokens.json")).st_mode) == 0o600)
check("pulled env file is deleted", not os.path.exists(os.path.join(APP, ".env.production.local")))

# ---- 2. Sensitive COSHIFT_TOKENS, no copy on the board (set up before 0.6.6) ----
fake_redis.DB.clear()
shutil.rmtree(HOME)
dotenv("")
r = setup("--restore", "--url", "https://my-board.vercel.app")
check("restore without readable tokens still connects", r.returncode == 0, r.stderr + r.stdout)
out = json.loads(r.stdout or "{}")
toks = home("tokens.json")
check("a new page key only", list(toks) == ["admin"] and out.get("board_tokens") is True, toks)
check("the page key is on the board", stored() == toks, stored())
check("remote.json says tokens live on the board", home("remote.json").get("tokens") == "board")
check("COSHIFT_TOKENS in Vercel is never rewritten", vercel_writes() == [], vercel_writes())

r = setup("--add", "NEWBIE")
check("account add works", r.returncode == 0, r.stderr)
check("the new account's token is on the board, next to the page key",
      set(stored()) == {"admin", "NEWBIE"} and stored()["NEWBIE"] == home("tokens.json")["NEWBIE"], stored())
check("account add still never rewrites COSHIFT_TOKENS", vercel_writes() == [], vercel_writes())

# ---- 3. the hosted API accepts the env's tokens and the board's ----
os.environ.update(KV_REST_API_URL=KV, KV_REST_API_TOKEN="x", COSHIFT_TOKENS=json.dumps({"tok-old": "OLDCLOUD"}),
                  COSHIFT_HOME=HOME)
sys.path.insert(0, os.path.join(APP, "api"))
import index as api  # noqa: E402


class Req:
    def __init__(self, tok):
        self.headers = {"Authorization": f"Bearer {tok}"}


who = lambda tok: api.handler.who(Req(tok))  # noqa: E731
check("an old cloud session's token (env) still works", who("tok-old") == "OLDCLOUD")
check("the new account's token (board) works", who(home("tokens.json")["NEWBIE"]) == "NEWBIE")
check("this computer's page key works as admin", who(home("tokens.json")["admin"]) == "admin")
check("a wrong token doesn't", who("nope") is None and who("") is None)

shutil.rmtree(TMP)
print(f"== failures: {fails}")
sys.exit(1 if fails else 0)
