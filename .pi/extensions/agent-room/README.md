# AgentRoom

Project-local Pi extension for persistent resident sub-agents.

## Commands

```text
/agent-room start [--in-place] [--base <ref>] [name]
/agent-room prd [--in-place] [--base <ref>] <issue-or-url>
/agent-room resume <run-id>
/agent-room unblock [run-id]
/agent-room list
/agent-room status
/agent-room ask <agent|all> <message>
/agent-room reply <message-id|agent> <message>
/agent-room inbox
/agent-room send <from> <to|all|human> <message>
/agent-room compact <agent|all>
/agent-room stop
/agent-room destroy [run-id] [--force]
```

Alias: `/room`.

## Model

- one persistent Pi `AgentSession` per resident agent
- new rooms create a git worktree by default under `.pi/agent-room/worktrees/<run-id>/`
- use `--in-place` / `--no-worktree` to run agents in the current checkout
- per-agent sessions stored under `.pi/agent-room/runs/<run-id>/sessions/`
- mailbox stored as append-only JSONL
- agents can send human-visible updates/questions with `agent_update` / `agent_question`
- human replies use `/agent-room reply <message-id|agent> <message>` and are delivered to agent inboxes
- resident prompts are serialized: only one agent runs at a time
- PRD runs gate slices with `agent_submit_review` → reviewer `agent_finish_review`
- approved slices are committed, then all agents are compacted before the next slice assignment
- compaction retries transient provider overloads (`overloaded_error` / HTTP 529) with exponential backoff so a momentary API hiccup does not wedge the workflow
- `/agent-room unblock [run-id]` clears a `blocked` PRD workflow and re-drives it from the last safe checkpoint (re-commit/compact/assign the current slice, or re-request final review); intended for recovering from transient infrastructure failures
- after the last slice, architect calls `agent_finish_architecture_review`; AgentRoom pushes the branch, opens/updates the PR, and comments on the PRD issue
- TUI widget renders resident-agent tiles, PRD slices, workflow state, and latest human-directed message above editor
- child sessions load Pi built-in tools plus AgentRoom communication tools

Default residents:

- `implementer` — can mutate files; must use `.agents/skills/tdd/SKILL.md` for implementation work
- `reviewer` — read-only review
- `architect` — read-only architecture/product review

`/agent-room prd` follows the Sandcastle PRD flow shape: fetch parent PRD, discover child issues that reference it, filter `ready-for-agent`, topologically order `Blocked by` dependencies, and start residents with the full slice plan. PRD worktrees default to `origin/main` unless `--base` or `--in-place` is supplied.

Runtime state is ignored by git via `.pi/agent-room/runs/` and `.pi/agent-room/worktrees/`.
`/agent-room stop` stops sessions but keeps the worktree/branch for inspection.
`/agent-room destroy [run-id] [--force]` stops the run, removes its AgentRoom worktree, and deletes run temp files.
