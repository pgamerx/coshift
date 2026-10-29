#!/usr/bin/env node
// coshift: one command for the Coshift board. The board itself is Python (standard library only);
// this wrapper finds it inside the installed package and keeps a deployable copy in ~/.coshift/app.
const { spawnSync } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

const PKG = path.join(__dirname, "..");
const HOME = process.env.COSHIFT_HOME || path.join(os.homedir(), ".coshift");
const APP = path.join(HOME, "app"); // what gets deployed; keeps its .vercel link across upgrades
const VERSION = require("../package.json").version;
const HINTS = {
  python3: "Coshift needs Python 3.9 or newer: https://www.python.org/downloads/",
  vercel: "Install the Vercel CLI first: npm i -g vercel",
};

const USAGE = `coshift ${VERSION}: let several Claude Code accounts share one project

  coshift demo [port]        try the board page with made-up data (no setup)
  coshift setup              link Vercel, add Upstash, name your accounts, create tokens, deploy
  coshift deploy             redeploy the board (after upgrading coshift)
  coshift hook               print the context hook (save it as .claude/hooks/board-context.sh)
  coshift serve              run the board as an MCP server (desktop sessions)
  coshift web [--open]       the board page on this machine
  coshift show | add | reopen | call <tool> [json] | push-usage
                             board commands (see: coshift call help)
  coshift claude-switch ...  macOS: swap the Claude desktop app between accounts (experimental)

Docs: https://github.com/pgamerx/coshift`;

function die(msg) {
  console.error(`coshift: ${msg}`);
  process.exit(1);
}

function run(cmd, args, opts = {}) {
  const r = spawnSync(cmd, args, { stdio: "inherit", ...opts });
  if (r.error && r.error.code === "ENOENT") die(`${cmd} not found. ${HINTS[cmd] || ""}`);
  return r.status === null ? 1 : r.status;
}

function syncApp() {
  fs.mkdirSync(APP, { recursive: true, mode: 0o700 });
  for (const p of ["api", "board", "scripts", "vercel.json", ".vercelignore"]) {
    fs.cpSync(path.join(PKG, p), path.join(APP, p), { recursive: true, force: true });
  }
}

function projectUrl() {
  try {
    const p = JSON.parse(fs.readFileSync(path.join(APP, ".vercel", "project.json"), "utf8"));
    return p.projectName ? `https://${p.projectName}.vercel.app` : "";
  } catch {
    return "";
  }
}

function setup(args) {
  syncApp();
  const here = { cwd: APP };
  if (!fs.existsSync(path.join(APP, ".vercel"))) {
    console.log("\n1/4  Create a Vercel project for your board:");
    if (run("vercel", ["link"], here)) die("vercel link failed.");
  }
  const envs = spawnSync("vercel", ["env", "ls"], { cwd: APP, encoding: "utf8" });
  if (!/KV_REST_API_URL/.test(envs.stdout || "")) {
    console.log("\n2/4  Add free Upstash Redis storage (accept its terms when asked):");
    if (run("vercel", ["integration", "add", "upstash/upstash-kv"], here)) {
      die("adding Upstash failed. Accept its terms when asked, then run coshift setup again.");
    }
  }
  console.log("\n3/4  Name your accounts and create their tokens:");
  const env = { ...process.env, COSHIFT_CLI: "1", COSHIFT_DEFAULT_URL: projectUrl() };
  if (run("python3", [path.join(APP, "scripts", "setup.py"), ...args], { cwd: APP, env })) die("setup failed.");
  console.log("\n4/4  Deploy the board:");
  if (run("vercel", ["deploy", "--prod", "--yes"], here)) die("deploy failed.");
}

const [cmd, ...rest] = process.argv.slice(2);
const board = (args) => process.exit(run("python3", [path.join(PKG, "board", "board.py"), ...args]));

switch (cmd) {
  case undefined:
  case "help":
  case "-h":
  case "--help":
    console.log(USAGE);
    break;
  case "-v":
  case "--version":
    console.log(VERSION);
    break;
  case "demo":
    process.exit(run("python3", [path.join(PKG, "scripts", "demo.py"), ...rest]));
    break;
  case "setup":
    setup(rest);
    break;
  case "deploy":
    if (!fs.existsSync(path.join(APP, ".vercel"))) die("no board yet. Run: coshift setup");
    syncApp();
    process.exit(run("vercel", ["deploy", "--prod", "--yes"], { cwd: APP }));
    break;
  case "hook":
    process.stdout.write(fs.readFileSync(path.join(PKG, "board", "board-context.sh")));
    break;
  case "claude-switch":
    if (process.platform !== "darwin") die("claude-switch is macOS only.");
    // via bash: npm doesn't keep the executable bit on non-bin files
    process.exit(run("bash", [path.join(PKG, "mac", "claude-switch"), ...rest]));
    break;
  case "serve":
  case "web":
  case "show":
  case "add":
  case "reopen":
  case "call":
  case "push-usage":
    board([cmd, ...rest]);
    break;
  default:
    die(`unknown command "${cmd}". Run: coshift help`);
}
