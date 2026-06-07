---
name: herdr-cli
description: Drive the herdr CLI (a terminal workspace manager for AI coding agents) over its socket API to inspect, read, message, wait on, and spawn agents running in panes, plus manage workspaces, tabs, git worktrees, sessions, and integrations. Use when the user mentions herdr, or asks to orchestrate/coordinate other terminal agents, read or send input to another agent's pane, wait for an agent's status, spawn an agent in a split/tab/worktree, or manage herdr sessions, config, or integrations.
---

# herdr CLI

`herdr` is a terminal workspace manager for AI coding agents. A persistent **server** holds **sessions**; the CLI talks to it over a Unix socket. Most subcommands print a single JSON line — parse it, don't eyeball it.

## Mental model

```
session ─▶ workspace ─▶ tab ─▶ pane ─▶ (an agent runs here)
```

- **IDs** are positional and distinct by separator: workspace `w65381…`, tab `w65381…:1` (colon), pane `w65381…-1` (dash), terminal `term_…`.
- **agent_status**: `idle` | `working` | `blocked` | `unknown` (the `wait` group also accepts `done`). Status only works for agents whose **integration** is installed (see `herdr integration status`).
- **Targets** (for `agent` commands) accept: terminal id, unique agent name, detected/reported agent label, or pane id. `pane`/`tab`/`workspace`/`worktree` commands take their own id type.

## Quick start

```bash
herdr status                       # is the server up?
herdr agent list                   # all agents + status + pane_id (JSON)
herdr agent read <target> --source recent --lines 80
herdr agent send <target> "do X"   # literal text, NO Enter — see "Send input"
herdr agent wait <target> --status idle --timeout 600000
```

Parse JSON with `jq`. The envelope is `{"id":…,"result":{…}}`:

```bash
herdr agent list | jq -r '.result.agents[] | "\(.agent)\t\(.agent_status)\t\(.pane_id)"'
herdr pane read <pane_id> --source recent --lines 60 | jq -r '.result.read.text'
```

## Core workflows

### Discover what's running

`herdr agent list` (or `pane list`, `tab list`, `workspace list`). Find the target/pane_id and current `agent_status` before acting.

### Read another agent's screen

`herdr agent read <target>` / `herdr pane read <pane_id>`.

- `--source visible` (default) | `recent` (scrollback) | `recent-unwrapped`.
- `--lines N` to cap; `--ansi` / `--format ansi` to keep colour codes.

The text is in `.result.read.text`.

### Send input / submit a prompt

`agent send` and `pane send-text` write **literal text without Enter**. To make a TUI agent act on a prompt, send the text, then send Enter:

```bash
herdr agent send <target> "Please run the tests and report failures"
herdr pane send-keys <pane_id> Enter
```

To run a **shell command** in a plain pane, prefer `pane run` (text + Enter):

```bash
herdr pane run <pane_id> "uv run pytest -q"
```

### Wait (blocking) before reading results

Don't poll in a loop — block on a condition:

```bash
herdr agent wait <target> --status idle --timeout 600000        # ms
herdr wait agent-status <pane_id> --status done --timeout 600000
herdr wait output <pane_id> --match "PASSED" --source recent --regex --timeout 120000
```

### Spawn a new agent

```bash
herdr agent start claude --cwd /path/to/repo --split right --focus -- claude
herdr pane split <pane_id> --direction down --cwd /path   # bare shell pane
herdr tab create --label build --cwd /path                # new tab
```

`agent start … -- <argv…>` launches the program after `--` in a fresh pane.

### Parallel agents on git worktrees

Give each agent an isolated checkout:

```bash
herdr worktree create --branch feature/x --base main --label feat-x --json
herdr worktree list --json | jq -r '.result.worktrees[] | "\(.branch)\t\(.path)"'
herdr worktree remove --workspace <workspace_id> --force --json
```

## Orchestration loop (the common pattern)

1. `agent list` → pick target + pane_id.
2. `agent send` + `pane send-keys Enter` (or `pane run`) to dispatch work.
3. `agent wait --status idle` (or `wait output --match`) to block until done.
4. `agent read --source recent` to collect the result, then decide next step.

## Gotchas

- Timeouts are **milliseconds** (`--timeout 600000` = 10 min).
- `agent send` does **not** press Enter; pair it with `pane send-keys … Enter`.
- `status` is human-readable; the `*/list`/`get`/`read` commands are JSON.
- `agent_status` is only reliable when the agent's integration is installed.
- Pane ids use `-`, tab ids use `:` — don't swap them.
- Default session is implicit; use `--session <name>` to target another.

## Full command reference

Sessions, server/update/channel, config, integrations, remote (SSH), and every flag: see [REFERENCE.md](REFERENCE.md).
