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
- `/agent-room unblock [run-id]` clears a `blocked` PRD workflow and re-drives it from the last safe checkpoint (re-commit/compact/assign the current slice, recover a final-architecture fix slice, or re-request final review); intended for recovering from transient infrastructure failures
- after the last slice, architect calls `agent_finish_architecture_review`; approval pushes/opens/updates the PR, while changes requested create a synthetic final-architecture fix slice for implementer/reviewer before final review retries
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

## Source layout

The extension is a pi directory extension: `index.ts` is the entry point and
imports sibling `.ts` modules with explicit extensions. Pure, self-contained
concerns are split out; `index.ts` keeps the coupled runtime core (room
lifecycle, mailbox/prompt queue, agent sessions, tools, command router).

| Module | Concern |
| --- | --- |
| `types.ts` | Shared type declarations |
| `storage.ts` | JSON/JSONL persistence + run paths |
| `github.ts` | `gh`/`git` exec wrappers + issue fetch |
| `issues.ts` | GitHub-issue text helpers |
| `slices.ts` | Slice discovery, planning, topological order |
| `prompts.ts` | PRD prompt builders + context formatting |
| `roles.ts` | `DEFAULT_ROLES`, tool sets, role lookups |
| `dashboard.ts` | Text/tile rendering helpers |
| `publish.ts` | PR publishing (`gh pr` create/edit, body, commits) |
| `workflow.ts` | PRD phase machine (see below) |
| `index.ts` | Runtime core + command router + extension registration |

## PRD workflow phase machine

`workflow.ts` is the single source of truth for the PRD run lifecycle. The
phases (`implementing -> reviewing -> approved -> committing -> compacting ->
final-reviewing -> publishing -> done`, plus `blocked`) and the legal edges
between them live in one `PRD_TRANSITIONS` table with an ASCII diagram.

Every phase write goes through `setWorkflowPhase(room, phase)`, the only mutator
of `workflow.phase`. It validates the move against the table and **throws on an
illegal transition** so workflow bugs fail loudly instead of silently
corrupting run state, and it keeps `blockedReason` consistent (set on entering
`blocked`, cleared on leaving it). Any phase may drop to `blocked` (fail-loud);
`/agent-room unblock` re-enters from `blocked` at the last safe checkpoint.
Final architecture review changes are not an infra block: AgentRoom appends a
synthetic fix slice, returns to `implementing`, runs normal reviewer gating and
commit automation, then requests final architecture review again.

This is an internal architecture decision for the extension, not a Memorable
Core concern, so it is documented here rather than in `docs/adr/`.
