# Coshift guide

Everything beyond the [README](../README.md): setup paths, accounts, cloud sessions, the context hook, the board's tools, settings, trays, security and development.

- [Setup](#setup)
- [Accounts](#accounts)
- [Working with the board](#working-with-the-board)
- [Cloud sessions](#cloud-sessions)
- [The context hook](#the-context-hook)
- [Live limits](#live-limits)
- [Settings](#settings)
- [Menu bar and tray](#menu-bar-and-tray)
- [Commands](#commands)
- [Board tools](#board-tools)
- [Security](#security)
- [macOS desktop-app switcher](#macos-desktop-app-switcher)
- [Development](#development)

## Setup

Requirements: Node 18+ and Python 3.9+ on Windows, macOS or Linux. Install with `npm install -g coshift` or `brew install pgamerx/tap/coshift`, then run `coshift setup`. It asks five things:

1. **Your system.** Detected for you; you can pick another with the arrow keys.
2. **Where the board lives.**
   - **Vercel** (free, recommended). The board runs on your own Vercel project with free Upstash Redis storage, so you can open it from your phone and cloud sessions can reach it. Setup creates the project, adds the storage (accept Upstash's terms when asked), creates one token per account and deploys. You need a Vercel account and the Vercel CLI (`npm i -g vercel`).
   - **This computer only.** No account needed. The page runs at `http://127.0.0.1` and only this computer's sessions can use it: no phone, no cloud sessions. You can switch later by running setup again.
3. **Your accounts.** Any names, any number, e.g. `ATLAS,FORGE,NOVA`.
4. **Each account's context window.** 200K (Pro and most models) or 1M (Max with a 1M-context model; check with `/context`). Sessions started with `coshift run` also report the real size automatically.
5. **Extras.** Connect desktop sessions to the board (MCP), and send live usage from this computer every minute.

Everything you need afterwards is in `~/.coshift/` (readable only by you): `cloud-setup.txt`, `tokens.json`, `remote.json`. Re-running setup keeps your tokens. After upgrading Coshift, `coshift deploy` updates your board.

From a clone instead of npm: `vercel link && vercel integration add upstash/upstash-kv && python3 scripts/setup.py && vercel deploy --prod`, or `python3 scripts/setup.py --local`.

## Accounts

Each account gets its own Claude Code profile folder (`~/.coshift/accounts/NAME`, used through Claude Code's `CLAUDE_CONFIG_DIR`). Claude Code keeps each folder's sign-in separate (its own Keychain entry on macOS, its own credentials file elsewhere), so Coshift never reads or copies a password or token.

| Command | What it does |
|---|---|
| `coshift login NAME` | Opens Claude Code with that account's profile so you can sign in once (type `/login` if it doesn't ask), then `/exit`. Also connects the board and the status line for that profile. |
| `coshift run [NAME] [claude args]` | Starts Claude Code as NAME. Without a name: the account mapped to this folder, else the one with the most limit left. Extra arguments go to Claude Code (`coshift run ATLAS --resume`). |
| `coshift map NAME` / `coshift map remove` | Ties the current folder (and its subfolders) to an account. |
| `coshift accounts` | Live 5-hour and weekly limits, context window and sign-in of every account. |

Accounts you only use in the cloud don't need `login`; their limits come from their sessions.

## Working with the board

Sessions follow a protocol the board gives them when they connect:

- **Claim, don't overlap.** `claim_task` hands out the next open task. Claims are atomic: two sessions never get the same task, even at the same moment.
- **Own your files.** Tasks list the paths they edit (`src/auth/`, `*.css`). A task whose files overlap a running task isn't handed out until that one finishes.
- **Order.** Tasks can depend on others (`depends_on`); they wait until those are done.
- **Notes as you go.** Every task keeps its notes: done so far, next step, files, branch.
- **Ask, don't stall.** A session blocked on a decision calls `ask_user`. It's highlighted at the top of the page (and pushed to your phone if alerts are on); your answer reaches that session on its next board call.
- **Ports.** Before starting a dev server or database, a session calls `lease_port` and gets its own port range, so parallel servers don't collide.
- **Stop lines.** Near the 5-hour or weekly stop line, a session finishes its small step and releases its task with a full handover.
- **Dead sessions free their claims.** A claim is free for another account once the session holding it has gone silent past the stale time (45 minutes by default). A busy session never loses its claim.

From the page you can add tasks (with files and order), answer questions, add notes, reopen or cancel tasks (cancelled tasks are kept, just hidden), send a one-off message to one account or all, and write **guidance**: standing rules every session sees with each board check until you remove them. Add `?theme=light` or `?theme=dark` to the page's address to force a theme.

### Starter prompts

New goal:
> Use the Coshift board. Split this goal into independent tasks with add_task, then claim one and start: [your goal]

Join the work:
> Use the Coshift board: report your usage, then claim and work through the open tasks. Leave notes as you go and hand over if you get near your limit.

A session that already has its own task list: copy the "Starter prompts" text from the bottom of the page.

## Cloud sessions

Cloud sessions on claude.ai/code reach a Vercel board over HTTPS. For each account, in its cloud environment settings:

- **Environment variables:** `COSHIFT_URL` and that account's `COSHIFT_TOKEN`. `coshift env NAME` prints them and copies them to the clipboard.
- **Network access:** allow your board's host (e.g. `my-coshift.vercel.app`).

The two-line prompt that starts or restarts a cloud session, the same for every account:

```
Run: curl -sS "$COSHIFT_URL/api/help" -H "Authorization: Bearer $COSHIFT_TOKEN" and follow it.
Start with board resume and continue from your saved context.
```

`/api/help` gives the session the protocol and a small `board` shell function; after that it's `board claim_task`, `board add_note '{"id": 3, "text": "…"}'` and so on.

## The context hook

A Claude Code `PostToolUse` hook reports how full each session's context is. At the stop line (70% by default) the session takes no new task, finishes the current one, saves a summary with `save_context`, and gives you the two-line prompt. The next session's `resume` returns that account's latest summary (the last five are kept) and its claimed tasks.

Install it once per repository: have one session fetch `$COSHIFT_URL/api/hook` and follow its steps, or run `mkdir -p .claude/hooks && coshift hook > .claude/hooks/board-context.sh` and add the `settings.json` entry `/api/hook` shows. It does nothing unless `COSHIFT_URL` and `COSHIFT_TOKEN` are set, so it's harmless for anyone else in the repository. The hook sends raw token counts; the board turns them into percentages using each account's context window.

## Live limits

The board shows each account's 5-hour and weekly usage from the newest of these sources:

1. **Claude Code's status line.** `coshift login` sets each profile's status line to `coshift statusline NAME`, which shows `◆ ATLAS · 5h 42% · wk 31% · ctx 18%` in Claude Code and quietly reports to the board (at most every 30 seconds, in the background). Works on every system. Needs a Pro or Max plan; the numbers appear after the session's first reply.
2. **Sessions themselves** (`report_usage`), e.g. desktop sessions with the app's usage tool.
3. **The usage pusher** (`coshift pusher`), which sends this computer's numbers every minute: a LaunchAgent on macOS, Task Scheduler on Windows, a systemd timer or cron on Linux. It reads the Claude desktop app and, on macOS, the Claude Usage menu bar app (set `COSHIFT_USAGE_APP=` to turn that off).

Cloud sessions can't read their own plan usage; without one of these sources they get a "usage unknown" warning and work on.

## Settings

Settings live on the board itself, so a change applies to every session at once without a redeploy. Change them on the page (Setup → Settings) or with `coshift config`.

| Setting | Default | Meaning |
|---|---|---|
| `stop_5h` | 85 | Stop at this % of the 5-hour limit |
| `stop_week` | 90 | Stop at this % of the weekly limit |
| `stop_context` | 70 | Save a summary and restart at this % of the context window |
| `stale_min` | 45 | Minutes of silence after which a session's claim is free |
| `context_window` | 200000 | Default context window; per account: `coshift config context_window 1000000 ATLAS` |
| `ntfy_topic` | off | [ntfy.sh](https://ntfy.sh) topic for phone alerts when a session asks you something |
| `port_base`, `port_block` | 4100, 10 | Port ranges handed out by `lease_port` |

Environment variables set the defaults on a new board: `COSHIFT_STOP_5H`, `COSHIFT_STOP_WEEK`, `COSHIFT_STOP_CONTEXT`, `COSHIFT_CONTEXT_WINDOW`, `COSHIFT_NTFY_TOPIC`. `COSHIFT_HOME` moves `~/.coshift`.

## Menu bar and tray

`coshift tray` installs the right one for your system and starts it at login:

- **macOS:** the menu bar app shows the active account's limits in the bar (`ATLAS 72% · 41%`), every account's 5-hour and weekly limits in the menu, starts Claude Code as an account in Terminal, opens the board, and notifies you when a session asks something. It's built on your Mac (needs Apple's command line tools: `xcode-select --install`). Turn on **Launch at Login** in its menu.
- **Windows:** an icon in the notification area. Hover for limits; click for the same menu; a pop-up when a session needs you. Built with Windows PowerShell, nothing to install.
- **Linux:** a panel icon on desktops with AppIndicator support (KDE, Cinnamon, XFCE, Ubuntu; plain GNOME needs the AppIndicator extension), otherwise desktop notifications.

`coshift tray remove` takes it out again.

## Commands

| Command | |
|---|---|
| `coshift` | Interactive menu |
| `coshift setup` | Guided setup |
| `coshift demo [port]` | The page with made-up data |
| `coshift accounts` / `login` / `run` / `map` | See [Accounts](#accounts) |
| `coshift status` | Sessions and tasks in the terminal |
| `coshift open` | Open the board page |
| `coshift env NAME` / `coshift env admin` | An account's cloud variables / the page key, copied to the clipboard |
| `coshift config [key value [ACCOUNT]]` | Show or change settings |
| `coshift account add NAME` / `rotate NAME` | Add an account to a Vercel board, or give one a new token |
| `coshift pusher [remove]` | Usage pusher |
| `coshift tray [remove]` | Menu bar / tray |
| `coshift deploy` | Redeploy the board after upgrading |
| `coshift doctor` | Check the whole setup |
| `coshift hook` | Print the context hook |
| `coshift statusline NAME` | The status line command (Claude Code calls it) |
| `coshift serve`, `web`, `call` | Board internals: MCP server, local page, run a tool |

## Board tools

| Tool | What it does |
|---|---|
| `resume` | Start of a session: this account's saved summary, its claimed tasks with notes, guidance |
| `board_status` | Every account's usage and all tasks |
| `claim_task` | Your unfinished task first, else the next unblocked open one (or `{"id": N}`) |
| `add_task` | Add a task; `files` it owns, `depends_on` ids, `done_summary` for finished work |
| `update_task` | Change a task's title, detail, files or dependencies |
| `add_note` | Progress note on a task |
| `complete_task` / `release_task` | Finish a task, or give it back with a full handover |
| `ask_user` | Flag a question for you on a task |
| `lease_port` | This session's port range |
| `report_usage` / `report_context` | Usage and context numbers (usually sent for you) |
| `save_context` | Save a summary for this account's next session |

## Security

- Every hosted API call needs a token. Each account has its own token and the page has a separate admin key; tokens are compared in constant time. Tokens live in your Vercel project's environment and in `~/.coshift/` (mode 600). Nothing secret is in the repository.
- Account sign-ins stay with Claude Code; Coshift only sets which profile folder Claude Code uses.
- The local page listens on 127.0.0.1 only and rejects other Hosts, other Origins and non-JSON posts.
- The usage readers take percentages, reset times and account IDs only, never session keys.
- The board deletes nothing: cancelled tasks and removed guidance are kept, just hidden.

## macOS desktop-app switcher

`mac/claude-switch` swaps the Claude **desktop app** between accounts without signing out, and can open another account in a second window side by side (`coshift claude-switch status`, `toggle`, `side-by-side`). It works by renaming the app's data folder, with a backup before the first swap. It depends on how the desktop app stores its data, which isn't a public interface, so an app update could break it. See [switcher commands](switcher-commands.md). The board doesn't need it.

## Development

```bash
python3 tests/test-board.py      # board over MCP, the page API and its security checks
python3 tests/test-features.py   # files, dependencies, questions, settings, ports, liveness, many accounts
python3 tests/test-cloud.py      # hosted API + the real context hook
bash mac/tests/test-sandbox.sh   # desktop-app switcher, in a throwaway folder
```

No dependencies, no network, nothing touches your real data. CI runs them on Windows, macOS and Linux and smoke-tests the npm package on all three. The animation and diagrams are a small [Remotion](https://www.remotion.dev) project in `docs/animation` (`npm i && npm run gif`).

**Releasing:** bump `version` in `package.json`, commit, `npm publish`, `git tag vX.Y.Z && git push --tags`. Once `npx coshift@X.Y.Z --version` works (npm takes a few minutes), update the version and `sha256` in [homebrew-tap](https://github.com/pgamerx/homebrew-tap)'s `Formula/coshift.rb`.
