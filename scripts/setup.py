#!/usr/bin/env python3
"""Coshift setup. Run from the repo root after `vercel link` and adding Upstash (see README):

    python3 scripts/setup.py

It asks for your account names, creates one secret token per account (plus an admin token for the
page), stores them in Vercel, connects this Mac to the shared board, and writes everything you need
to paste into each account's cloud environment to ~/.coshift/cloud-setup.txt. Safe to re-run: existing
tokens are kept unless you pass --new-tokens.
"""
import json, os, re, secrets, subprocess, sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = os.path.expanduser(os.environ.get("COSHIFT_HOME", "~/.coshift"))
sys.path.insert(0, os.path.join(REPO, "board"))


def write_private(path, text):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)


def ask(q, default=""):
    a = input(f"{q}{f' [{default}]' if default else ''}: ").strip()
    return a or default


def vercel(*args, **kw):
    return subprocess.run(["vercel", *args], cwd=REPO, text=True, capture_output=True, **kw)


def main():
    os.makedirs(HOME, mode=0o700, exist_ok=True)
    if not os.path.isdir(os.path.join(REPO, ".vercel")):
        sys.exit("Link the Vercel project first: vercel link   (then add Upstash, see README)")

    # 1. accounts and tokens
    tok_path = os.path.join(HOME, "tokens.json")
    tokens = {} if "--new-tokens" in sys.argv or not os.path.exists(tok_path) else json.load(open(tok_path))
    if not tokens:
        names = ask("Names for your accounts, comma separated (letters/digits)", "ATLAS,FORGE")
        names = [n.strip().upper() for n in names.split(",") if n.strip()]
        if not names or any(not re.fullmatch(r"[A-Z0-9_-]{1,20}", n) for n in names) or "ADMIN" in names:
            sys.exit("Use 1-20 letters, digits, - or _ per name (and not ADMIN).")
        tokens = {n: secrets.token_urlsafe(32) for n in names} | {"admin": secrets.token_urlsafe(32)}
        write_private(tok_path, json.dumps(tokens, indent=1))
    accounts = [n for n in tokens if n != "admin"]
    print(f"Accounts: {', '.join(accounts)}  (tokens in {tok_path})")

    # 2. tokens to Vercel (the server maps token -> account)
    value = json.dumps({t: n for n, t in tokens.items()})
    for env in ("production", "preview"):
        r = vercel("env", "add", "COSHIFT_TOKENS", env, "--force", input=value)
        if r.returncode:
            sys.exit(f"vercel env add failed ({env}): {r.stderr.strip()[-300:]}")
    print("Stored COSHIFT_TOKENS in Vercel.")

    # 3. this Mac -> the shared board (Redis credentials from Vercel)
    env_file = os.path.join(REPO, ".env.local")
    vercel("env", "pull", env_file, "--yes")
    kv = dict(re.findall(r'^(KV_REST_API_URL|KV_REST_API_TOKEN)="?([^"\n]*)"?', open(env_file).read(), re.M)) \
        if os.path.exists(env_file) else {}
    if len(kv) < 2:
        sys.exit("No Upstash credentials in the Vercel project. Add it first: vercel integration add upstash/upstash-kv")
    remote_path = os.path.join(HOME, "remote.json")
    remote = json.load(open(remote_path)) if os.path.exists(remote_path) else {}
    url = ask("Your board's URL (after `vercel deploy --prod`)",
              remote.get("url") or os.environ.get("COSHIFT_DEFAULT_URL") or "https://<project>.vercel.app")
    remote.update(url=url.rstrip("/"), redis_url=kv["KV_REST_API_URL"], redis_token=kv["KV_REST_API_TOKEN"])

    # 4. optional: which local Claude account (org) is which name, for live usage from this Mac
    import board
    found = board.outside_usage()  # Claude desktop app / Claude Usage app, if present
    if found:
        print("\nClaude accounts found on this Mac (for live usage):")
        mapping = remote.get("accounts", {})
        for org, u in found.items():
            label = u.get("profile") or org[:8]
            pick = ask(f"  {label} ({u['five_hour_pct']}% 5-hour, {u['weekly_pct']}% weekly) is which account? "
                       f"({'/'.join(accounts)}, blank to skip)", mapping.get(org, ""))
            if pick.upper() in accounts:
                mapping[org] = pick.upper()
        remote["accounts"] = mapping
    write_private(remote_path, json.dumps(remote, indent=1))

    # 5. stable path for the menu bar app and desktop MCP
    link = os.path.join(HOME, "board.py")
    if os.path.islink(link) or not os.path.exists(link):
        if os.path.islink(link):
            os.remove(link)
        os.symlink(os.path.join(REPO, "board", "board.py"), link)

    # 6. usage pusher LaunchAgent file (you load it yourself; see the printed command)
    plist = os.path.join(HOME, "local.coshift.push-usage.plist")
    write_private(plist, f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>Label</key><string>local.coshift.push-usage</string>
	<key>ProgramArguments</key>
	<array><string>/usr/bin/python3</string><string>{link}</string><string>push-usage</string></array>
	<key>StartInterval</key><integer>60</integer>
	<key>RunAtLoad</key><true/>
	<key>StandardOutPath</key><string>{HOME}/push.log</string>
	<key>StandardErrorPath</key><string>{HOME}/push.log</string>
</dict>
</plist>
""")

    # 7. what to paste where
    host = url.split("//")[-1].split("/")[0]
    lines = [f"COSHIFT - CLOUD SETUP (private: tokens are passwords for your board)\n",
             f"Board page: {url}\n  Admin key (the page asks once): {tokens['admin']}\n",
             "In claude.ai/code, open each account's cloud environment settings:\n"]
    for n in accounts:
        lines.append(f"{n} -> Environment variables:\nCOSHIFT_URL={url}\nCOSHIFT_TOKEN={tokens[n]}\n")
    lines.append(f"Every environment -> Network access: allow {host}\n")
    setup_txt = os.path.join(HOME, "cloud-setup.txt")
    write_private(setup_txt, "\n".join(lines))

    steps = [] if os.environ.get("COSHIFT_CLI") else [("Deploy:", "vercel deploy --prod")]
    steps += [("Cloud environments:", f"cat {setup_txt}"),
              ("Live usage (optional):", f"cp {plist} ~/Library/LaunchAgents/ && launchctl bootstrap gui/$(id -u) "
                                         "~/Library/LaunchAgents/local.coshift.push-usage.plist"),
              ("Desktop sessions (optional):", f"claude mcp add --scope user coshift -- /usr/bin/python3 {link} serve"),
              ("Context hook:", "in each project repo, have one session install it (README, setup step 3)")]
    print("\nDone. Next:\n" + "\n".join(f"  {i}. {label:<28} {cmd}" for i, (label, cmd) in enumerate(steps, 1)))

if __name__ == "__main__":
    main()
