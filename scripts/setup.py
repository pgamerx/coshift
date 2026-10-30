#!/usr/bin/env python3
"""Coshift setup engine. `coshift setup` drives it with flags; from a clone you can also run it directly:

    python3 scripts/setup.py                 # asks its questions (after `vercel link` + Upstash, see README)
    python3 scripts/setup.py --local         # board on this computer only, no Vercel

Flags (the wizard passes these): --names A,B  --url URL  --map ORG=NAME (repeatable)  --local  --json
                                 --new-tokens  --add NAME  --rotate NAME
It creates one secret token per account (plus an admin token for the page), stores them in Vercel, connects
this computer to the shared board, and writes what to paste into each cloud environment to
~/.coshift/cloud-setup.txt. Safe to re-run: existing tokens are kept unless you pass --new-tokens.
"""
import json, os, re, secrets, shutil, subprocess, sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = os.path.expanduser(os.environ.get("COSHIFT_HOME", "~/.coshift"))
sys.path.insert(0, os.path.join(REPO, "board"))
NAME_RE = r"[A-Z0-9_-]{1,20}"


def write_private(path, text):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)


def read_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


class Args:
    def __init__(self, argv):
        self.flags, self.maps, i = {}, {}, 0
        while i < len(argv):
            a = argv[i]
            if a in ("--local", "--json", "--new-tokens"):
                self.flags[a] = True
            elif a in ("--names", "--url", "--add", "--rotate", "--map") and i + 1 < len(argv):
                i += 1
                if a == "--map":
                    org, _, name = argv[i].partition("=")
                    self.maps[org] = name.upper()
                else:
                    self.flags[a] = argv[i]
            else:
                sys.exit(f"unknown argument {a}")
            i += 1

    def get(self, k, default=None):
        return self.flags.get(k, default)


ARGS = Args(sys.argv[1:])


def say(*a):
    print(*a, file=sys.stderr if ARGS.get("--json") else sys.stdout)


def ask(q, default=""):
    if not sys.stdin.isatty():
        return default
    a = input(f"{q}{f' [{default}]' if default else ''}: ").strip()
    return a or default


def vercel(*args, **kw):
    return subprocess.run(["vercel", *args], cwd=REPO, text=True, capture_output=True, **kw)


def parse_names(raw):
    names = [n.strip().upper() for n in raw.split(",") if n.strip()]
    if not names or any(not re.fullmatch(NAME_RE, n) for n in names) or "ADMIN" in names or len(set(names)) < len(names):
        sys.exit("Account names: 1-20 letters, digits, - or _, all different (and not ADMIN).")
    return names


def map_accounts(remote, accounts):
    """Which local Claude account (org id) is which name, for live usage and desktop-session identity."""
    mapping = dict(remote.get("accounts", {}))
    mapping.update({o: n for o, n in ARGS.maps.items() if n in accounts})
    if not ARGS.maps and sys.stdin.isatty():
        import board
        found = board.outside_usage()  # Claude desktop app / Claude Usage app, if present
        if found:
            say("\nClaude accounts found on this computer (for live usage):")
            for org, u in found.items():
                pick = ask(f"  {u.get('profile') or org[:8]} ({u['five_hour_pct']}% 5-hour, {u['weekly_pct']}% weekly) "
                           f"is which account? ({'/'.join(accounts)}, blank to skip)", mapping.get(org, "")).upper()
                if pick in accounts:
                    mapping[org] = pick
    return {o: n for o, n in mapping.items() if n in accounts}


def link_board():
    """A stable path to board.py for the menu bar app, trays and desktop MCP (copied on Windows)."""
    link = os.path.join(HOME, "board.py")
    src = os.path.join(REPO, "board", "board.py")
    if os.path.islink(link) or os.path.exists(link):
        os.remove(link)
    try:
        os.symlink(src, link)
    except (OSError, NotImplementedError):  # Windows without symlink rights
        shutil.copy(src, link)
    return link


def push_tokens(tokens):
    value = json.dumps({t: n for n, t in tokens.items()})
    for env in ("production", "preview"):
        r = vercel("env", "add", "COSHIFT_TOKENS", env, "--force", input=value)
        if r.returncode:
            sys.exit(f"vercel env add failed ({env}): {r.stderr.strip()[-300:]}")


def write_cloud_setup(url, tokens):
    accounts = [n for n in tokens if n != "admin"]
    host = url.split("//")[-1].split("/")[0]
    lines = ["COSHIFT - CLOUD SETUP (private: tokens are passwords for your board)\n",
             f"Board page: {url}\n  Admin key (the page asks once): {tokens['admin']}\n",
             "In claude.ai/code, open each account's cloud environment settings:\n"]
    for n in accounts:
        lines.append(f"{n} -> Environment variables:\nCOSHIFT_URL={url}\nCOSHIFT_TOKEN={tokens[n]}\n")
    lines.append(f"Every environment -> Network access: allow {host}\n")
    path = os.path.join(HOME, "cloud-setup.txt")
    write_private(path, "\n".join(lines))
    return path


def finish(result):
    if ARGS.get("--json"):
        print(json.dumps(result))
    return 0


def setup_local():
    remote_path = os.path.join(HOME, "remote.json")
    remote = read_json(remote_path, {})
    names = parse_names(ARGS.get("--names") or ask("Names for your accounts, comma separated", "ATLAS,FORGE"))
    remote = {"mode": "local", "names": names, "accounts": map_accounts(remote, names)}
    write_private(remote_path, json.dumps(remote, indent=1))
    link = link_board()
    say(f"Local board ready for {', '.join(names)}. Open it with: coshift web --open")
    return finish({"mode": "local", "accounts": names, "mapped": remote["accounts"], "link": link,
                   "python": sys.executable})


def change_token(tokens, tok_path):
    """--add NAME / --rotate NAME on an existing Vercel setup."""
    name = (ARGS.get("--add") or ARGS.get("--rotate")).upper()
    if not re.fullmatch(NAME_RE, name) or name == "ADMIN":
        sys.exit("Account names: 1-20 letters, digits, - or _ (and not ADMIN).")
    if ARGS.get("--add") and name in tokens:
        sys.exit(f"{name} already exists. To give it a new token: coshift account rotate {name}")
    if ARGS.get("--rotate") and name not in tokens:
        sys.exit(f"no account {name}. Accounts: {', '.join(n for n in tokens if n != 'admin')}")
    tokens[name] = secrets.token_urlsafe(32)
    write_private(tok_path, json.dumps(tokens, indent=1))
    push_tokens(tokens)
    url = read_json(os.path.join(HOME, "remote.json"), {}).get("url", "https://<project>.vercel.app")
    path = write_cloud_setup(url, tokens)
    say(f"{'Added' if ARGS.get('--add') else 'New token for'} {name}. Redeploy, then update its cloud environment.")
    return finish({"mode": "vercel", "changed": name, "setup_txt": path, "accounts": [n for n in tokens if n != "admin"]})


def main():
    os.makedirs(HOME, mode=0o700, exist_ok=True)
    if ARGS.get("--local"):
        return setup_local()
    if not os.path.isdir(os.path.join(REPO, ".vercel")):
        sys.exit("Link the Vercel project first: vercel link   (then add Upstash, see README). "
                 "Or keep the board on this computer: --local")

    tok_path = os.path.join(HOME, "tokens.json")
    tokens = {} if ARGS.get("--new-tokens") else read_json(tok_path, {})
    if ARGS.get("--add") or ARGS.get("--rotate"):
        if not tokens:
            sys.exit("no accounts yet. Run: coshift setup")
        return change_token(tokens, tok_path)

    # 1. accounts and tokens
    if not tokens:
        names = parse_names(ARGS.get("--names") or ask("Names for your accounts, comma separated", "ATLAS,FORGE"))
        tokens = {n: secrets.token_urlsafe(32) for n in names}
        tokens["admin"] = secrets.token_urlsafe(32)
        write_private(tok_path, json.dumps(tokens, indent=1))
    accounts = [n for n in tokens if n != "admin"]
    say(f"Accounts: {', '.join(accounts)}  (tokens in {tok_path})")

    # 2. tokens to Vercel (the server maps token -> account)
    push_tokens(tokens)
    say("Stored COSHIFT_TOKENS in Vercel.")

    # 3. this computer -> the shared board (Redis credentials from Vercel)
    env_file = os.path.join(REPO, ".env.local")
    vercel("env", "pull", env_file, "--yes")
    kv = {}
    if os.path.exists(env_file):
        with open(env_file) as f:
            kv = dict(re.findall(r'^(KV_REST_API_URL|KV_REST_API_TOKEN)="?([^"\n]*)"?', f.read(), re.M))
    if len(kv) < 2:
        sys.exit("No Upstash credentials in the Vercel project. Add it first: vercel integration add upstash/upstash-kv")
    remote_path = os.path.join(HOME, "remote.json")
    remote = read_json(remote_path, {})
    url = (ARGS.get("--url") or ask("Your board's URL (after `vercel deploy --prod`)",
           remote.get("url") or os.environ.get("COSHIFT_DEFAULT_URL") or "https://<project>.vercel.app")).rstrip("/")
    remote.update(mode="vercel", url=url, redis_url=kv["KV_REST_API_URL"], redis_token=kv["KV_REST_API_TOKEN"],
                  accounts=map_accounts(remote, accounts))
    write_private(remote_path, json.dumps(remote, indent=1))

    link = link_board()
    setup_txt = write_cloud_setup(url, tokens)
    if not os.environ.get("COSHIFT_CLI"):
        say(f"\nDone. Next:\n  1. Deploy:              vercel deploy --prod\n"
            f"  2. Cloud environments:  see {setup_txt}\n"
            f"  3. Desktop sessions:    claude mcp add --scope user coshift -- {sys.executable} {link} serve\n"
            f"  4. Context hook:        README, setup step 3")
    return finish({"mode": "vercel", "accounts": accounts, "url": url, "setup_txt": setup_txt,
                   "mapped": remote["accounts"], "link": link, "python": sys.executable})


if __name__ == "__main__":
    sys.exit(main())
