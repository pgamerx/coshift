#!/usr/bin/env python3
"""coshift setup → "Restore from my Vercel board": setup.py --restore rebuilds tokens.json and remote.json from the
linked project's env, with a fake `vercel` CLI. Run: python3 tests/test-restore.py"""
import json, os, shutil, stat, subprocess, sys, tempfile

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
TMP = tempfile.mkdtemp(prefix="coshift-restore.")
APP, HOME, BIN = (os.path.join(TMP, d) for d in ("app", "home", "bin"))
shutil.copytree(os.path.join(ROOT, "scripts"), os.path.join(APP, "scripts"))
shutil.copytree(os.path.join(ROOT, "board"), os.path.join(APP, "board"))
os.makedirs(os.path.join(APP, ".vercel"))
os.makedirs(BIN)
old = {"admin": "tok-admin", "WORK": "tok-work", "GPT": "tok-gpt"}
dotenv = ('KV_REST_API_URL="https://x.upstash.io"\nKV_REST_API_TOKEN="rtok"\n'
          f'COSHIFT_TOKENS="{json.dumps({t: n for n, t in old.items()}).replace(chr(34), chr(92) + chr(34))}"\n')
fake = os.path.join(BIN, "vercel")
with open(fake, "w") as f:  # `vercel env pull FILE --yes --environment production` writes FILE
    f.write(f"#!/bin/sh\n[ \"$1 $2\" = \"env pull\" ] && printf '%s' '{dotenv}' > \"$3\"\n")
os.chmod(fake, os.stat(fake).st_mode | stat.S_IEXEC)

env = {**os.environ, "PATH": BIN + os.pathsep + os.environ["PATH"], "COSHIFT_HOME": HOME}
r = subprocess.run([sys.executable, os.path.join(APP, "scripts", "setup.py"), "--restore", "--url",
                    "https://my-board.vercel.app/", "--json"], env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL)
fails = 0
def check(desc, cond, detail=""):
    global fails
    print(("PASS: " if cond else "FAIL: ") + desc + ("" if cond else f"\n      {detail}"))
    fails += 0 if cond else 1

check("restore exits 0", r.returncode == 0, r.stderr)
out = json.loads(r.stdout or "{}")
check("reports the restored accounts", sorted(out.get("accounts", [])) == ["GPT", "WORK"], r.stdout)
check("tokens.json is the old tokens", json.load(open(os.path.join(HOME, "tokens.json"))) == old)
rem = json.load(open(os.path.join(HOME, "remote.json")))
check("remote.json points at the same board and Redis",
      rem["url"] == "https://my-board.vercel.app" and rem["redis_token"] == "rtok" and rem["mode"] == "vercel", rem)
check("tokens.json is private", stat.S_IMODE(os.stat(os.path.join(HOME, "tokens.json")).st_mode) == 0o600)
check("pulled env file is deleted", not os.path.exists(os.path.join(APP, ".env.production.local")))
shutil.rmtree(TMP)
sys.exit(1 if fails else 0)
