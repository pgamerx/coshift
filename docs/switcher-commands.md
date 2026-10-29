# claude-switch reference

## Commands

| Command | What it does |
| --- | --- |
| `status` | Shows the active profile, whether Claude is running, live folder state, and latest backup. |
| `list` | Lists profiles; `*` marks the active one. |
| `save <name>` | Names the current Claude login as profile `<name>` (first-time setup). |
| `new <name>` | Quits Claude, stores the current profile, and starts a fresh signed-out profile `<name>`. |
| `use <name>` | Quits Claude, stores the current profile, swaps in `<name>`, and relaunches. |
| `toggle` | Switches between `CLAUDE_SWITCH_A` (default `main`) and `CLAUDE_SWITCH_B` (default `second`). |
| `backup` | Makes a timestamped APFS-clone backup of the live folder. |
| `side-by-side [n]` (alias `sbs`) | Opens the inactive profile (or `<n>`) in a second window using its stored, signed-in data; falls back to a fresh `_sidebyside/<n>` folder if it has none. |
| `side-by-side-close [n]` (alias `sbs-close`) | Quits that second instance gracefully (closing its window doesn't). `use`/`toggle` do this automatically for their target. |
| `--dry-run` (or `-n`) | Prints every action without changing anything. |

## Environment overrides

| Variable | Default | Purpose |
| --- | --- | --- |
| `CLAUDE_SWITCH_LIVE` | `$HOME/Library/Application Support/Claude` | Live folder that holds the active profile's data. |
| `CLAUDE_SWITCH_HOME` | `$HOME/ClaudeProfiles` | Folder where inactive profiles are stored (`<name>/data`) and where state, backups, and the log live. |
| `CLAUDE_SWITCH_BUNDLE_ID` | `com.anthropic.claudefordesktop` | Bundle ID used to quit Claude gracefully and to relaunch it with `open`. |
| `CLAUDE_SWITCH_APP_PATH` | `/Applications/Claude.app` | Path to the Claude app, used to identify its processes. |
| `CLAUDE_SWITCH_TIMEOUT` | `30` | Seconds to wait for Claude to fully exit before refusing to swap. |
| `CLAUDE_SWITCH_NO_LAUNCH` | `0` | Set to `1` to skip relaunching Claude after a swap. |
| `CLAUDE_SWITCH_NO_NOTIFY` | `0` | Set to `1` to suppress macOS notifications. |
| `CLAUDE_SWITCH_A` | `main` | First profile name used by `toggle`. |
| `CLAUDE_SWITCH_B` | `second` | Second profile name used by `toggle`, and the default for `side-by-side`. |
