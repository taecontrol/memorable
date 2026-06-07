# Issue tracker: GitHub

Issues and PRDs for this repo live as GitHub issues. Use the `gh` CLI for all operations.

## Conventions

- **Create an issue**: `gh issue create --title "..." --body "..."`. Use a heredoc for multi-line bodies.
- **Read an issue**: `gh issue view <number> --comments`, filtering comments by `jq` and also fetching labels.
- **List issues**: `gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'` with appropriate `--label` and `--state` filters.
- **Comment on an issue**: `gh issue comment <number> --body "..."`
- **Apply / remove labels**: `gh issue edit <number> --add-label "..."` / `--remove-label "..."`
- **Close**: `gh issue close <number> --comment "..."`

Infer the repo from `git remote -v` — `gh` does this automatically when run inside a clone.

## Issue kinds

- `PRD` — planning parent. A PRD is not an implementation assignment and must not enter an AFK worker queue. Do not combine `PRD` with `ready-for-agent`.
- `slice` — implementation assignment produced from a PRD/plan. A slice may enter an AFK worker queue only when it also has `ready-for-agent` and is unblocked.

If `slice` does not exist in the tracker yet, create it once before publishing slices:

```bash
gh label create slice --color BFD4F2 --description "Implementation slice assignable to an agent"
```

A parent PRD and its slices are linked through the slice body:

```markdown
## Parent

#123 — PRD title
```

Slice blockers are machine-readable through:

```markdown
## Blocked by

- #124
- #125
```

Use exactly `None - can start immediately` when no blockers exist.

## Agent slice queue

A worker queue must not use issue number order alone. It must select runnable slices by contract:

1. Open issue has `ready-for-agent`.
2. Open issue has `slice`.
3. Issue does **not** have `PRD`.
4. `## Parent` matches the current PRD/run.
5. Every issue referenced in `## Blocked by` is closed, or the section says `None - can start immediately`.

If any of these cannot be checked, pause and ask the coordinator instead of assigning the issue.

## When a skill says "publish to the issue tracker"

Create a GitHub issue.

## When a skill says "fetch the relevant ticket"

Run `gh issue view <number> --comments`.
