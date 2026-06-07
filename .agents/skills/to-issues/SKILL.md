---
name: to-issues
description: Break a plan, spec, or PRD into independently-grabbable issues on the project issue tracker using tracer-bullet vertical slices. Use when user wants to convert a plan into issues, create implementation tickets, or break down work into issues.
---

# To Issues

Break a plan into independently-grabbable issues using vertical slices (tracer bullets).

The issue tracker and triage label vocabulary should have been provided to you — run `/setup-matt-pocock-skills` if not.

## Process

### 1. Gather context

Work from whatever is already in the conversation context. If the user passes an issue reference (issue number, URL, or path) as an argument, fetch it from the issue tracker and read its full body and comments.

If the source is a PRD issue, record its issue number as the **Parent**. Generate slices for that parent only. When several PRDs are visible, do not treat sibling PRDs as implementation slices and do not include them in the worker queue.

### 2. Explore the codebase (optional)

If you have not already explored the codebase, do so to understand the current state of the code. Issue titles and descriptions should use the project's domain glossary vocabulary, and respect ADRs in the area you're touching.

### 3. Draft vertical slices

Break the plan into **tracer bullet** issues. Each issue is a thin vertical slice that cuts through ALL integration layers end-to-end, NOT a horizontal slice of one layer.

Slices may be 'HITL' or 'AFK'. HITL slices require human interaction, such as an architectural decision or a design review. AFK slices can be implemented and merged without human interaction. Prefer AFK over HITL where possible.

<vertical-slice-rules>
- Each slice delivers a narrow but COMPLETE path through every layer (schema, API, UI, tests)
- A completed slice is demoable or verifiable on its own
- Prefer many thin slices over few thick ones
</vertical-slice-rules>

### 4. Quiz the user

Present the proposed breakdown as a numbered list. For each slice, show:

- **Title**: short descriptive name
- **Type**: HITL / AFK
- **Parent**: the PRD/source issue this slice belongs to, if any
- **Blocked by**: which other slices (if any) must complete first
- **User stories covered**: which user stories this addresses (if the source material has them)

Ask the user:

- Does the granularity feel right? (too coarse / too fine)
- Are the dependency relationships correct?
- Should any slices be merged or split further?
- Are the correct slices marked as HITL and AFK?

Iterate until the user approves the breakdown.

### 5. Publish the issues to the issue tracker

For each approved slice, publish a new issue to the issue tracker. Use the issue body template below.

Label every implementation slice with the non-state kind label `slice` (create the tracker label once if it does not exist). Label AFK slices that are fully specified with the correct triage state, usually `ready-for-agent`, unless instructed otherwise. `ready-for-agent` means "specified enough for an agent"; it does **not** mean "currently unblocked". Worker queues must still enforce the `## Blocked by` section.

Do **not** apply the `PRD` label to slices. Do **not** apply `ready-for-agent` to parent PRDs. A PRD is a planning container; a slice is the runnable assignment.

Publish issues in dependency order (blockers first) so you can reference real issue identifiers in the `## Blocked by` field. Blockers must be GitHub issue references, one per line, or the exact text `None - can start immediately`.

<issue-template>
## Parent

A reference to the parent issue on the issue tracker. Required when slicing from an existing issue or PRD. Use the exact issue reference, for example `#237 — PRD: SQLite embedded storage backend`.

## What to build

A concise description of this vertical slice. Describe the end-to-end behavior, not layer-by-layer implementation.

Avoid specific file paths or code snippets — they go stale fast. Exception: if a prototype produced a snippet that encodes a decision more precisely than prose can (state machine, reducer, schema, type shape), inline it here and note briefly that it came from a prototype. Trim to the decision-rich parts — not a working demo, just the important bits.

## Acceptance criteria

- [ ] Criterion 1
- [ ] Criterion 2
- [ ] Criterion 3

## Blocked by

- A reference to the blocking ticket, one issue per line

Or exactly `None - can start immediately` if no blockers.

</issue-template>

Do NOT close or modify any parent issue.
