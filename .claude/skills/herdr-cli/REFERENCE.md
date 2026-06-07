# herdr CLI — full reference

Terminal workspace manager for AI coding agents (`herdr 0.6.x`). Home: https://herdr.dev

```
session ─▶ workspace ─▶ tab ─▶ pane ─▶ (an agent runs here)
```

A persistent **server** owns one or more named **sessions** and exposes a Unix socket. The CLI is a thin client over that socket. Most subcommands emit a single JSON line: `{"id":"cli:<group>:<cmd>","result":{…,"type":"<kind>"}}`.

## Top-level

```
herdr                              Launch or attach to the persistent session
herdr --session <name>             Use/create a named session
herdr --no-session                 Run monolithically (no server/client escape hatch)
herdr --remote <ssh-target> [--session <name>]   Attach to a remote server over SSH
herdr --remote-keybindings <local|server>        Keys for --remote attach (default local)
herdr --handoff                    Opt into live handoff (with update / remote attach)
herdr --default-config             Print default config and exit
herdr status [server|client]       Local client + running server status (human-readable)
herdr update [--handoff]           Download & install the latest version
herdr --version | -V               Print version
herdr --help | -h                  Help
```

Paths & env:

- Config: `~/.config/herdr/config.toml` (override with `HERDR_CONFIG_PATH`)
- Socket: `~/.config/herdr/herdr.sock`
- Logs: `~/.config/herdr/herdr.log` (+ `herdr-client.log`, `herdr-server.log`)

## IDs & targeting

| Thing      | Example              | Separator |
|------------|----------------------|-----------|
| workspace  | `w65381eccd6fec1`    | —         |
| tab        | `w65381eccd6fec1:1`  | `:`       |
| pane       | `w65381eccd6fec1-1`  | `-`       |
| terminal   | `term_65381eccd6fa91`| —         |

`agent <subcommand> <target>` accepts a terminal id, a unique agent name, a detected/reported agent label, or a pane id. The other groups take their own id type (pane id, tab id, workspace id).

`agent_status` ∈ `idle | working | blocked | unknown`. The `wait` group also accepts `done`.

## workspace

```
herdr workspace list
herdr workspace create [--cwd PATH] [--label TEXT] [--focus|--no-focus]
herdr workspace get <workspace_id>
herdr workspace focus <workspace_id>
herdr workspace rename <workspace_id> <label>
herdr workspace close <workspace_id>
```

## tab

```
herdr tab list [--workspace <workspace_id>]
herdr tab create [--workspace <workspace_id>] [--cwd PATH] [--label TEXT] [--focus|--no-focus]
herdr tab get <tab_id>
herdr tab focus <tab_id>
herdr tab rename <tab_id> <label>
herdr tab close <tab_id>
```

## pane

```
herdr pane list [--workspace <workspace_id>]
herdr pane get <pane_id>
herdr pane rename <pane_id> <label>|--clear
herdr pane read <pane_id> [--source visible|recent|recent-unwrapped] [--lines N] [--format text|ansi] [--ansi]
herdr pane split <pane_id> --direction right|down [--cwd PATH] [--focus|--no-focus]
herdr pane close <pane_id>
herdr pane send-text <pane_id> <text>        # literal text, no Enter
herdr pane send-keys <pane_id> <key> [key …] # e.g. Enter, Escape, C-c
herdr pane run <pane_id> <command>           # command text + Enter
herdr pane report-agent <pane_id> --source ID --agent LABEL --state idle|working|blocked|unknown
      [--message TEXT] [--custom-status TEXT] [--seq N] [--agent-session-id ID] [--agent-session-path PATH]
herdr pane report-metadata <pane_id> --source ID [--agent LABEL] [--applies-to-source ID]
      [--title TEXT|--clear-title] [--display-agent TEXT|--clear-display-agent]
      [--custom-status TEXT|--clear-custom-status] [--state-label STATUS=TEXT|--clear-state-labels]
      [--seq N] [--ttl-ms N]
```

`report-agent` / `report-metadata` are how an integration pushes an agent's state/labels into herdr. You normally won't call these by hand — the installed integration hooks do.

## agent

```
herdr agent list
herdr agent get <target>
herdr agent read <target> [--source visible|recent|recent-unwrapped] [--lines N] [--format text|ansi] [--ansi]
herdr agent send <target> <text>             # literal text, no Enter
herdr agent rename <target> <name>|--clear
herdr agent focus <target>
herdr agent wait <target> --status <idle|working|blocked|unknown> [--timeout MS]
herdr agent attach <target> [--takeover]
herdr agent start <name> [--cwd PATH] [--workspace ID] [--tab ID] [--split right|down] [--focus|--no-focus] -- <argv…>
```

- `read` text lands in `.result.read.text`; `truncated` flags clipping.
- `send` writes literal text and does **not** submit; follow with `herdr pane send-keys <pane_id> Enter` to make a TUI agent act.
- `start … -- <argv…>` runs the program after `--` in a new pane (e.g. `herdr agent start claude --cwd /repo --split right -- claude`).
- `attach --takeover` seizes an already-attached agent.

## wait (blocking helpers)

```
herdr wait output <pane_id> --match <text> [--source visible|recent|recent-unwrapped] [--lines N] [--timeout MS] [--regex] [--raw]
herdr wait agent-status <pane_id> --status <idle|working|blocked|done|unknown> [--timeout MS]
```

`--timeout` is in **milliseconds**. `--regex` treats `--match` as a regex; `--raw` matches against raw (unprocessed) output. Prefer these over hand-rolled polling loops.

## worktree (git worktrees over the API)

```
herdr worktree list [--workspace ID | --cwd PATH] [--json]
herdr worktree create [--workspace ID | --cwd PATH] [--branch NAME] [--base REF] [--path PATH] [--label TEXT] [--focus|--no-focus] [--json]
herdr worktree open [--workspace ID | --cwd PATH] (--path PATH | --branch NAME) [--label TEXT] [--focus|--no-focus] [--json]
herdr worktree remove --workspace ID [--force] [--json]
```

Use to give parallel agents isolated checkouts of the same repo. `create` cuts a new branch/worktree; `open` attaches an existing one into a workspace.

## session

```
herdr session list [--json]
herdr session attach <name>
herdr session stop <name> [--json]      # use 'default' to target the default session
herdr session delete <name> [--json]
```

## integration

Installs hooks so herdr can detect an agent's live state (idle/working/blocked). Without the integration, `agent_status` is `unknown`.

```
herdr integration install   <pi|omp|claude|codex|copilot|opencode|hermes|qodercli>
herdr integration uninstall <pi|omp|claude|codex|copilot|opencode|hermes|qodercli>
herdr integration status [--outdated-only]
```

`status` reports `current (vN)`, `not installed`, or outdated per agent, with the hook path it manages (e.g. claude → `~/.claude/hooks/herdr-agent-state.sh`).

## server / channel / config

```
herdr server                       Run as a headless server
herdr server stop                  Stop the running server via the API socket
herdr server reload-config         Reload config.toml in the running server
herdr channel show                 Print the configured update channel
herdr channel set <stable|preview> Choose the update channel
herdr config reset-keys            Back up config.toml and remove custom keybindings
```

## JSON parsing cheatsheet (`jq`)

```bash
# agent name / status / pane
herdr agent list | jq -r '.result.agents[] | "\(.agent)\t\(.agent_status)\t\(.pane_id)"'

# just the screen text of a pane
herdr pane read <pane_id> --source recent --lines 80 | jq -r '.result.read.text'

# worktrees: branch + path
herdr worktree list --json | jq -r '.result.worktrees[] | "\(.branch)\t\(.path)"'

# find the pane_id for a named agent
herdr agent list | jq -r '.result.agents[] | select(.agent=="claude") | .pane_id'
```

## Notes & gotchas

- Timeouts are milliseconds.
- `agent send` / `pane send-text` never press Enter — add `pane send-keys … Enter`.
- `pane run` is the right tool for shell commands (text + Enter in one call).
- Pane ids use `-`; tab ids use `:`. They are not interchangeable.
- `status` and `integration status` print human-readable text; the list/get/read/worktree commands print JSON (some accept `--json` to force it).
- `--no-session` bypasses the server entirely — an escape hatch, not the norm.
