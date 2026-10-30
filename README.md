# Coshift

**Run several Claude Code accounts on one project at once. They split the work, hand over at their limits, and restart from a saved summary instead of compacting.**

[![npm](https://img.shields.io/npm/v/coshift?color=c96442&label=npm)](https://www.npmjs.com/package/coshift)
[![homebrew](https://img.shields.io/badge/homebrew-pgamerx%2Ftap-c96442)](https://github.com/pgamerx/homebrew-tap)
[![tests](https://github.com/pgamerx/coshift/actions/workflows/test.yml/badge.svg)](https://github.com/pgamerx/coshift/actions/workflows/test.yml)
![platforms](https://img.shields.io/badge/macOS%20·%20Windows%20·%20Linux-555)
[![license](https://img.shields.io/badge/license-MIT-blue)](https://github.com/pgamerx/coshift/blob/main/LICENSE)

![Two Claude Code accounts claim different tasks from a shared board; one hits its 5-hour limit and hands its task over with notes; at 70% context a session saves a summary and a new one resumes from two lines](https://raw.githubusercontent.com/pgamerx/coshift/main/docs/img/coshift-demo.gif)

```bash
npx coshift demo     # see the board with demo data, no setup
```

## Why

You hit your 5-hour limit halfway through a task, ask Claude for a handover document, switch accounts, paste it in, and hope nothing got lost. Coshift lets your accounts do that themselves, like a shift change in a hospital: whoever comes on picks up exactly where the last one stopped.

## What you get

- **A shared task board.** Sessions claim their own tasks. Two sessions never take the same task or edit the same files.
- **Handovers at your limits.** Near the stop line (85% of the 5-hour limit or 90% weekly, both adjustable) a session hands its task over with notes, and another account carries on.
- **Restarts instead of compaction.** At 70% context a session saves a summary; a fresh one resumes from two lines.
- **Any number of accounts.** `coshift run` starts Claude Code as the account with the most limit left.
- **A board for your phone.** Limits, tasks, questions from your sessions, standing rules. Light and dark.
- **Limits by the clock.** A menu bar app on macOS and a tray icon on Windows and Linux.

![The Coshift team board: accounts with live limits, a question waiting for you, tasks with the files they own. Desktop in light mode, phone in dark mode](https://raw.githubusercontent.com/pgamerx/coshift/main/docs/img/board-overview.png)

## Quick start

```bash
npm install -g coshift          # or: brew install pgamerx/tap/coshift
coshift setup                   # your system, where the board lives (Vercel, free; or this computer), your accounts
coshift login ATLAS             # sign in each account once; each gets its own Claude Code profile
coshift login FORGE
coshift run                     # Claude Code as the account with the most limit left
```

Then tell the session: *Use the Coshift board: split [your goal] into tasks, then claim one.* Start more sessions the same way and they pick up the rest.

![coshift accounts: live 5-hour and weekly limits and the context window of every account](https://raw.githubusercontent.com/pgamerx/coshift/main/docs/img/cli/cli-accounts.png)

<details>
<summary>The setup wizard</summary>

![coshift setup: your system, where the board lives, your accounts and their context windows, then a summary](https://raw.githubusercontent.com/pgamerx/coshift/main/docs/img/cli/cli-setup.png)

</details>

## How it works

![Sessions on every account talk to the Coshift board with their own token; live limits come from Claude Code's status line; a hook reports each session's context; you steer from your phone](https://raw.githubusercontent.com/pgamerx/coshift/main/docs/img/how-it-works.png)

Sessions coordinate through the board, not through you. Each account signs in with its own Claude Code profile, so Coshift never touches a password or token. Live limits come from Claude Code's own status line. Cloud sessions on claude.ai/code reach the board over HTTPS; desktop and terminal sessions use it as an MCP server.

**[Read the full guide →](https://github.com/pgamerx/coshift/blob/main/docs/GUIDE.md)** for cloud sessions, the context hook, every command and tool, settings, trays and security.

## FAQ

**Is running several accounts allowed?** Check [Anthropic's terms](https://www.anthropic.com/legal/consumer-terms) for your plan. Coshift doesn't change any limits; it coordinates sessions you already run.

**Windows and Linux?** Yes. The board, the CLI, accounts and live limits work on all three. The desktop-app switcher in `mac/` is the only macOS-only part.

**How many accounts?** As many as you have. Each one gets its own token, profile and colour on the board.

---

MIT licensed. Formerly called Baton.
