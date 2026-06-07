# repo-tools

Safe git + GitHub tools for pi. Phase 1 of replacing `bash` in interactive sessions.

## Tools

Read-only:

- `git_inspect` — `status`, `diff`, `log`, `info`
- `gh_issue_view` — fixed `gh issue view` JSON read
- `gh_run_inspect` — fixed `gh run view` status + failed logs for Actions run/job URLs

AFK-safe write / network mutation:

- `git_branch_create` — `git switch -c <branch> [start_point]`
- `git_commit` — `git add -A` or `git add -- <paths>`, then `git commit -m <message>`
- `git_push` — `git push [--set-upstream] origin <current-branch>`
- `git_restore` — fixed `git restore` for selected paths
- `gh_pr_create` — fixed `gh pr create` from current branch

## Policy

- No shell execution.
- No raw git/gh argument passthrough.
- Tool code builds argv from validated inputs.
- Nonzero git/gh exits are normal tool results, not tool execution errors.
- Output is truncated to pi's built-in limits; full output is written to a temp file when truncated.
- Write tools do not prompt for confirmation; they are intended for AFK agent workflows.
- Safety comes from constrained argv, validation, no raw passthrough, no force push, and serialized git mutations.
- Git writes are serialized by an in-extension repo mutation lock.
- `git_push` only pushes the current branch to `origin`; no force push.
- `git_commit` rejects `Co-authored-by: Claude` trailers.
- `gh_run_inspect` does not watch/block; call it again to re-check CI after pushing.

## Bash replacement ledger — Phase 1

Covered here:

- git status/diff/log/info
- branch creation
- commit
- push
- restore selected paths
- GitHub issue reads
- GitHub Actions failure inspection
- PR creation

Still outside this extension:

- code search / ripgrep replacement
- ad-hoc scratch repro scripts
