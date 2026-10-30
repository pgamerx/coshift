#!/usr/bin/env node
// coshift: one command for the Coshift board on Windows, macOS and Linux. No dependencies.
// The board itself is Python (standard library only); this wrapper finds it inside the installed package
// and keeps a deployable copy in ~/.coshift/app.
const { spawnSync } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");
const readline = require("readline");

const PKG = path.join(__dirname, "..");
const HOME = process.env.COSHIFT_HOME || path.join(os.homedir(), ".coshift");
const APP = path.join(HOME, "app"); // what gets deployed; keeps its .vercel link across upgrades
const VERSION = require("../package.json").version;
const IS_WIN = process.platform === "win32";

// ---------- look ----------
const TTY = process.stdout.isTTY && !process.env.NO_COLOR;
const paint = (code) => (s) => (TTY ? `\x1b[${code}m${s}\x1b[0m` : String(s));
const c = {
  bold: paint("1"), dim: paint("2"), orange: paint("38;5;173"), green: paint("38;5;71"),
  yellow: paint("38;5;179"), red: paint("38;5;167"), cyan: paint("38;5;110"),
};
const sym = { ok: c.green("✓"), no: c.red("✗"), warn: c.yellow("!"), dot: c.orange("●"), arrow: c.orange("›") };
const strip = (s) => String(s).replace(/\x1b\[[0-9;]*m/g, "");

function banner(sub) {
  console.log(`\n  ${c.orange("━━")} ${c.bold("coshift")} ${c.dim(VERSION)}${sub ? c.dim("  ·  " + sub) : ""}\n`);
}
function step(n, total, title) {
  console.log(`\n  ${c.orange(`[${n}/${total}]`)} ${c.bold(title)}`);
}
function box(lines, color = c.orange) {
  const w = Math.max(...lines.map((l) => strip(l).length)) + 2;
  console.log("  " + color("╭" + "─".repeat(w) + "╮"));
  for (const l of lines) console.log("  " + color("│") + " " + l + " ".repeat(w - strip(l).length - 1) + color("│"));
  console.log("  " + color("╰" + "─".repeat(w) + "╯"));
}
const info = (s) => console.log(`  ${c.dim("·")} ${s}`);
const good = (s) => console.log(`  ${sym.ok} ${s}`);
const bad = (s) => console.log(`  ${sym.no} ${s}`);
const warn = (s) => console.log(`  ${sym.warn} ${s}`);

function die(msg) {
  console.error(`\n  ${sym.no} ${msg}\n`);
  process.exit(1);
}

// ---------- prompts (arrow keys in a terminal, plain text otherwise) ----------
async function select(question, options, defaultIndex = 0) {
  if (!process.stdin.isTTY) return options[defaultIndex].value;
  return new Promise((resolve) => {
    let i = defaultIndex;
    const draw = (first) => {
      if (!first) process.stdout.write(`\x1b[${options.length}A`);
      options.forEach((o, k) => {
        const on = k === i;
        process.stdout.write(`\x1b[2K    ${on ? sym.arrow : " "} ${on ? c.bold(o.label) : o.label}${o.hint ? c.dim("  " + o.hint) : ""}\n`);
      });
    };
    console.log(`  ${c.bold(question)} ${c.dim("(↑/↓, Enter)")}`);
    draw(true);
    readline.emitKeypressEvents(process.stdin);
    process.stdin.setRawMode(true);
    process.stdin.resume();
    const onKey = (_, key = {}) => {
      if (key.name === "up" || key.name === "k") i = (i + options.length - 1) % options.length;
      else if (key.name === "down" || key.name === "j" || key.name === "tab") i = (i + 1) % options.length;
      else if (key.name === "return") {
        process.stdin.setRawMode(false);
        process.stdin.removeListener("keypress", onKey);
        process.stdin.pause();
        return resolve(options[i].value);
      } else if (key.ctrl && key.name === "c") {
        process.stdin.setRawMode(false);
        console.log();
        process.exit(130);
      } else return;
      draw(false);
    };
    process.stdin.on("keypress", onKey);
  });
}

async function input(question, def = "") {
  if (!process.stdin.isTTY) return def;
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  const a = await new Promise((r) => rl.question(`  ${c.bold(question)}${def ? c.dim(` (${def})`) : ""} ${sym.arrow} `, r));
  rl.close();
  return a.trim() || def;
}

const confirm = async (q, yes = true) =>
  select(q, [{ label: "Yes", value: true }, { label: "No", value: false }], yes ? 0 : 1);

// ---------- running things ----------
function run(cmd, args, opts = {}) {
  const r = spawnSync(cmd, args, { stdio: "inherit", shell: IS_WIN && !/[\\/]/.test(cmd), ...opts });
  if (r.error && r.error.code === "ENOENT") return 127;
  return r.status === null ? 1 : r.status;
}
const has = (cmd) => spawnSync(IS_WIN ? "where" : "which", [cmd], { stdio: "ignore" }).status === 0;

let PY = null; // [command, ...args] of a Python 3.9+
function python() {
  if (PY) return PY;
  for (const cand of IS_WIN ? [["py", "-3"], ["python"], ["python3"]] : [["python3"], ["python"]]) {
    const r = spawnSync(cand[0], [...cand.slice(1), "-c", "import sys;print('%d %d'%sys.version_info[:2])"],
      { encoding: "utf8", shell: false });
    const [maj, min] = (r.stdout || "").trim().split(" ").map(Number);
    if (r.status === 0 && (maj > 3 || (maj === 3 && min >= 9))) return (PY = cand);
  }
  die(`Coshift needs Python 3.9 or newer. Get it from ${c.cyan("https://www.python.org/downloads/")}`);
}
const pyVersion = () => spawnSync(python()[0], [...python().slice(1), "--version"], { encoding: "utf8" }).stdout.trim() || python().join(" ");
const tokensLabel = (n) => (Number(n) >= 1e6 ? Number(n) / 1e6 + "M" : Number(n) >= 1000 ? Number(n) / 1000 + "K" : String(n));
const py = (script, args, opts) => run(python()[0], [...python().slice(1), script, ...args], opts);
function pyOut(script, args, opts = {}) {
  const r = spawnSync(python()[0], [...python().slice(1), script, ...args], { encoding: "utf8", ...opts });
  return { code: r.status, out: (r.stdout || "").trim(), err: (r.stderr || "").trim() };
}
const BOARD = path.join(PKG, "board", "board.py");

function readJson(p, d = null) {
  try { return JSON.parse(fs.readFileSync(p, "utf8")); } catch { return d; }
}
const remote = () => readJson(path.join(HOME, "remote.json"), {});
const tokens = () => readJson(path.join(HOME, "tokens.json"), {});
const mode = () => remote().mode || (remote().url ? "vercel" : remote().names ? "local" : "");

function copy(text) {
  const tool = process.platform === "darwin" ? ["pbcopy"] : IS_WIN ? ["clip"] : has("wl-copy") ? ["wl-copy"] : has("xclip") ? ["xclip", "-selection", "clipboard"] : null;
  if (!tool) return false;
  return spawnSync(tool[0], tool.slice(1), { input: text, shell: IS_WIN }).status === 0;
}

function syncApp() {
  fs.mkdirSync(APP, { recursive: true, mode: 0o700 });
  for (const p of ["api", "board", "scripts", "vercel.json", ".vercelignore"]) {
    fs.cpSync(path.join(PKG, p), path.join(APP, p), { recursive: true, force: true });
  }
}
function projectUrl() {
  const p = readJson(path.join(APP, ".vercel", "project.json"), {});
  return p.projectName ? `https://${p.projectName}.vercel.app` : "";
}

// ---------- setup wizard ----------
const OS_LABEL = { darwin: "macOS", win32: "Windows", linux: "Linux" };

async function setup(args) {
  banner("setup");
  console.log(`  Let several Claude Code accounts share one project: split tasks, hand over at limits,\n  restart from a saved summary at a context threshold.\n`);

  // 1. system
  const detected = OS_LABEL[process.platform] ? process.platform : "linux";
  const order = ["darwin", "win32", "linux"];
  step(1, 5, "Your system");
  const sys = await select("Which system is this?", order.map((k) => ({
    label: OS_LABEL[k], value: k, hint: k === detected ? "detected" : "",
  })), order.indexOf(detected));
  python();
  good(`${OS_LABEL[sys]} · ${pyVersion()} · Node ${process.versions.node}`);

  // 2. hosting
  step(2, 5, "Where the board lives");
  const host = await select("Host the board where?", [
    { label: "Vercel", value: "vercel", hint: "free · recommended · open it from any device, works with cloud sessions" },
    { label: "This computer only", value: "local", hint: "no account needed · this machine only" },
  ]);
  if (host === "local") {
    box([
      `${sym.warn} ${c.bold("This computer only")}`,
      "The board page runs at http://127.0.0.1 on this machine. You won't be able",
      "to open it from your phone or another device, and cloud sessions on",
      "claude.ai/code can't reach it. Desktop sessions on this computer can.",
      `We recommend ${c.bold("Vercel")} (free) so you can check it from anywhere.`,
      `You can switch later: ${c.cyan("coshift setup")}`,
    ], c.yellow);
    if (!(await confirm("Continue with this computer only?", true))) return setup(args);
  }

  // 3. accounts + context windows
  step(3, 5, "Your accounts");
  const prev = (remote().names || Object.keys(tokens()).filter((n) => n !== "admin")).join(",");
  const names = (await input("Name your accounts (comma separated)", prev || "ATLAS,FORGE"))
    .split(",").map((s) => s.trim().toUpperCase()).filter(Boolean);
  if (!names.length || names.some((n) => !/^[A-Z0-9_-]{1,20}$/.test(n) || n === "ADMIN") || new Set(names).size < names.length)
    die("Account names: 1-20 letters, digits, - or _, all different (and not ADMIN).");
  const windows = {};
  for (const n of names) {
    windows[n] = await select(`Context window of ${c.orange(n)}'s sessions?`, [
      { label: "200K tokens", value: 200000, hint: "Pro, and most models" },
      { label: "1M tokens", value: 1000000, hint: "Max with a 1M-context model (check with /context)" },
    ]);
  }
  const detectedAccts = (() => { try { return JSON.parse(pyOut(BOARD, ["detect-accounts"]).out || "{}"); } catch { return {}; } })();
  const maps = [];
  const orgs = Object.entries(detectedAccts);
  if (orgs.length) {
    info(`Found ${orgs.length} Claude account${orgs.length > 1 ? "s" : ""} on this computer (for live usage):`);
    for (const [org, u] of orgs) {
      const pick = await select(`${u.profile || org.slice(0, 8)} (${u.five_hour_pct}% 5-hour, ${u.weekly_pct}% weekly) is`,
        [...names.map((n) => ({ label: n, value: n })), { label: "Skip", value: "" }]);
      if (pick) maps.push("--map", `${org}=${pick}`);
    }
  }

  // 4. board
  step(4, 5, host === "vercel" ? "Create the board on Vercel" : "Create the board on this computer");
  const common = ["--names", names.join(","), ...maps, "--json"];
  let result;
  if (host === "local") {
    const r = pyOut(path.join(PKG, "scripts", "setup.py"), ["--local", ...common]);
    if (r.code) die(r.err || "setup failed");
    result = JSON.parse(r.out);
    good("Local board ready");
  } else {
    if (!has("vercel")) {
      warn(`The Vercel CLI isn't installed. Install it with ${c.cyan("npm i -g vercel")}, then run ${c.cyan("coshift setup")} again.`);
      process.exit(1);
    }
    syncApp();
    const here = { cwd: APP };
    if (!fs.existsSync(path.join(APP, ".vercel"))) {
      info("Creating a Vercel project (log in if asked)…");
      if (run("vercel", ["link"], here)) die("vercel link failed.");
    }
    const envs = spawnSync("vercel", ["env", "ls"], { cwd: APP, encoding: "utf8", shell: IS_WIN });
    if (!/KV_REST_API_URL/.test(envs.stdout || "")) {
      info("Adding free Upstash Redis storage (accept its terms when asked)…");
      if (run("vercel", ["integration", "add", "upstash/upstash-kv"], here))
        die("adding Upstash failed. Accept its terms when asked, then run coshift setup again.");
    }
    const url = await input("Board address", remote().url || projectUrl());
    info("Creating account tokens and storing them in Vercel…");
    const r = pyOut(path.join(APP, "scripts", "setup.py"), [...common, "--url", url, ...args],
      { cwd: APP, env: { ...process.env, COSHIFT_CLI: "1" } });
    if (r.code) die(r.err || "setup failed");
    result = JSON.parse(r.out);
    good("Tokens stored");
    info("Deploying…");
    if (run("vercel", ["deploy", "--prod", "--yes"], here)) die("deploy failed.");
    good(`Board live at ${c.cyan(result.url)}`);
  }
  for (const n of names) pyOut(BOARD, ["settings", "set", "context_window", String(windows[n]), n]);
  good(`Context windows saved (${names.map((n) => `${n} ${windows[n] >= 1e6 ? windows[n] / 1e6 + "M" : windows[n] / 1000 + "K"}`).join(", ")})`);

  // 5. extras
  step(5, 5, "Extras");
  if (has("claude") && (await confirm("Connect desktop Claude Code sessions on this computer to the board?", true))) {
    const r = run("claude", ["mcp", "add", "--scope", "user", "coshift", "--", result.python, result.link, "serve"], { stdio: "ignore" });
    r === 0 ? good("Desktop sessions connected (new sessions get the board tools)") : warn("Couldn't add it; it may already be there. Check: claude mcp list");
  }
  if (host === "vercel" && orgs.length && (await confirm("Send this computer's live usage to the board every minute?", true))) {
    await pusher("install");
  }

  console.log();
  const lines = [`${sym.ok} ${c.bold("Coshift is set up")}`, ""];
  if (host === "vercel") {
    lines.push(`Board      ${c.cyan(result.url)}`, `Page key   ${c.cyan("coshift env admin")}`, "",
      `Next, for each account, in claude.ai/code → environment settings:`,
      ...names.map((n) => `  ${c.orange(n.padEnd(8))} ${c.cyan(`coshift env ${n}`)}  ${c.dim("(copies its variables)")}`),
      "", `Then start a session with:`);
  } else {
    lines.push(`Board      ${c.cyan("coshift web --open")}`, "", "Start a desktop session in your project with:");
  }
  lines.push(c.dim("  Use the Coshift board: split <goal> into tasks, then claim one."));
  lines.push("", `Everything else: ${c.cyan("coshift")}`);
  box(lines);
  console.log();
}

// ---------- other commands ----------
function env(name) {
  const t = tokens();
  const url = remote().url;
  if (!mode()) die(`Not set up yet. Run: ${c.cyan("coshift setup")}`);
  if (mode() !== "vercel" || !url) die("Your board is on this computer only, so there's nothing to paste into cloud sessions.");
  const n = (name || "").toUpperCase();
  if (n === "ADMIN") {
    console.log(`\n  Page key for ${c.cyan(url)}:\n\n  ${t.admin}\n`);
    if (copy(t.admin)) good("Copied to the clipboard");
    return;
  }
  if (!t[n]) die(`Which account? ${Object.keys(t).filter((k) => k !== "admin").join(", ")}  (e.g. coshift env ${Object.keys(t)[0]})`);
  const text = `COSHIFT_URL=${url}\nCOSHIFT_TOKEN=${t[n]}`;
  const host = url.split("//")[1].split("/")[0];
  console.log(`\n  ${c.bold(n)} → claude.ai/code → environment settings\n`);
  console.log(`  ${c.dim("Environment variables:")}\n${text.split("\n").map((l) => "  " + l).join("\n")}\n`);
  console.log(`  ${c.dim("Network access:")} allow ${c.cyan(host)}\n`);
  if (copy(text)) good("Variables copied to the clipboard");
}

async function config(args) {
  const keys = {
    stop_5h: "Stop at this % of the 5-hour limit", stop_week: "Stop at this % of the weekly limit",
    stop_context: "Restart at this % of the context window", stale_min: "Minutes of silence before a claim is free",
    context_window: "Default context window (tokens)", ntfy_topic: "ntfy.sh topic for phone alerts (empty = off)",
  };
  if (args.length >= 2) {
    const r = pyOut(BOARD, ["settings", "set", ...args]);
    return r.code ? die(r.err.split("\n").pop() || r.out) : good(r.out);
  }
  const r = pyOut(BOARD, ["settings"]);
  if (r.code) die(r.err.split("\n").pop() || "couldn't read the board");
  const s = JSON.parse(r.out);
  if (!args.length && process.stdin.isTTY) {
    banner("settings");
    const pick = await select("Change which setting?", [
      ...Object.keys(keys).map((k) => ({ label: `${keys[k]}`, value: k, hint: k === "context_window" ? tokensLabel(s[k]) : String(s[k] === "" ? "off" : s[k]) })),
      ...Object.entries(s.context_windows || {}).map(([a, w]) => ({ label: `Context window of ${a}`, value: "cw:" + a, hint: tokensLabel(w) })),
      { label: "Done", value: "" },
    ]);
    if (!pick) return;
    const [k, acct] = pick.startsWith("cw:") ? ["context_window", pick.slice(3)] : [pick, null];
    const v = await input(`New value`, String(acct ? s.context_windows[acct] : s[k]));
    const out = pyOut(BOARD, ["settings", "set", k, v, ...(acct ? [acct] : [])]);
    out.code ? bad(out.err.split("\n").pop()) : good(out.out);
    return config(args);
  }
  for (const [k, label] of Object.entries(keys)) console.log(`  ${c.dim(label.padEnd(44))} ${k.padEnd(15)} ${c.bold(k === "context_window" ? tokensLabel(s[k]) : s[k] === "" ? "off" : s[k])}`);
  for (const [a, w] of Object.entries(s.context_windows || {})) console.log(`  ${c.dim(("Context window of " + a).padEnd(44))} ${"".padEnd(15)} ${c.bold(tokensLabel(w))}`);
}

async function account(args) {
  const [action, name] = args;
  if (!["add", "rotate"].includes(action) || !name) die("usage: coshift account add|rotate NAME");
  if (mode() !== "vercel") die("accounts with tokens are for a Vercel board. For a local board, run coshift setup.");
  syncApp();
  const r = pyOut(path.join(APP, "scripts", "setup.py"), [`--${action}`, name, "--json"], { cwd: APP });
  if (r.code) die(r.err.split("\n").pop());
  good(`${action === "add" ? "Added" : "New token for"} ${name.toUpperCase()}`);
  info("Deploying so the board knows…");
  if (run("vercel", ["deploy", "--prod", "--yes"], { cwd: APP, stdio: "ignore" })) die("deploy failed; run coshift deploy");
  good("Deployed");
  env(name);
}

function doctor() {
  banner("doctor");
  const check = (ok, yes, no, optional) => (ok ? good(yes) : optional ? warn(no) : bad(no)) || ok;
  const pyv = (() => { try { return pyVersion(); } catch { return ""; } })();
  check(true, `${OS_LABEL[process.platform] || process.platform} · Node ${process.versions.node}`);
  check(!!pyv, `Python: ${pyv}`, "Python 3.9+ not found");
  const m = mode();
  check(!!m, `Board: ${m === "vercel" ? remote().url : "this computer only"}`, "Not set up yet: run coshift setup");
  if (m === "vercel") {
    check(has("vercel"), "Vercel CLI installed", "Vercel CLI missing: npm i -g vercel");
    const t = tokens();
    const any = Object.entries(t).find(([k]) => k !== "admin");
    if (any) {
      const r = spawnSync(process.execPath, ["-e", `fetch(${JSON.stringify(remote().url + "/api/help")},{headers:{Authorization:"Bearer ${any[1]}"}}).then(r=>process.exit(r.status===200?0:1)).catch(()=>process.exit(2))`]);
      check(r.status === 0, `Board answers as ${any[0]}`, "Board didn't answer: run coshift deploy, or check the address");
    }
  }
  const s = pyOut(BOARD, ["settings"]);
  check(s.code === 0, "Board storage reachable", `Board storage error: ${s.err.split("\n").pop()}`);
  const accts = JSON.parse(pyOut(BOARD, ["detect-accounts"]).out || "{}");
  check(Object.keys(accts).length > 0, `Live usage: ${Object.keys(accts).length} Claude account(s) found on this computer`,
    "No live usage source on this computer (optional; sessions report their own)", true);
  if (has("claude")) {
    const r = spawnSync("claude", ["mcp", "get", "coshift"], { encoding: "utf8", shell: IS_WIN });
    check(r.status === 0, "Desktop sessions connected (MCP)", "Desktop sessions not connected: coshift setup → Extras");
  }
  console.log();
}

// ---------- usage pusher, per system ----------
async function pusher(action = "install") {
  const link = path.join(HOME, "board.py");
  const pyCmd = (() => { const r = spawnSync(python()[0], [...python().slice(1), "-c", "import sys;print(sys.executable)"], { encoding: "utf8" }); return r.stdout.trim(); })();
  if (process.platform === "darwin") {
    const plist = path.join(os.homedir(), "Library", "LaunchAgents", "local.coshift.push-usage.plist");
    const uid = process.getuid();
    if (action === "remove") {
      run("launchctl", ["bootout", `gui/${uid}/local.coshift.push-usage`], { stdio: "ignore" });
      if (fs.existsSync(plist)) fs.unlinkSync(plist);
      return good("Usage pusher removed");
    }
    fs.mkdirSync(path.dirname(plist), { recursive: true });
    fs.writeFileSync(plist, `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>local.coshift.push-usage</string>
  <key>ProgramArguments</key><array><string>${pyCmd}</string><string>${link}</string><string>push-usage</string></array>
  <key>StartInterval</key><integer>60</integer><key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>${HOME}/push.log</string><key>StandardErrorPath</key><string>${HOME}/push.log</string>
</dict></plist>\n`);
    run("launchctl", ["bootout", `gui/${uid}/local.coshift.push-usage`], { stdio: "ignore" });
    return run("launchctl", ["bootstrap", `gui/${uid}`, plist]) === 0 ? good("Usage pusher running every minute (LaunchAgent)") : bad("launchctl refused; see coshift doctor");
  }
  if (IS_WIN) {
    if (action === "remove") return run("schtasks", ["/Delete", "/TN", "Coshift usage", "/F"]) === 0 ? good("Usage pusher removed") : bad("Not found");
    const r = run("schtasks", ["/Create", "/SC", "MINUTE", "/MO", "1", "/TN", "Coshift usage", "/TR", `"${pyCmd}" "${link}" push-usage`, "/F"]);
    return r === 0 ? good("Usage pusher running every minute (Task Scheduler)") : bad("Task Scheduler refused");
  }
  // Linux: a systemd user timer when available, else cron
  const unitDir = path.join(os.homedir(), ".config", "systemd", "user");
  if (has("systemctl")) {
    if (action === "remove") {
      run("systemctl", ["--user", "disable", "--now", "coshift-usage.timer"], { stdio: "ignore" });
      for (const f of ["coshift-usage.service", "coshift-usage.timer"]) { try { fs.unlinkSync(path.join(unitDir, f)); } catch {} }
      return good("Usage pusher removed");
    }
    fs.mkdirSync(unitDir, { recursive: true });
    fs.writeFileSync(path.join(unitDir, "coshift-usage.service"), `[Unit]\nDescription=Coshift usage pusher\n\n[Service]\nType=oneshot\nExecStart=${pyCmd} ${link} push-usage\n`);
    fs.writeFileSync(path.join(unitDir, "coshift-usage.timer"), `[Unit]\nDescription=Coshift usage pusher every minute\n\n[Timer]\nOnBootSec=30\nOnUnitActiveSec=60\n\n[Install]\nWantedBy=timers.target\n`);
    run("systemctl", ["--user", "daemon-reload"]);
    return run("systemctl", ["--user", "enable", "--now", "coshift-usage.timer"]) === 0 ? good("Usage pusher running every minute (systemd timer)") : bad("systemd refused; see coshift doctor");
  }
  const line = `* * * * * "${pyCmd}" "${link}" push-usage >> "${HOME}/push.log" 2>&1 # coshift`;
  const cur = spawnSync("crontab", ["-l"], { encoding: "utf8" }).stdout || "";
  const next = cur.split("\n").filter((l) => !l.includes("# coshift")).concat(action === "remove" ? [] : [line]).filter(Boolean).join("\n") + "\n";
  return spawnSync("crontab", ["-"], { input: next }).status === 0 ? good(action === "remove" ? "Usage pusher removed" : "Usage pusher running every minute (cron)") : bad("crontab refused");
}

// ---------- accounts: one Claude Code settings folder per account (CLAUDE_CONFIG_DIR) ----------
// Claude Code keeps each folder's login separate (its own Keychain entry on macOS, its own credentials file
// elsewhere), so Coshift never reads or copies a token.
const ACCTS = path.join(HOME, "accounts");
const acctDir = (n) => path.join(ACCTS, n.toUpperCase());
const MAPS = path.join(HOME, "maps.json");

function knownAccounts() {
  const set = new Set([...(remote().names || []), ...Object.keys(tokens()).filter((k) => k !== "admin")]);
  try { for (const d of fs.readdirSync(ACCTS)) if (fs.statSync(path.join(ACCTS, d)).isDirectory()) set.add(d); } catch {}
  return [...set];
}
function acctEmail(n) {
  const j = readJson(path.join(acctDir(n), ".claude.json"), {});
  return (j.oauthAccount && j.oauthAccount.emailAddress) || "";
}
function boardUsage() {
  const r = pyOut(BOARD, ["usage-json"]);
  try { return JSON.parse(r.out); } catch { return { usage: {}, settings: {}, windows: {} }; }
}
function mappedAccount(dir = process.cwd()) {
  const maps = readJson(MAPS, {});
  for (let d = path.resolve(dir); ; d = path.dirname(d)) {
    if (maps[d]) return { name: maps[d], dir: d };
    if (path.dirname(d) === d) return null;
  }
}
function headroom(u, st) {
  if (!u) return 0; // unknown usage: neutral
  return Math.min((st.stop_5h || 85) - u.five_hour_pct, (st.stop_week || 90) - u.weekly_pct);
}
function pickAccount() {
  const m = mappedAccount();
  if (m) return { name: m.name, why: `mapped to ${m.dir}` };
  const names = knownAccounts().filter((n) => fs.existsSync(acctDir(n)));
  if (!names.length) die(`No accounts yet. Add one: ${c.cyan("coshift login ATLAS")}`);
  const { usage, settings } = boardUsage();
  const best = names.map((n) => ({ n, h: headroom(usage[n], settings), u: usage[n] }))
    .sort((a, b) => b.h - a.h)[0];
  const why = best.u ? `most limit left (5h ${best.u.five_hour_pct}%, weekly ${best.u.weekly_pct}%)` : "no usage known yet";
  if (best.u && best.h <= 0) warn(`Every account is at its stop line. ${best.n} has the most left.`);
  return { name: best.n, why };
}

function prepareAccount(n) {
  const dir = acctDir(n);
  fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
  // status line: shows account/limits/context, and reports them to the board (documented Claude Code feature)
  const sp = path.join(dir, "settings.json");
  const st = readJson(sp, {});
  if (!st.statusLine || String(st.statusLine.command || "").includes("coshift")) {
    st.statusLine = { type: "command", command: `coshift statusline ${n}`, padding: 0 };
    fs.writeFileSync(sp, JSON.stringify(st, null, 2));
  } else warn(`${n} already has its own status line; live usage for it comes from sessions instead.`);
  const env = { ...process.env, CLAUDE_CONFIG_DIR: dir };
  if (has("claude") && spawnSync("claude", ["mcp", "get", "coshift"], { env, stdio: "ignore", shell: IS_WIN }).status !== 0) {
    const pyExe = spawnSync(python()[0], [...python().slice(1), "-c", "import sys;print(sys.executable)"], { encoding: "utf8" }).stdout.trim();
    spawnSync("claude", ["mcp", "add", "--scope", "user", "coshift", "--", pyExe, path.join(HOME, "board.py"), "serve"], { env, stdio: "ignore", shell: IS_WIN });
  }
  return dir;
}

async function login(name) {
  const n = (name || await input("Account name (e.g. ATLAS)")).toUpperCase();
  if (!/^[A-Z0-9_-]{1,20}$/.test(n) || n === "ADMIN") die("Account names: 1-20 letters, digits, - or _.");
  if (!has("claude")) die(`Claude Code isn't installed: ${c.cyan("https://claude.com/claude-code")}`);
  const dir = prepareAccount(n);
  box([`${sym.dot} Signing in ${c.bold(n)}`, "",
    "Claude Code opens with this account's own settings folder.",
    `Sign in with the account you want as ${c.orange(n)} (type ${c.cyan("/login")} if it doesn't ask),`,
    `then type ${c.cyan("/exit")}. Your other accounts stay signed in.`]);
  run("claude", [], { env: { ...process.env, CLAUDE_CONFIG_DIR: dir, COSHIFT_AS: n } });
  const email = acctEmail(n);
  email ? good(`${n} is signed in as ${email}`) : warn(`${n} doesn't look signed in yet. Run ${c.cyan(`coshift login ${n}`)} again.`);
}

function runAs(args) {
  let name = args[0] && !args[0].startsWith("-") && knownAccounts().includes(args[0].toUpperCase()) ? args.shift().toUpperCase() : null;
  let why = "chosen";
  if (!name) ({ name, why } = pickAccount());
  if (!fs.existsSync(acctDir(name))) die(`${name} isn't set up on this computer. Run: ${c.cyan(`coshift login ${name}`)}`);
  console.log(`  ${sym.dot} ${c.bold(name)} ${c.dim(`· ${why}${acctEmail(name) ? " · " + acctEmail(name) : ""}`)}`);
  process.exit(run("claude", args, { env: { ...process.env, CLAUDE_CONFIG_DIR: acctDir(name), COSHIFT_AS: name } }));
}

function map(args) {
  const maps = readJson(MAPS, {});
  const here = path.resolve(process.cwd());
  if (args[0] === "remove" || args[0] === "--remove") {
    delete maps[here];
    fs.writeFileSync(MAPS, JSON.stringify(maps, null, 2));
    return good(`${here} no longer mapped`);
  }
  if (!args[0]) {
    const m = mappedAccount();
    return m ? info(`${c.bold(m.name)} for ${m.dir}`) : info(`No account mapped here. Map one: ${c.cyan("coshift map ATLAS")}`);
  }
  const n = args[0].toUpperCase();
  if (!knownAccounts().includes(n)) die(`No account ${n}. Accounts: ${knownAccounts().join(", ") || "none yet"}`);
  maps[here] = n;
  fs.mkdirSync(HOME, { recursive: true });
  fs.writeFileSync(MAPS, JSON.stringify(maps, null, 2));
  good(`${here} → ${c.bold(n)} (coshift run here starts as ${n})`);
}

function bar(pct, stop) {
  if (pct == null) return c.dim("·".repeat(12) + "   ?");
  const fill = Math.round(Math.min(pct, 100) / 100 * 12);
  const col = pct >= stop ? c.red : pct >= stop - 15 ? c.yellow : c.green;
  return col("█".repeat(fill)) + c.dim("░".repeat(12 - fill)) + " " + String(Math.round(pct)).padStart(3) + "%";
}

function accounts() {
  banner("accounts");
  const names = knownAccounts();
  if (!names.length) return info(`No accounts yet. Add one: ${c.cyan("coshift login ATLAS")}`);
  const { usage, settings, windows } = boardUsage();
  const m = mappedAccount();
  console.log(`  ${c.dim("ACCOUNT".padEnd(10))}${c.dim("5-HOUR".padEnd(20))}${c.dim("WEEKLY".padEnd(20))}${c.dim("CONTEXT".padEnd(9))}${c.dim("SIGNED IN")}`);
  for (const n of names) {
    const u = usage[n];
    const email = fs.existsSync(acctDir(n)) ? (acctEmail(n) || c.yellow("not yet")) : c.dim("cloud only");
    const here = m && m.name === n ? c.orange(" ← here") : "";
    console.log(`  ${c.bold(n.padEnd(10))}${bar(u && u.five_hour_pct, settings.stop_5h || 85)}   ${bar(u && u.weekly_pct, settings.stop_week || 90)}   ${tokensLabel(windows[n] || settings.context_window || 200000).padEnd(9)}${email}${here}`);
  }
  console.log(`\n  ${c.dim("Start a session:")} ${c.cyan("coshift run")} ${c.dim("(picks the account with most limit left)")} or ${c.cyan("coshift run NAME")}\n`);
}

async function statusline(args) {
  // Claude Code calls this with its documented status-line JSON on stdin.
  const name = (args[0] || process.env.COSHIFT_AS || "").toUpperCase();
  let raw = "";
  for await (const chunk of process.stdin) raw += chunk;
  let d = {};
  try { d = JSON.parse(raw); } catch {}
  const rl = d.rate_limits || {}, cw = d.context_window || {};
  const pc = (v) => (v == null ? "?" : Math.round(v) + "%");
  const parts = [c.orange("◆ " + (name || "coshift"))];
  if (rl.five_hour) parts.push(`5h ${pc(rl.five_hour.used_percentage)}`);
  if (rl.seven_day) parts.push(`wk ${pc(rl.seven_day.used_percentage)}`);
  if (cw.used_percentage != null) parts.push(`ctx ${pc(cw.used_percentage)}`);
  process.stdout.write(parts.join(c.dim(" · ")) + "\n");
  // report to the board at most every 30 seconds, in the background so the status line never waits
  if (!name) return;
  const stamp = path.join(HOME, `.statusline-${name}`);
  try { if (Date.now() - fs.statSync(stamp).mtimeMs < 30000) return; } catch {}
  try { fs.mkdirSync(HOME, { recursive: true }); fs.writeFileSync(stamp, ""); } catch { return; }
  const { spawn } = require("child_process");
  const child = spawn(python()[0], [...python().slice(1), BOARD, "ingest-statusline"],
    { env: { ...process.env, COSHIFT_AS: name }, stdio: ["pipe", "ignore", "ignore"], detached: true, windowsHide: true });
  child.stdin.end(raw);
  child.unref();
}

// ---------- tray: macOS menu bar, Windows notification area, Linux indicator/notifications ----------
async function tray(action = "install") {
  const board = path.join(HOME, "board.py");
  if (!fs.existsSync(board) && action !== "remove") die(`Set up Coshift first: ${c.cyan("coshift setup")}`);
  if (process.platform === "darwin") {
    const app = path.join(os.homedir(), "Applications", "Claude Switch Menu.app");
    if (action === "remove") {
      run("pkill", ["-f", "Claude Switch Menu.app/Contents/MacOS/ClaudeSwitchMenu"], { stdio: "ignore" });
      return good(`Menu bar app stopped. Turn off "Launch at Login" in its menu first if you enabled it; the app stays in ~/Applications.`);
    }
    if (action === "install") {
      if (!has("swiftc")) die(`The menu bar app is built on your Mac and needs Apple's command line tools: ${c.cyan("xcode-select --install")}`);
      info("Building the menu bar app…");
      if (run("bash", [path.join(PKG, "mac", "menubar", "install-menubar.sh")], { stdio: "ignore" })) die("build failed");
    }
    run("pkill", ["-f", "Claude Switch Menu.app/Contents/MacOS/ClaudeSwitchMenu"], { stdio: "ignore" });
    run("open", [app]);
    return box([`${sym.ok} Coshift is in your menu bar`, "",
      "Every account's limits, start Claude Code as an account, and a",
      "notification when a session needs you.",
      `To start it at login: open its menu ${sym.arrow} ${c.bold("Launch at Login")}`]);
  }
  if (IS_WIN) {
    const ps1 = path.join(HOME, "coshift-tray.ps1");
    const startup = path.join(process.env.APPDATA || "", "Microsoft", "Windows", "Start Menu", "Programs", "Startup", "coshift-tray.vbs");
    if (action === "remove") {
      try { fs.unlinkSync(startup); } catch {}
      spawnSync("powershell", ["-NoProfile", "-Command", "Get-CimInstance Win32_Process -Filter \"Name='powershell.exe'\" | Where-Object { $_.CommandLine -like '*coshift-tray.ps1*' } | ForEach-Object { Stop-Process -Id $_.ProcessId }"], { stdio: "ignore" });
      return good("Tray removed");
    }
    fs.copyFileSync(path.join(PKG, "tray", "coshift-tray.ps1"), ps1);
    const cmd = `powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File ""${ps1}""`;
    fs.writeFileSync(startup, `CreateObject("WScript.Shell").Run "${cmd}", 0, False\r\n`);
    spawnSync("wscript.exe", [startup], { stdio: "ignore", detached: true });
    return box([`${sym.ok} Coshift is in your notification area (by the clock)`, "",
      "Hover for every account's limits; click for the menu. It starts",
      "at login. If you don't see it, check the ^ hidden-icons arrow."]);
  }
  // Linux
  const script = path.join(HOME, "coshift-tray-linux.py");
  const auto = path.join(os.homedir(), ".config", "autostart", "coshift-tray.desktop");
  if (action === "remove") {
    try { fs.unlinkSync(auto); } catch {}
    run("pkill", ["-f", "coshift-tray-linux.py"], { stdio: "ignore" });
    return good("Tray removed");
  }
  fs.copyFileSync(path.join(PKG, "tray", "coshift-tray-linux.py"), script);
  const pyExe = spawnSync(python()[0], [...python().slice(1), "-c", "import sys;print(sys.executable)"], { encoding: "utf8" }).stdout.trim();
  fs.mkdirSync(path.dirname(auto), { recursive: true });
  fs.writeFileSync(auto, `[Desktop Entry]\nType=Application\nName=Coshift\nComment=Claude Code accounts on the Coshift board\nExec=${pyExe} ${script}\nX-GNOME-Autostart-enabled=true\n`);
  run("pkill", ["-f", "coshift-tray-linux.py"], { stdio: "ignore" });
  const { spawn } = require("child_process");
  spawn(pyExe, [script], { detached: true, stdio: "ignore" }).unref();
  const hasIndicator = spawnSync(pyExe, ["-c", "import gi;gi.require_version('Gtk','3.0')"], { stdio: "ignore" }).status === 0;
  return box([`${sym.ok} Coshift tray started (and at every login)`, "",
    hasIndicator ? "Look for its icon in your panel. On plain GNOME, install the"
      : `No tray library found (${c.cyan("python3-gi")}), so you'll get desktop notifications`,
    hasIndicator ? "AppIndicator extension to see tray icons." : "when a session needs you or an account hits its stop line."]);
}

// ---------- interactive shell ----------
async function shell() {
  banner(mode() === "vercel" ? remote().url : mode() === "local" ? "board on this computer" : "not set up yet");
  if (!mode()) {
    console.log(`  Welcome. Let's set up your board first.\n`);
    return setup([]);
  }
  for (;;) {
    const pick = await select("What do you want to do?", [
      { label: "Accounts", value: "accounts", hint: "live limits of every account" },
      { label: "Start Claude Code", value: "run", hint: "as the account with most limit left" },
      { label: "Board status", value: "status", hint: "sessions and tasks" },
      { label: "Open the board page", value: "open" },
      { label: "Settings", value: "config", hint: "stop lines, context windows, phone alerts" },
      ...(mode() === "vercel" ? [
        { label: "Cloud variables for an account", value: "env", hint: "copy to claude.ai/code" },
        { label: "Add an account / new token", value: "account" },
        { label: "Redeploy the board", value: "deploy" },
        { label: "Usage pusher", value: "pusher", hint: "send live limits every minute" },
      ] : []),
      { label: process.platform === "darwin" ? "Menu bar app" : "Tray icon", value: "tray", hint: "limits and alerts by the clock" },
      { label: "Doctor", value: "doctor", hint: "check everything" },
      { label: "Run setup again", value: "setup" },
      { label: "Quit", value: "quit" },
    ]);
    console.log();
    if (pick === "quit") return;
    if (pick === "status") py(BOARD, ["show"]);
    if (pick === "accounts") accounts();
    if (pick === "run") runAs([]);
    if (pick === "open") py(BOARD, ["web", "--open"]);
    if (pick === "config") await config([]);
    if (pick === "doctor") doctor();
    if (pick === "tray") await tray(await select(process.platform === "darwin" ? "Menu bar app" : "Tray icon",
      [{ label: "Install / restart", value: "install" }, { label: "Remove", value: "remove" }]));
    if (pick === "setup") return setup([]);
    if (pick === "deploy") { syncApp(); run("vercel", ["deploy", "--prod", "--yes"], { cwd: APP }); }
    if (pick === "pusher") await pusher(await select("Usage pusher", [{ label: "Install / restart", value: "install" }, { label: "Remove", value: "remove" }]));
    if (pick === "env") {
      const names = Object.keys(tokens()).filter((k) => k !== "admin");
      env(await select("Which account?", [...names.map((n) => ({ label: n, value: n })), { label: "Page key (admin)", value: "admin" }]));
    }
    if (pick === "account") {
      const what = await select("Which?", [{ label: "Add an account", value: "add" }, { label: "New token for an account", value: "rotate" }]);
      const name = what === "add" ? await input("New account name") : await select("Which account?", Object.keys(tokens()).filter((k) => k !== "admin").map((n) => ({ label: n, value: n })));
      if (name) await account([what, name]);
    }
    console.log();
  }
}

const USAGE = `${c.bold("coshift")} ${c.dim(VERSION)}: several Claude Code accounts, one project

  ${c.cyan("coshift")}                     interactive menu
  ${c.cyan("coshift setup")}               guided setup (Vercel or this computer)
  ${c.cyan("coshift demo [port]")}         try the board page with made-up data
  ${c.cyan("coshift accounts")}            every account's live limits
  ${c.cyan("coshift login NAME")}          add an account (its own Claude Code sign-in)
  ${c.cyan("coshift run [NAME]")}          start Claude Code as NAME, or the one with most limit left
  ${c.cyan("coshift map [NAME|remove]")}   tie this folder to an account
  ${c.cyan("coshift status")}              sessions and tasks
  ${c.cyan("coshift open")}                open the board page
  ${c.cyan("coshift env NAME|admin")}      an account's cloud variables (copied) / the page key
  ${c.cyan("coshift config [k v [ACCT]]")} show or change settings (stop lines, context windows, alerts)
  ${c.cyan("coshift account add|rotate N")} add an account or give one a new token
  ${c.cyan("coshift pusher [remove]")}     send live usage to the board every minute
  ${c.cyan("coshift tray [remove]")}       menu bar (macOS) / tray icon (Windows, Linux) with limits and alerts
  ${c.cyan("coshift deploy")}              redeploy the board after upgrading
  ${c.cyan("coshift doctor")}              check the whole setup
  ${c.cyan("coshift hook")}                print the context hook for a repo
  ${c.cyan("coshift serve | web | call")}  board internals (MCP server, local page, tools)
  ${c.cyan("coshift claude-switch ...")}   macOS: swap the Claude desktop app between accounts

Docs: ${c.cyan("https://github.com/pgamerx/coshift")}`;

async function main() {
  const [cmd, ...rest] = process.argv.slice(2);
  switch (cmd) {
    case undefined: return process.stdin.isTTY ? shell() : console.log(USAGE);
    case "help": case "-h": case "--help": return console.log(USAGE);
    case "-v": case "--version": return console.log(VERSION);
    case "setup": return setup(rest);
    case "demo": return process.exit(py(path.join(PKG, "scripts", "demo.py"), rest));
    case "status": return process.exit(py(BOARD, ["show"]));
    case "accounts": return accounts();
    case "login": return login(rest[0]);
    case "run": return runAs(rest);
    case "map": return map(rest);
    case "statusline": return statusline(rest);
    case "open": return process.exit(py(BOARD, ["web", "--open"]));
    case "env": return env(rest[0]);
    case "config": return config(rest);
    case "account": return account(rest);
    case "pusher": return pusher(rest[0] === "remove" ? "remove" : "install");
    case "doctor": return doctor();
    case "tray": return tray(rest[0] === "remove" ? "remove" : rest[0] === "run" ? "run" : "install");
    case "deploy":
      if (!fs.existsSync(path.join(APP, ".vercel"))) die("no Vercel board yet. Run: coshift setup");
      syncApp();
      return process.exit(run("vercel", ["deploy", "--prod", "--yes"], { cwd: APP }));
    case "hook": return process.stdout.write(fs.readFileSync(path.join(PKG, "board", "board-context.sh")));
    case "claude-switch":
      if (process.platform !== "darwin") die("claude-switch swaps the Claude desktop app on macOS only.");
      return process.exit(run("bash", [path.join(PKG, "mac", "claude-switch"), ...rest])); // npm drops the exec bit
    case "serve": case "web": case "show": case "add": case "reopen": case "call": case "push-usage": case "settings":
      return process.exit(py(BOARD, [cmd, ...rest]));
    default: die(`unknown command "${cmd}". Run: coshift help`);
  }
}

main().catch((e) => die(e.message));
