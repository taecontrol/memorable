# AgentRoom

Project-local Pi extension for persistent resident sub-agents.

## Commands

```text
/agent-room start [--in-place] [--base <ref>] [name]
/agent-room prd [--in-place] [--base <ref>] <issue-or-url>
/agent-room resume <run-id>
/agent-room list
/agent-room status
/agent-room ask <agent|all> <message>
/agent-room send <from> <to|all> <message>
/agent-room compact <agent|all>
/agent-room stop
```

Alias: `/room`.

## Model

- one persistent Pi `AgentSession` per resident agent
- new rooms create a git worktree by default under `.pi/agent-room/worktrees/<run-id>/`
- use `--in-place` / `--no-worktree` to run agents in the current checkout
- per-agent sessions stored under `.pi/agent-room/runs/<run-id>/sessions/`
- mailbox stored as append-only JSONL
- TUI widget renders resident-agent tiles above editor
- child sessions load Pi built-in tools plus AgentRoom communication tools

Default residents:

- `implementer` — can mutate files
- `reviewer` — read-only review
- `architect` — read-only architecture/product review

Runtime state is ignored by git via `.pi/agent-room/runs/` and `.pi/agent-room/worktrees/`.
`/agent-room stop` stops sessions but keeps the worktree/branch for inspection.
