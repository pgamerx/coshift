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

// Every deploy goes through here. Vercel's own refusal ("Error: Not authorized") doesn't say what to do, and new users
// often don't know the board's deploys need the Vercel CLI signed in to the account that owns the board.
function deployBoard({ quiet = false } = {}) {
  if (!has("vercel")) {
    bad(`The Vercel CLI isn't installed. Install it with ${c.cyan("npm i -g vercel")}, sign in with ${c.cyan("vercel login")}, then run ${c.cyan("coshift deploy")}.`);
    return 1;
  }
  const signedIn = spawnSync("vercel", ["whoami"], { stdio: ["ignore", "ignore", "ignore"], timeout: 30000, shell: IS_WIN }).status === 0;
  if (!signedIn) {
    if (!process.stdin.isTTY) {
      bad(`Not signed in to Vercel. Run ${c.cyan("vercel login")} with the account that owns your board, then ${c.cyan("coshift deploy")}.`);
      return 1;
    }
    info("Sign in to Vercel first, with the account that owns your board (your board runs there)…");
    if (run("vercel", ["login"])) {
      bad(`Vercel sign-in didn't finish. Run ${c.cyan("vercel login")}, then ${c.cyan("coshift deploy")}.`);
      return 1;
    }
  }
  const r = spawnSync("vercel", ["deploy", "--prod", "--yes"],
    { cwd: APP, stdio: quiet ? "pipe" : "inherit", encoding: "utf8", shell: IS_WIN });
  const code = r.status === null ? 1 : r.status;
  if (code) {
    const said = quiet ? String(r.stderr || "").trim().split("\n").filter(Boolean).pop() : "";
    bad(`Vercel didn't deploy the board${said ? ` (${said})` : ""}.`);
    info(`"Not authorized"? Sign in again with ${c.cyan("vercel login")}, using the account that owns the board, and update the CLI`);
    info(`with ${c.cyan("npm i -g vercel@latest")}. Then run ${c.cyan("coshift deploy")}. Check the account with ${c.cyan("vercel whoami")}.`);
  }
  return code;
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
  console.log(`  Coshift lets several Claude Code and Codex accounts work on your projects together: they split the work
  into tasks on a shared board, hand over when one nears its limit, and restart from a saved summary
  when a session's context fills up. This takes about 3 minutes; you can re-run it any time.\n`);

  // 1. system: detected, nothing to answer
  step(1, 7, "Checking this computer");
  const sys = OS_LABEL[process.platform] ? process.platform : "linux";
  python();
  good(`${OS_LABEL[sys]} · ${pyVersion()} · Node ${process.versions.node}`);
  has("claude") ? good("Claude Code found") : warn(`Claude Code not found${has("codex") ? " (fine if you only use Codex)" : `. Install it first: ${c.cyan("https://claude.com/claude-code")}`}`);
  if (has("codex")) good(`Codex found: add ChatGPT accounts later with ${c.cyan("coshift login NAME --codex")}`);

  // 2. hosting
  step(2, 7, "Where the board lives");
  info("The board is the shared to-do list every session reads and writes.");
  const host = await select("Host the board where?", [
    { label: "Vercel", value: "vercel", hint: "free · recommended · open it from any device, works with cloud sessions" },
    { label: "This computer only", value: "local", hint: "no account needed · this machine only" },
    { label: "Restore from my Vercel board", value: "restore", hint: "new computer · same board, accounts and tasks" },
  ]);
  if (host === "restore") return restoreSetup(args);
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
  step(3, 7, "Your accounts");
  info("One short name per account you'll use, Claude or ChatGPT/Codex (it's how sessions and the board tell them apart).");
  const prev = (remote().names || Object.keys(tokens()).filter((n) => n !== "admin")).join(",");
  const names = (await input("Name your accounts (comma separated)", prev || "ATLAS,FORGE"))
    .split(",").map((s) => s.trim().toUpperCase()).filter(Boolean);
  if (!names.length || names.some((n) => !/^[A-Z0-9_-]{1,20}$/.test(n) || n === "ADMIN") || new Set(names).size < names.length)
    die("Account names: 1-20 letters, digits, - or _, all different (and not ADMIN).");
  const windows = {};
  for (const n of names) {
    windows[n] = await select(`Context window of ${c.orange(n)}'s sessions?`, [
      { label: "200K tokens", value: 200000, hint: "Pro, and most models" },
      { label: "1M tokens", value: 1000000, hint: "Max with a 1M-context model" },
      { label: "Not sure", value: 200000, hint: "uses 200K; the status line corrects it once a session runs" },
    ]);
  }
  const detectedAccts = (() => { try { return JSON.parse(pyOut(BOARD, ["detect-accounts"]).out || "{}"); } catch { return {}; } })();
  const maps = [];
  const orgs = Object.entries(detectedAccts).filter(([org]) => !org.startsWith("codex:"));  // Codex ones already have names
  if (orgs.length) {
    info(`Found ${orgs.length} Claude account${orgs.length > 1 ? "s" : ""} signed in on this computer. Which name is each? (This lets the board show their live limits.)`);
    for (const [org, u] of orgs) {
      const pick = await select(`${u.profile || org.slice(0, 8)} (${u.five_hour_pct}% 5-hour, ${u.weekly_pct}% weekly) is`,
        [...names.map((n) => ({ label: n, value: n })), { label: "Skip", value: "" }]);
      if (pick) maps.push("--map", `${org}=${pick}`);
    }
  }

  // 4. board
  step(4, 7, host === "vercel" ? "Create the board on Vercel" : "Create the board on this computer");
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
    if (deployBoard()) process.exit(1);
    good(`Board live at ${c.cyan(result.url)}`);
  }
  for (const n of names) pyOut(BOARD, ["settings", "set", "context_window", String(windows[n]), n]);
  good(`Context windows saved (${names.map((n) => `${n} ${windows[n] >= 1e6 ? windows[n] / 1e6 + "M" : windows[n] / 1000 + "K"}`).join(", ")})`);

  // 5. projects
  step(5, 7, "Projects");
  info("Each repo can have its own board, so tasks from different projects never mix. A repo without one");
  info("uses the main board. Pick the project from the dropdown at the top of the board page.");
  const repoHere = fs.existsSync(path.join(process.cwd(), ".git")) ? path.basename(process.cwd()) : "";
  if (repoHere && (await confirm(`Give this repo (${repoHere}) its own board?`, true))) {
    const r = pyOut(BOARD, ["projects", "add"], { cwd: process.cwd() });  // the board names it after the main checkout
    r.code ? warn(r.err || r.out) : good(r.out);
  } else info(`Later, inside a repo: ${c.cyan("coshift project add")}  (or "+ New project" on the board page)`);

  // 6. this computer
  step(6, 7, "Connect this computer");
  info("Desktop and terminal Claude Code sessions here get the board's tools (claim_task, add_note, ...).");
  if (has("claude") && (await confirm("Connect Claude Code sessions on this computer to the board?", true))) {
    const r = run("claude", ["mcp", "add", "--scope", "user", "coshift", "--", result.python, result.link, "serve"], { stdio: "ignore" });
    r === 0 ? good("Desktop sessions connected (new sessions get the board tools)") : warn("Couldn't add it; it may already be there. Check: claude mcp list");
  }
  if (host === "vercel" && orgs.length && (await confirm("Send this computer's live usage (5-hour and weekly %) to the board every minute?", true))) {
    await pusher("install");
  }

  // 7. cloud sessions: each account's variables, then the context hook in the repo
  step(7, 7, "Cloud sessions (claude.ai/code)");
  let cloud = false;
  if (host === "vercel" && (await confirm("Will you also run cloud sessions on claude.ai/code?", true))) {
    cloud = true;
    info("Each account needs its own two variables in its cloud environment. One at a time:");
    for (const n of names) {
      console.log(`
  ${c.orange("●")} ${c.bold(n)}: sign in to claude.ai as ${n}, open Claude Code → your environment → Edit,`);
      console.log(`    paste these into ${c.bold("Environment variables")}, and allow the board under ${c.bold("Network access")}.`);
      env(n);
      await input(`Saved in ${n}'s environment? Press Enter for the next`);
    }
    console.log(`
  ${c.bold("Context hook")}: cloud sessions report how full their context is through a small hook that`);
    console.log(`  lives in your repo (it does nothing without the variables, so it's safe for anyone else).`);
    const repo = await input("Add it to which repo? (folder path, empty to skip)", fs.existsSync(path.join(process.cwd(), ".git")) ? process.cwd() : "");
    if (repo) hookInstall(repo);
    else info(`Later, in your repo: ${c.cyan("coshift hook install")}`);
  } else if (host === "vercel") info(`Later: ${c.cyan("coshift env NAME")} for each account, and ${c.cyan("coshift hook install")} in your repo.`);
  else info("Cloud sessions can't reach a board on this computer; desktop sessions can.");

  console.log();
  const lines = [`${sym.ok} ${c.bold("Coshift is set up")}`, ""];
  if (host === "vercel") {
    lines.push(`Board      ${c.cyan(result.url)}`, `Page key   ${c.cyan("coshift env admin")}`, "");
    if (!cloud) lines.push(`Cloud sessions: ${c.cyan("coshift env NAME")} per account, ${c.cyan("coshift hook install")} per repo`, "");
  } else {
    lines.push(`Board      ${c.cyan("coshift open")}`, "");
  }
  lines.push(c.bold("What now:"),
    `  1. Open the board (${c.cyan("coshift open")}). Anything still missing shows there as a checklist.`,
    `  2. Start a session in your project (${c.cyan("coshift run")} picks the account with most limit left)`,
    `     and tell it: ${c.dim("Use the Coshift board: split <goal> into tasks, then claim one.")}`,
    `  3. Start more sessions on other accounts with: ${c.dim("Use the Coshift board and claim the next task.")}`,
    "", `Everything else: ${c.cyan("coshift")}  (menu)   ·   check the setup: ${c.cyan("coshift doctor")}`);
  box(lines);
  console.log();
}

// New computer, existing Vercel board: link the same project, pull its tokens and Redis link, reconnect this machine.
// Tasks, projects, settings and context windows already live in the board's Redis, so nothing is re-asked.
async function restoreSetup(args) {
  if (!has("vercel")) die(`The Vercel CLI isn't installed. Install it with ${c.cyan("npm i -g vercel")}, then run ${c.cyan("coshift setup")} again.`);
  step(3, 4, "Find your board on Vercel");
  syncApp();
  const here = { cwd: APP };
  if (spawnSync("vercel", ["whoami"], { stdio: "ignore", timeout: 30000, shell: IS_WIN }).status !== 0) {
    info("Sign in to Vercel with the account that owns your board…");
    if (run("vercel", ["login"])) die("Vercel sign-in didn't finish. Run vercel login, then coshift setup.");
  }
  if (!fs.existsSync(path.join(APP, ".vercel"))) {
    info(`Pick ${c.bold("your existing board project")} when asked ("Link to existing project?" → yes).`);
    if (run("vercel", ["link"], here)) die("vercel link failed.");
  }
  const url = await input("Board address", remote().url || projectUrl());
  info("Pulling your accounts and storage from Vercel…");
  const detected = (() => { try { return JSON.parse(pyOut(BOARD, ["detect-accounts"]).out || "{}"); } catch { return {}; } })();
  const orgs = Object.entries(detected).filter(([org]) => !org.startsWith("codex:"));
  const r = pyOut(path.join(APP, "scripts", "setup.py"), ["--restore", "--url", url, "--json", ...args],
    { cwd: APP, env: { ...process.env, COSHIFT_CLI: "1" } });
  if (r.code) die(r.err || "restore failed");
  const result = JSON.parse(r.out);
  if (result.board_tokens) {
    good(`Connected to ${c.cyan(result.url)}`);
    info("Vercel keeps your account tokens hidden, so this computer got its own page key instead. Your existing");
    info("tokens and cloud sessions stay exactly as they are; accounts you add here get their tokens the same way.");
    info("Updating the board so it accepts them…");
    if (deployBoard({ quiet: true })) process.exit(1);
  } else good(`Restored ${result.accounts.join(", ")} · board at ${c.cyan(result.url)}`);

  step(4, 4, "Connect this computer");
  if (has("claude") && (await confirm("Connect Claude Code sessions on this computer to the board?", true))) {
    const m = run("claude", ["mcp", "add", "--scope", "user", "coshift", "--", result.python, result.link, "serve"], { stdio: "ignore" });
    m === 0 ? good("Desktop sessions connected") : warn("Couldn't add it; it may already be there. Check: claude mcp list");
  }
  if (orgs.length && (await confirm("Send this computer's live usage (5-hour and weekly %) to the board every minute?", true))) {
    await pusher("install");
  }
  console.log();
  box([`${sym.ok} ${c.bold("Coshift is restored")}`, "",
    `Board      ${c.cyan(result.url)}`, `Page key   ${c.cyan("coshift env admin")}`, "",
    ...(result.accounts.length ? [c.bold("Sign each account in again on this computer (sign-ins never leave a machine):"),
      ...result.accounts.map((n) => `  ${c.cyan(`coshift login ${n}`)}   ${c.dim("(add --codex for a ChatGPT account)")}`), ""] : []),
    `New account: ${c.cyan("coshift account add NAME")}   ·   cloud sessions keep working as they are`,
    `Check everything: ${c.cyan("coshift doctor")}`]);
  console.log();
}

// Renames an account on the board (every project, all history) and in this computer's files. The board keeps
// old -> new, so the old token, cloud variables and env vars keep working; nothing to re-paste or redeploy.
function renameAccount(oldName, newName) {
  if (!oldName || !newName) die("usage: coshift account rename OLD NEW");
  const o = oldName.toUpperCase(), n = newName.toUpperCase();
  const known = knownAccounts().map((x) => x.toUpperCase());
  if (known.length && !known.includes(o)) die(`No account ${o} here. Accounts: ${known.join(", ")}`);
  const r = pyOut(BOARD, ["rename-account", o, n]);
  if (r.code) die(r.err.split("\n").pop() || r.out);
  good(`Board: ${o} is now ${n} on every project, history included`);
  const swap = (v) => (typeof v === "string" && v.toUpperCase() === o ? n : v);
  const t = tokens();
  if (t[o]) { t[n] = t[o]; delete t[o]; fs.writeFileSync(path.join(HOME, "tokens.json"), JSON.stringify(t, null, 2), { mode: 0o600 }); }
  const rm = remote();
  if (Object.keys(rm).length) {
    if (rm.names) rm.names = rm.names.map(swap);
    for (const k of Object.keys(rm.accounts || {})) rm.accounts[k] = swap(rm.accounts[k]);
    fs.writeFileSync(path.join(HOME, "remote.json"), JSON.stringify(rm, null, 2), { mode: 0o600 });
  }
  const maps = readJson(MAPS, null);
  if (maps) { for (const k of Object.keys(maps)) maps[k] = swap(maps[k]); fs.writeFileSync(MAPS, JSON.stringify(maps, null, 2)); }
  if (fs.existsSync(acctDir(o)) && !fs.existsSync(acctDir(n))) {  // its own Claude Code sign-in moves with it
    fs.renameSync(acctDir(o), acctDir(n));
    const sp = path.join(acctDir(n), "settings.json"), st = readJson(sp, null);
    if (st?.statusLine?.command?.includes("coshift statusline")) {
      st.statusLine.command = `coshift statusline ${n}`;
      fs.writeFileSync(sp, JSON.stringify(st, null, 2));
    }
    if (isCodex(n) && has("codex")) prepareCodex(n);  // its MCP server carries the account name
  }
  // macOS switcher label: keep it matching, or the account mix-up check would warn
  const np = process.env.CLAUDE_SWITCH_MENU_NAMES || path.join(os.homedir(), "Library", "Application Support", "ClaudeSwitchMenu", "names.json");
  const labels = readJson(np, null);
  if (labels) {
    let changed = false;
    for (const [k, v] of Object.entries(labels)) {
      const label = typeof v === "string" ? v : v?.name;
      if (k.startsWith("@") || !label || label.toUpperCase() !== o) continue;
      const shown = label === label.toUpperCase() ? n : n[0] + n.slice(1).toLowerCase();  // keep its style: FORGE / Forge
      if (typeof v === "string") labels[k] = shown; else v.name = shown;
      changed = true;
    }
    if (changed) { fs.writeFileSync(np, JSON.stringify(labels, null, 2), { mode: 0o600 }); good("Menu bar label updated"); }
  }
  good(`This computer's files updated. ${o}'s token and cloud variables keep working as ${n}.`);
}

// ---------- other commands ----------
const HOOK_CMD = 'sh "$CLAUDE_PROJECT_DIR/.claude/hooks/board-context.sh"';
// The repo's pointer to the board, for sessions that don't have the board's tools (Claude Code on claude.ai/code,
// Codex on chatgpt.com/codex): Codex reads AGENTS.md, Claude Code reads CLAUDE.md. The instructions themselves stay
// on the board (Team → Shared instructions), so they're edited in one place.
const AGENTS_BLOCK = `<!-- coshift:start -->
## Coshift board

Several accounts (Claude Code, Codex and Antigravity, on the web, desktop or CLI) work on this repo together through the Coshift board.
At the start of every session or task:

- If you have the board's tools (claim_task, resume, ...), call \`resume\` (Antigravity: pass this repo's absolute path as \`workspace\`).
- Otherwise, if \`COSHIFT_URL\` and \`COSHIFT_TOKEN\` are set, run this and follow what it says:
  \`curl -sS "$COSHIFT_URL/api/help" -H "Authorization: Bearer $COSHIFT_TOKEN"\`
- Otherwise, ignore this section.

Follow the project instructions, lead and roles the board shows you, and never change files another account's running task owns.
<!-- coshift:end -->`;
function agentsInstall(dir = process.cwd()) {
  const root = path.resolve(dir);
  if (!fs.existsSync(root)) return bad(`No folder ${root}`);
  for (const f of ["AGENTS.md", "CLAUDE.md"]) {
    const p = path.join(root, f);
    const cur = fs.existsSync(p) ? fs.readFileSync(p, "utf8") : "";
    const next = /<!-- coshift:start -->[\s\S]*?<!-- coshift:end -->/.test(cur)
      ? cur.replace(/<!-- coshift:start -->[\s\S]*?<!-- coshift:end -->/, AGENTS_BLOCK)
      : (cur ? cur.trimEnd() + "\n\n" : "") + AGENTS_BLOCK + "\n";
    if (next !== cur) fs.writeFileSync(p, next);
  }
  good(`Board pointer added to ${root} (AGENTS.md for Codex and Antigravity, CLAUDE.md for Claude Code)`);
  info("Commit both files so web sessions get them. Write the instructions themselves on the board: Team → Shared instructions.");
}

function hookInstall(dir = process.cwd()) {
  // the context hook for cloud sessions: the script plus a PostToolUse entry in the repo's .claude/settings.json
  const root = path.resolve(dir);
  if (!fs.existsSync(root)) return bad(`No folder ${root}`);
  const script = path.join(root, ".claude", "hooks", "board-context.sh");
  fs.mkdirSync(path.dirname(script), { recursive: true });
  fs.copyFileSync(path.join(PKG, "board", "board-context.sh"), script);
  fs.chmodSync(script, 0o755);
  const sp = path.join(root, ".claude", "settings.json");
  const st = readJson(sp, null);
  if (st === null && fs.existsSync(sp)) return bad(`${sp} isn't valid JSON; add the hook by hand: coshift hook`);
  const conf = st || {};
  const post = ((conf.hooks = conf.hooks || {}).PostToolUse = conf.hooks.PostToolUse || []);
  if (!post.some((m) => (m.hooks || []).some((h) => String(h.command || "").includes("board-context.sh")))) {
    post.push({ matcher: "*", hooks: [{ type: "command", command: HOOK_CMD }] });
    fs.writeFileSync(sp, JSON.stringify(conf, null, 2) + "\n");
  }
  good(`Context hook added to ${root} (.claude/hooks/board-context.sh, .claude/settings.json)`);
  info("Commit both files so cloud sessions get them.");
}

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
  console.log(`\n  ${c.bold(n)}'s cloud variables:\n\n${text.split("\n").map((l) => "  " + l).join("\n")}\n`);
  console.log(`  ${c.orange("Claude Code on the web")} ${c.dim("(claude.ai/code → your environment → Edit)")}`);
  console.log(`    Environment variables: paste both lines.  Network access: allow ${c.cyan(host)}\n`);
  console.log(`  ${c.orange("Codex on the web")} ${c.dim("(chatgpt.com/codex → Settings → Environments → yours → Edit)")}`);
  console.log(`    Environment variables (not Secrets: Codex hides secrets from the agent): add both.`);
  console.log(`    Agent internet access: On, domain allowlist ${c.cyan(host)}, HTTP methods: All (the board needs POST).\n`);
  console.log(`  ${c.dim("Once per repo:")} ${c.cyan("coshift agents")} ${c.dim("so web sessions find the board, then commit AGENTS.md and CLAUDE.md.")}\n`);
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
    if (r.code) return die(r.err.split("\n").pop() || r.out);
    good(r.out);
    return info("Applies to every session right away; no redeploy needed.");
  }
  const r = pyOut(BOARD, ["settings"]);
  if (r.code) die(r.err.split("\n").pop() || "couldn't read the board");
  const s = JSON.parse(r.out);
  if (!args.length && process.stdin.isTTY) {
    banner("settings");
    const pick = await select("Change which setting?", [
      ...Object.keys(keys).map((k) => ({ label: `${keys[k]}`, value: k, hint: k === "context_window" ? tokensLabel(s[k]) : String(s[k] === "" ? "off" : s[k]) })),
      ...[...new Set([...Object.keys(s.context_windows || {}), ...knownAccounts()])].map((a) => ({
        label: `Context window of ${a}`, value: "cw:" + a,
        hint: s.context_windows?.[a] ? tokensLabel(s.context_windows[a]) : `default (${tokensLabel(s.context_window)})` })),
      { label: "Done", value: "" },
    ]);
    if (!pick) return;
    const [k, acct] = pick.startsWith("cw:") ? ["context_window", pick.slice(3)] : [pick, null];
    const v = await input(k === "context_window" ? "New value (e.g. 1M or 200K)" : "New value", String(acct ? s.context_windows?.[acct] ?? s.context_window : s[k]));
    const out = pyOut(BOARD, ["settings", "set", k, v, ...(acct ? [acct] : [])]);
    out.code ? bad(out.err.split("\n").pop()) : good(`${out.out}  ${c.dim("(applies right away; no redeploy needed)")}`);
    return config(args);
  }
  for (const [k, label] of Object.entries(keys)) console.log(`  ${c.dim(label.padEnd(44))} ${k.padEnd(15)} ${c.bold(k === "context_window" ? tokensLabel(s[k]) : s[k] === "" ? "off" : s[k])}`);
  for (const [a, w] of Object.entries(s.context_windows || {})) console.log(`  ${c.dim(("Context window of " + a).padEnd(44))} ${"".padEnd(15)} ${c.bold(tokensLabel(w))}`);
}

async function account(args) {
  const [action, name] = args;
  if (action === "rename") return renameAccount(name, args[2]);
  if (!["add", "rotate"].includes(action) || !name) die("usage: coshift account add|rotate NAME  |  coshift account rename OLD NEW");
  if (mode() !== "vercel") die("accounts with tokens are for a Vercel board. For a local board, run coshift setup.");
  syncApp();
  const r = pyOut(path.join(APP, "scripts", "setup.py"), [`--${action}`, name, "--json"], { cwd: APP });
  if (r.code) die(r.err.split("\n").pop());
  good(`${action === "add" ? "Added" : "New token for"} ${name.toUpperCase()}`);
  info("Deploying so the board knows…");
  if (deployBoard({ quiet: true })) process.exit(1);
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
    if (has("vercel")) {
      const who = spawnSync("vercel", ["whoami"], { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"], timeout: 30000, shell: IS_WIN });
      check(who.status === 0, `Vercel CLI signed in as ${String(who.stdout || "").trim().split("\n").pop()} (deploys need the account that owns the board)`,
        "Vercel CLI not signed in: run vercel login (needed for coshift deploy and coshift update)");
    }
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
  for (const n of knownAccounts().filter((x) => fs.existsSync(acctDir(x)) && isCodex(x)))
    check(spawnSync("codex", ["mcp", "get", "coshift"], { env: toolEnv(n), stdio: "ignore", shell: IS_WIN }).status === 0,
      `${n} (Codex) connected (MCP)`, `${n} (Codex) not connected: coshift login ${n} --codex`);
  for (const n of knownAccounts().filter((x) => fs.existsSync(acctDir(x)) && isAntigravity(x)))
    check(readJson(antigravityConfig(), {}).mcpServers?.coshift?.env?.COSHIFT_AS === n,
      `${n} (Antigravity) connected (MCP)`, `${n} (Antigravity) not connected: coshift login ${n} --antigravity`);
  if (has("claude")) {
    const got = (n) => spawnSync("claude", ["mcp", "get", n], { encoding: "utf8", shell: IS_WIN }).status === 0;
    check(got("coshift") || got("team-board"), "Desktop sessions connected (MCP)", "Desktop sessions not connected: coshift setup → Connect this computer");
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

// ---------- accounts: one settings folder per account (CLAUDE_CONFIG_DIR, or CODEX_HOME for Codex) ----------
// Claude Code and Codex keep each folder's login separate (Keychain or a credentials file), so Coshift never reads
// or copies a token. A Codex account's folder has a config.toml; a Claude Code one never does.
const ACCTS = path.join(HOME, "accounts");
const acctDir = (n) => path.join(ACCTS, n.toUpperCase());
const MAPS = path.join(HOME, "maps.json");

function knownAccounts() {
  const set = new Set([...(remote().names || []), ...Object.keys(tokens()).filter((k) => k !== "admin")]);
  try { for (const d of fs.readdirSync(ACCTS)) if (fs.statSync(path.join(ACCTS, d)).isDirectory()) set.add(d); } catch {}
  return [...set];
}
const isCodex = (n) => fs.existsSync(path.join(acctDir(n), "config.toml"));
// Antigravity signs in inside its own app and reads one global MCP config, so its folder only holds this marker
const isAntigravity = (n) => fs.existsSync(path.join(acctDir(n), "antigravity"));
const toolOf = (n) => (isCodex(n) ? "codex" : isAntigravity(n) ? "antigravity" : "claude");
const TOOL_LABEL = { codex: "Codex", antigravity: "Antigravity", claude: "Claude Code" };
const toolEnv = (n) => ({ ...process.env, [isCodex(n) ? "CODEX_HOME" : "CLAUDE_CONFIG_DIR"]: acctDir(n), COSHIFT_AS: n });
function acctEmail(n) {
  if (isCodex(n)) return fs.existsSync(path.join(acctDir(n), "auth.json")) ? "ChatGPT (Codex)" : "";  // presence only
  if (isAntigravity(n)) return "Google (Antigravity)";
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
function pickAccount(tool) {
  const m = mappedAccount();
  if (m && (!tool || toolOf(m.name) === tool)) return { name: m.name, why: `mapped to ${m.dir}` };
  // Antigravity's limits are unknown and it's an app, so a plain `coshift run` never picks it
  const all = knownAccounts(), names = all.filter((n) => fs.existsSync(acctDir(n)) && (tool ? toolOf(n) === tool : toolOf(n) !== "antigravity"));
  if (!names.length && tool && tool !== "claude") die(`No ${TOOL_LABEL[tool]} account yet. Add one: ${c.cyan(`coshift login NAME --${tool}`)}`);
  if (!names.length) die(all.length  // known from the board or the desktop app, but no terminal sign-in here yet
    ? `${all.join(" and ")} ${all.length > 1 ? "are" : "is"} on the board, but not signed in to the Claude Code CLI on this computer yet\n    (the desktop app's sign-in is separate). Once per account: ${c.cyan(`coshift login ${all[0]}`)}`
    : `No accounts yet. Add one: ${c.cyan("coshift login ATLAS")}`);
  const { usage, settings } = boardUsage();
  const best = names.map((n) => ({ n, h: headroom(usage[n], settings), u: usage[n] }))
    .sort((a, b) => b.h - a.h)[0];
  const why = best.u ? `most limit left (5h ${best.u.five_hour_pct}%, weekly ${best.u.weekly_pct}%)` : "no usage known yet";
  if (best.u && best.h <= 0) warn(`Every account is at its stop line. ${best.n} has the most left.`);
  return { name: best.n, why };
}

function prepareCodex(n) {
  const dir = acctDir(n), cfg = path.join(dir, "config.toml");
  fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
  if (!fs.existsSync(cfg)) fs.writeFileSync(cfg, "");  // marks the folder as Codex's (see isCodex)
  const env = { ...process.env, CODEX_HOME: dir };
  // Codex starts MCP servers with a trimmed environment, so the account name goes in the server's own env
  const pyExe = spawnSync(python()[0], [...python().slice(1), "-c", "import sys;print(sys.executable)"], { encoding: "utf8" }).stdout.trim();
  spawnSync("codex", ["mcp", "remove", "coshift"], { env, stdio: "ignore", shell: IS_WIN });
  const extra = process.env.COSHIFT_HOME ? ["--env", `COSHIFT_HOME=${process.env.COSHIFT_HOME}`] : [];
  spawnSync("codex", ["mcp", "add", "coshift", "--env", `COSHIFT_AS=${n}`, "--env", "COSHIFT_TOOL=codex", ...extra,
    "--", pyExe, path.join(HOME, "board.py"), "serve"], { env, stdio: "ignore", shell: IS_WIN });
  return dir;
}

// Antigravity's global MCP config (older versions: ~/.gemini/antigravity/mcp_config.json)
function antigravityConfig() {
  const g = path.join(os.homedir(), ".gemini");
  return fs.existsSync(path.join(g, "config")) || !fs.existsSync(path.join(g, "antigravity"))
    ? path.join(g, "config", "mcp_config.json") : path.join(g, "antigravity", "mcp_config.json");
}
function prepareAntigravity(n) {
  const cfgPath = antigravityConfig();
  let cfg = {};
  try { const t = fs.readFileSync(cfgPath, "utf8"); if (t.trim()) cfg = JSON.parse(t); }
  catch (e) { if (e.code !== "ENOENT") die(`Can't read ${cfgPath} (${e.message}). Fix it, then run this again.`); }
  cfg.mcpServers = cfg.mcpServers || {};
  const prev = cfg.mcpServers.coshift?.env?.COSHIFT_AS;
  if (prev && prev !== n) warn(`Antigravity was connected as ${prev}; it's ${n} now (Antigravity has one sign-in per computer).`);
  const pyExe = spawnSync(python()[0], [...python().slice(1), "-c", "import sys;print(sys.executable)"], { encoding: "utf8" }).stdout.trim();
  cfg.mcpServers.coshift = { command: pyExe, args: [path.join(HOME, "board.py"), "serve"],
    env: { COSHIFT_AS: n, COSHIFT_TOOL: "antigravity", ...(process.env.COSHIFT_HOME ? { COSHIFT_HOME: process.env.COSHIFT_HOME } : {}) } };
  fs.mkdirSync(path.dirname(cfgPath), { recursive: true });
  fs.writeFileSync(cfgPath, JSON.stringify(cfg, null, 2) + "\n");
  // the previous Antigravity account's folder holds only the marker; left behind it would look like a Claude Code one
  for (const x of knownAccounts()) if (x !== n && isAntigravity(x)) fs.rmSync(acctDir(x), { recursive: true });
  fs.mkdirSync(acctDir(n), { recursive: true, mode: 0o700 });
  fs.writeFileSync(path.join(acctDir(n), "antigravity"), "");
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

async function login(args) {
  const codex = args.includes("--codex") || (args[0] && fs.existsSync(acctDir(args[0])) && isCodex(args[0]));
  const agy = args.includes("--antigravity") || (args[0] && fs.existsSync(acctDir(args[0])) && isAntigravity(args[0]));
  const name = args.find((a) => !a.startsWith("-"));
  const n = (name || await input("Account name (e.g. ATLAS)")).toUpperCase();
  if (!/^[A-Z0-9_-]{1,20}$/.test(n) || n === "ADMIN") die("Account names: 1-20 letters, digits, - or _.");
  if (agy) {
    if (fs.existsSync(acctDir(n)) && !isAntigravity(n)) die(`${n} is a ${TOOL_LABEL[toolOf(n)]} account. Pick another name for the Antigravity one.`);
    prepareAntigravity(n);
    box([`${sym.dot} Connected ${c.bold(n)} (Antigravity)`, "",
      `Sign in to the Antigravity app with the Google account you want as ${c.orange(n)},`,
      "then restart Antigravity (or refresh its MCP servers) so it loads the board.",
      `Board in ${c.dim(antigravityConfig())}`]);
    return good(`${n} is set up for Antigravity. Open a repo in it: ${c.cyan(`coshift run ${n}`)}`);
  }
  if (codex) {
    if (!has("codex")) die(`Codex isn't installed: ${c.cyan("npm i -g @openai/codex")} or ${c.cyan("brew install codex")}`);
    if (fs.existsSync(acctDir(n)) && !isCodex(n)) die(`${n} is a Claude Code account. Pick another name for the Codex one.`);
    const dir = prepareCodex(n);
    box([`${sym.dot} Signing in ${c.bold(n)} (Codex)`, "",
      "Your browser opens: sign in with the ChatGPT account you want as " + c.orange(n) + ".",
      "Your other accounts stay signed in."]);
    run("codex", ["login"], { env: { ...process.env, CODEX_HOME: dir } });
    const ok = spawnSync("codex", ["login", "status"], { env: { ...process.env, CODEX_HOME: dir }, stdio: "ignore", shell: IS_WIN }).status === 0;
    if (ok && mode() === "vercel" && !tokens()[n]) info(`For Codex on the web too, give it a board token: ${c.cyan(`coshift account add ${n}`)}`);
    return ok ? good(`${n} is signed in to Codex. Start it: ${c.cyan(`coshift run ${n}`)}`) : warn(`${n} doesn't look signed in yet. Run ${c.cyan(`coshift login ${n} --codex`)} again.`);
  }
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
  // `coshift run codex` / `coshift run claude`: the account with most limit left among that tool's accounts only
  const tool = ["codex", "claude", "antigravity"].includes(args[0]) && !knownAccounts().includes(args[0].toUpperCase()) ? args.shift() : null;
  let name = args[0] && !args[0].startsWith("-") && knownAccounts().includes(args[0].toUpperCase()) ? args.shift().toUpperCase() : null;
  let why = "chosen";
  if (!name) ({ name, why } = pickAccount(tool));
  if (!fs.existsSync(acctDir(name))) die(`${name} isn't set up on this computer. Run: ${c.cyan(`coshift login ${name}`)}`);
  console.log(`  ${sym.dot} ${c.bold(name)} ${c.dim(`· ${TOOL_LABEL[toolOf(name)]} · ${why}${acctEmail(name) ? " · " + acctEmail(name) : ""}`)}`);
  if (toolOf(name) === "antigravity")  // an app: open this folder in it; the board knows the account from its MCP config
    process.exit(process.platform === "darwin" ? run("open", ["-a", "Antigravity", process.cwd()]) : run("antigravity", [process.cwd(), ...args]));
  process.exit(run(toolOf(name), args, { env: toolEnv(name) }));
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

// One screen: accounts (limits + whether their sessions work), then this folder's project's tasks, one line each,
// with the latest note shortened to fit. --full prints everything the board has (every note in full).
function status(args) {
  if (args.includes("--full")) return process.exit(py(BOARD, ["show"]));
  const r = pyOut(BOARD, ["status-json"]);
  let s;
  try { s = JSON.parse(r.out); } catch { die(r.err.split("\n").pop() || "couldn't read the board"); }
  const W = Math.max(60, Math.min(process.stdout.columns || 100, 140));
  const fit = (t, n) => (t.length > n ? t.slice(0, Math.max(0, n - 1)) + "…" : t);
  const ago = (m) => (m == null ? "" : m < 1 ? "just now" : m < 120 ? `${m}m ago` : m < 2880 ? `${Math.floor(m / 60)}h ago` : `${Math.floor(m / 1440)}d ago`);
  banner(`status · ${s.project === "default" ? "main board" : s.project}`);
  for (const a of s.accounts) {
    const act = a.sessions ? `${a.sessions} session${a.sessions > 1 ? "s" : ""} · last action ${ago(a.last_min)}` : "no session in 3h";
    console.log(`  ${c.bold(a.name.padEnd(10))}${bar(a.five_hour_pct, s.stop_5h)}   ${bar(a.weekly_pct, s.stop_week)}   ${c.dim(act)}`
      + (a.quiet ? c.yellow(` · ${a.quiet} quiet`) : "") + (a.stop ? c.yellow("  at stop line") : ""));
  }
  const section = (title, list, line) => {
    if (!list.length) return;
    console.log(`\n  ${c.dim(title + "  " + list.length)}`);
    list.forEach(line);
  };
  const by = (st) => s.tasks.filter((t) => t.status === st);
  const asks = s.tasks.filter((t) => t.ask);
  section("NEEDS YOU", asks, (t) => console.log(`  ${c.yellow("#" + t.id)}  ${fit(t.title, W - 12)}\n       ${c.yellow("?")} ${fit(t.ask, W - 10)}`));
  section("IN PROGRESS", by("claimed"), (t) => {
    const who = `${t.owner} · ${ago(t.age_min)}` + (t.stale ? " · quiet" : "");
    console.log(`  ${c.orange(("#" + t.id).padEnd(5))}${fit(t.title, W - who.length - 12).padEnd(W - who.length - 11)} ${c.dim(who)}`);
    if (t.note) {
      const text = t.note.text.replace(/\s+/g, " ").replace(new RegExp(`^${t.note.by}:\\s*`), "");  // "FORGE: FORGE: …"
      console.log(`       ${c.dim(fit(`${t.note.by}: ${text}`, W - 9))}`);
    }
  });
  section("QUEUE", by("open"), (t) => console.log(`  ${c.dim(("#" + t.id).padEnd(5))}${fit(t.title, W - 9)}`
    + (t.blocked.length ? `\n       ${c.dim("waits: " + fit(t.blocked.join("; "), W - 16))}` : "")));
  section("RECENTLY DONE", by("done"), (t) => console.log(`  ${c.green("✓")}    ${c.dim(fit(t.title, W - 9))}`));
  if (!s.tasks.length) info("No tasks yet. Tell a session: Use the Coshift board: split <goal> into tasks, then claim one.");
  const others = s.projects.filter((p) => p !== s.project);
  console.log(`\n  ${c.dim("Every note:")} ${c.cyan("coshift status --full")}   ${c.dim("Board:")} ${c.cyan("coshift open")}`
    + (others.length ? `   ${c.dim("Other projects:")} ${others.map((p) => (p === "default" ? "main board" : p)).join(", ")}` : "") + "\n");
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
  fs.writeFileSync(auto, `[Desktop Entry]\nType=Application\nName=Coshift\nComment=Claude Code and Codex accounts on the Coshift board\nExec=${pyExe} ${script}\nX-GNOME-Autostart-enabled=true\n`);
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
      { label: "Start a session", value: "run", hint: "Claude Code or Codex, as the account with most limit left" },
      { label: "Board status", value: "status", hint: "sessions and tasks of this repo's project" },
      { label: "Projects", value: "projects", hint: "list them, or give this repo its own board" },
      { label: "Open the board page", value: "open" },
      { label: "Settings", value: "config", hint: "stop lines, context windows, phone alerts" },
      { label: "Rename an account", value: "rename", hint: "everywhere; its token keeps working" },
      ...(mode() === "vercel" ? [
        { label: "Cloud variables for an account", value: "env", hint: "copy to claude.ai/code" },
        { label: "Add the context hook to a repo", value: "hook", hint: "cloud sessions report their context" },
        { label: "Connect a repo for web sessions", value: "agents", hint: "AGENTS.md + CLAUDE.md point at the board" },
        { label: "Add an account / new token", value: "account" },
        { label: "Redeploy the board", value: "deploy" },
        { label: "Usage pusher", value: "pusher", hint: "send live limits every minute" },
      ] : []),
      { label: process.platform === "darwin" ? "Menu bar app" : "Tray icon", value: "tray", hint: "limits and alerts by the clock" },
      { label: "Doctor", value: "doctor", hint: "check everything" },
      { label: "Update Coshift", value: "update", hint: "newest version; your board too" },
      { label: "Run setup again", value: "setup" },
      { label: "Quit", value: "quit" },
    ]);
    console.log();
    if (pick === "quit") return;
    if (pick === "status") py(BOARD, ["show"]);
    if (pick === "projects") {
      py(BOARD, ["projects"]);
      if (fs.existsSync(path.join(process.cwd(), ".git")) && (await confirm("Give this repo its own board?", false))) py(BOARD, ["projects", "add"]);
    }
    if (pick === "hook") hookInstall(await input("Repo folder", process.cwd()));
    if (pick === "agents") agentsInstall(await input("Repo folder", process.cwd()));
    if (pick === "accounts") accounts();
    if (pick === "run") runAs([]);
    if (pick === "open") py(BOARD, ["web", "--open"]);
    if (pick === "config") await config([]);
    if (pick === "rename") {
      const names = knownAccounts();
      if (!names.length) info("No accounts yet.");
      else {
        const old = await select("Rename which account?", names.map((n) => ({ label: n, value: n })));
        const now = await input(`New name for ${old}`);
        if (now) renameAccount(old, now);
      }
    }
    if (pick === "doctor") doctor();
    if (pick === "update") await update([]);
    if (pick === "tray") await tray(await select(process.platform === "darwin" ? "Menu bar app" : "Tray icon",
      [{ label: "Install / restart", value: "install" }, { label: "Remove", value: "remove" }]));
    if (pick === "setup") return setup([]);
    if (pick === "deploy") { syncApp(); deployBoard(); }
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

const USAGE = `${c.bold("coshift")} ${c.dim(VERSION)}: several Claude Code and Codex accounts, one shared board per project

${c.dim("EVERY DAY")}
  ${c.cyan("coshift")}                       interactive menu
  ${c.cyan("coshift status [--full]")}       accounts and this repo's tasks at a glance
  ${c.cyan("coshift run [NAME]")}            start NAME, or the account with most limit left
  ${c.cyan("coshift run codex|claude")}      the same, only among Codex / Claude Code accounts
  ${c.cyan("coshift run antigravity")}       open this folder in Antigravity as its account
  ${c.cyan("coshift open")}                  the board page
  ${c.cyan("coshift accounts")}              every account's limits, context window and sign-in

${c.dim("ACCOUNTS")}
  ${c.cyan("coshift login NAME")}            add an account (its own Claude Code sign-in)
  ${c.cyan("coshift login NAME --codex")}    add a ChatGPT account for Codex
  ${c.cyan("coshift login NAME --antigravity")} connect Antigravity (one Google account per computer)
  ${c.cyan("coshift account rename A B")}    rename everywhere; its token keeps working
  ${c.cyan("coshift account add|rotate N")}  add an account to a Vercel board / new token
  ${c.cyan("coshift env NAME|admin")}        cloud variables for claude.ai/code (copied) / page key
  ${c.cyan("coshift map [NAME|remove]")}     tie this folder to an account

${c.dim("PROJECTS AND SETTINGS")}
  ${c.cyan("coshift project [add [NAME]]")}  list projects / give this repo its own board
  ${c.cyan("coshift config [k v [ACCT]]")}   stop lines, context windows, phone alerts
  ${c.cyan("coshift team [lead N|none]")}    this project's lead; ${c.cyan('coshift team role N "text"')} for roles, ${c.cyan("coshift team only N on")} for assigned tasks only
  ${c.cyan("coshift hook install [DIR]")}    context hook for cloud sessions (print: coshift hook)
  ${c.cyan("coshift agents [DIR]")}          point web sessions (claude.ai, Codex web) at the board

${c.dim("SETUP AND UPKEEP")}
  ${c.cyan("coshift setup")}                 guided setup (Vercel or this computer)
  ${c.cyan("coshift doctor")}                check the whole setup
  ${c.cyan("coshift update [--auto on|off]")}  newest version, board redeployed too; auto-update
  ${c.cyan("coshift deploy")}                update a Vercel board after upgrading
  ${c.cyan("coshift pusher [remove]")}       send live limits every minute
  ${c.cyan("coshift tray [remove]")}         menu bar (macOS) / tray icon (Windows, Linux)
  ${c.cyan("coshift demo [port]")}           the board with made-up data
  ${c.cyan("coshift claude-switch ...")}     macOS: swap the Claude desktop app between accounts
  ${c.cyan("coshift serve | web | call")}    internals: MCP server, local page, tools

Docs: ${c.cyan("https://github.com/pgamerx/coshift")}`;

// ---------- updates: `coshift update`, a once-a-day check, and opt-in auto-update ----------
const UPD = path.join(HOME, "update.json");  // {at, latest, auto}
const newer = (a, b) => {  // is version a newer than b?
  const x = String(a).split(".").map(Number), y = String(b).split(".").map(Number);
  for (let i = 0; i < 3; i++) if ((x[i] || 0) !== (y[i] || 0)) return (x[i] || 0) > (y[i] || 0);
  return false;
};
// The newer of npm's latest and GitHub's latest release (made only after the tests pass), so a slow or failing npm
// doesn't hide a new version. Either one answering is enough.
function latestVersion() {
  const r = spawnSync(process.execPath, ["-e", `const get = (u, f) => fetch(u, { headers: { "User-Agent": "coshift" } })
    .then((r) => r.ok ? r.json() : {}).then(f).catch(() => "");
  Promise.all([get("https://registry.npmjs.org/coshift/latest", (j) => j.version || ""),
    get("https://api.github.com/repos/pgamerx/coshift/releases/latest", (j) => (j.tag_name || "").replace(/^v/, ""))])
    .then((v) => console.log(v.join(" ")))`], { encoding: "utf8", timeout: 15000 });
  const found = (r.stdout || "").trim().split(/\s+/).filter((v) => /^\d+\.\d+\.\d+$/.test(v));
  return found.reduce((a, b) => (newer(b, a) ? b : a), "");
}
function saveUpd(patch) {
  try { fs.mkdirSync(HOME, { recursive: true }); fs.writeFileSync(UPD, JSON.stringify({ ...readJson(UPD, {}), ...patch })); } catch {}
}

async function update(args) {
  if (args[0] === "--auto") {
    if (!["on", "off"].includes(args[1])) return info(`Auto-update is ${readJson(UPD, {}).auto ? "on" : "off"}. Change it: ${c.cyan("coshift update --auto on|off")}`);
    saveUpd({ auto: args[1] === "on" });
    return good(args[1] === "on" ? "Auto-update on: Coshift installs new versions itself (checked once a day)" : "Auto-update off: you'll get a one-line notice instead");
  }
  if (args[0] === "--finish") return finishUpdate(args[1]);  // run by the newly installed version
  banner("update");
  const latest = latestVersion();
  if (!latest) die("Couldn't reach npm or GitHub to check for a new version.");
  saveUpd({ at: Date.now(), latest });
  if (!newer(latest, VERSION)) return good(`You're on the newest version (${VERSION})`);
  info(`${VERSION} → ${c.bold(latest)}`);
  const brew = fs.realpathSync(PKG).includes("/Cellar/");
  let code = brew ? run("brew", ["upgrade", "coshift"]) : run("npm", ["install", "-g", `coshift@${latest}`]);
  if (code && !brew) {  // not on npm yet (it takes a few minutes after a release) or npm is down: the release's tag
    info("npm doesn't have it yet; installing from GitHub instead…");
    code = run("npm", ["install", "-g", `github:pgamerx/coshift#v${latest}`]);
  }
  if (code) die(brew ? "brew upgrade failed" : `npm install failed. If it's a permissions error: ${c.cyan(`sudo npm install -g coshift@${latest}`)}, then ${c.cyan("coshift update")}`);
  process.exit(run("coshift", ["update", "--finish", VERSION]));
}

function finishUpdate(from) {
  // the board.py that sessions, the tray and the pusher run: a link into the package (a copy where links aren't allowed)
  const link = path.join(HOME, "board.py");
  if (fs.existsSync(link) && !fs.lstatSync(link).isSymbolicLink()) fs.copyFileSync(BOARD, link);
  good(`Coshift ${VERSION} installed${from ? ` (was ${from})` : ""}`);
  if (mode() === "vercel" && fs.existsSync(path.join(APP, ".vercel"))) {
    info("Updating your Vercel board so web sessions get the same version…");
    syncApp();
    if (!deployBoard({ quiet: true })) good("Board redeployed");
  }
  if (process.platform === "darwin" && fs.existsSync(path.join(os.homedir(), "Applications", "Claude Switch Menu.app")))
    info(`Menu bar app: ${c.cyan("coshift tray")} rebuilds it with this version.`);
  info(`What's new: ${c.cyan(`https://github.com/pgamerx/coshift/releases/tag/v${VERSION}`)}. Sessions pick up the new board on their next start.`);
}

// At most once a day, on commands people type: a one-line notice, or the update itself with auto-update on.
// The check runs in the background and the result shows next time, so no command ever waits on npm.
function checkForUpdate(cmd) {
  if (!process.stdout.isTTY || process.env.COSHIFT_NO_UPDATE_CHECK || ["update", "serve", "statusline", "call", "web", "push-usage", "-v", "--version"].includes(cmd)) return;
  const u = readJson(UPD, {});
  if (!u.at || Date.now() - u.at > 864e5) {
    saveUpd({ at: Date.now() });
    const { spawn } = require("child_process");
    spawn(process.execPath, ["-e", `fetch("https://registry.npmjs.org/coshift/latest").then(r=>r.json()).then(j=>{const fs=require("fs"),p=${JSON.stringify(UPD)};let o={};try{o=JSON.parse(fs.readFileSync(p,"utf8"))}catch{}o.latest=j.version;fs.writeFileSync(p,JSON.stringify(o))}).catch(()=>{})`],
      { detached: true, stdio: "ignore", windowsHide: true }).unref();
  }
  if (!u.latest || !newer(u.latest, VERSION)) return;
  if (u.auto && u.tried !== u.latest) {  // one try per version, so a failing install doesn't run on every command
    process.on("exit", () => {
      saveUpd({ tried: u.latest });
      console.log(`\n  ${sym.dot} Auto-update: installing coshift ${u.latest}…`);
      spawnSync("coshift", ["update"], { stdio: "inherit", shell: IS_WIN });
    });
  } else if (!u.auto) {
    process.on("exit", () => console.log(`\n  ${sym.dot} ${c.dim(`coshift ${u.latest} is out (you have ${VERSION}):`)} ${c.cyan("coshift update")}`));
  }
}

async function main() {
  const [cmd, ...rest] = process.argv.slice(2);
  checkForUpdate(cmd);
  switch (cmd) {
    case undefined: return process.stdin.isTTY ? shell() : console.log(USAGE);
    case "help": case "-h": case "--help": return console.log(USAGE);
    case "-v": case "--version": return console.log(VERSION);
    case "setup": return setup(rest);
    case "demo": return process.exit(py(path.join(PKG, "scripts", "demo.py"), rest));
    case "status": return status(rest);
    case "accounts": return accounts();
    case "login": return login(rest);
    case "run": case "start": return runAs(rest);
    case "map": return map(rest);
    case "statusline": return statusline(rest);
    case "open": return process.exit(py(BOARD, ["web", "--open"]));
    case "env": return env(rest[0]);
    case "config": return config(rest);
    case "account": return account(rest);
    case "pusher": return pusher(rest[0] === "remove" ? "remove" : "install");
    case "doctor": return doctor();
    case "update": return update(rest);
    case "tray": return tray(rest[0] === "remove" ? "remove" : rest[0] === "run" ? "run" : "install");
    case "deploy":
      if (!fs.existsSync(path.join(APP, ".vercel"))) die("no Vercel board yet. Run: coshift setup");
      syncApp();
      return process.exit(deployBoard());
    case "project": case "projects": return process.exit(py(BOARD, ["projects", ...(rest[0] === "add" ? ["add", ...rest.slice(1)] : [])]));
    case "agents": return agentsInstall(rest[0]);
    case "hook": return rest[0] === "install" ? hookInstall(rest[1]) : process.stdout.write(fs.readFileSync(path.join(PKG, "board", "board-context.sh")));
    case "claude-switch":
      if (process.platform !== "darwin") die("claude-switch swaps the Claude desktop app on macOS only.");
      return process.exit(run("bash", [path.join(PKG, "mac", "claude-switch"), ...rest])); // npm drops the exec bit
    case "serve": case "web": case "show": case "add": case "reopen": case "call": case "push-usage": case "settings": case "team":
      return process.exit(py(BOARD, [cmd, ...rest]));
    default: die(`unknown command "${cmd}". Run: coshift help`);
  }
}

main().catch((e) => die(e.message));
