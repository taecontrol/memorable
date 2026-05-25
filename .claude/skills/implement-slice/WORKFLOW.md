# Workflow

## Step 1: Parse Input

Extract owner, repo, and issue number from the GitHub issue URL.
Supported formats:

- `https://github.com/owner/repo/issues/42`
- `owner/repo#42`

## Step 2: Validate Git State

Run `git status --porcelain` and `git branch --show-current`.

- **Dirty working tree** → stop with: "Working tree has uncommitted changes. Commit or stash before running /implement-slice."
- **On `main`** → will create branch in step 4.
- **On a feature branch** → validate it matches the parent issue (step 3).

## Step 3: Fetch Issue Context

Run these in parallel:

```bash
gh issue view <number> -R <owner/repo> --json title,body,comments
```

Parse `Parent: #N` from the slice issue body (first match). Then:

```bash
gh issue view <parent-number> -R <owner/repo> --json title,body,comments
```

If no `Parent: #N` found, stop with: "Could not find parent issue reference. Expected `Parent: #N` in the issue body."

Build the context payload:

- **Slice**: title, body, all comments
- **Parent**: title, body only (no comments)

## Step 4: Branch Management

Slugify the parent issue title: lowercase, replace non-alphanumeric with `-`, collapse consecutive `-`, trim leading/trailing `-`.

Target branch: `feat/<parent-number>-<slugified-title>`

| Current branch | Target exists? | Action                                                                  |
| -------------- | -------------- | ----------------------------------------------------------------------- |
| `main`         | No             | `git checkout -b feat/N-slug`                                           |
| `main`         | Yes            | `git checkout feat/N-slug`                                              |
| Target branch  | —              | Stay, no action                                                         |
| Other branch   | —              | Stop with: "Currently on `<branch>`, expected `main` or `feat/N-slug`." |

## Step 5: Implement (Subagent Round)

Spawn a `python-developer` subagent with the following prompt structure:

> You are implementing a slice for the Memorable project.
>
> ## Parent Issue: `<parent-title>` (#`<parent-number>`)
>
> `<parent-body>`
>
> ## Slice: `<slice-title>` (#`<slice-number>`)
>
> `<slice-body>`
>
> ## Slice Comments
>
> `<comments>`
>
> ## Instructions
>
> Use the `tdd` skill to implement this slice. Read the acceptance criteria
> in the slice and encode them as tests. For each acceptance criterion,
> write a RED test first, then make it GREEN with minimal code.
>
> After implementation, run the full test suite: `uv run pytest tests/ -v --tb=short`
>
> [If round 2, append review findings from the previous round here]

## Step 6: Review (Subagent Round)

Spawn a `python-developer` subagent:

> You are reviewing a slice implementation for the Memorable project.
>
> ## Slice: `<slice-title>` (#`<slice-number>`)
>
> `<slice-body>`
>
> ## Instructions
>
> Use the `code-review` skill to review the current diff against main.
> Focus your review on the changes from this slice.
>
> After the review, state clearly whether the review is **CLEAN** (all ✅)
> or **HAS FINDINGS** (any ❌ or 🟡). List each finding with file, line,
> and what to fix.

## Step 7: Feedback Loop

- If review is **CLEAN** → proceed to step 8.
- If review **HAS FINDINGS** and this is round 1 → go to step 5 with
  findings appended to the implementer prompt.
- If review **HAS FINDINGS** and this is round 2 → proceed to step 8,
  surface remaining findings to the user.

## Step 8: Verify Acceptance Criteria

Run `uv run pytest tests/ -v --tb=short`.

- If tests fail → do NOT commit. Report failures to the user.
- If tests pass → check for non-testable acceptance criteria in the slice
  issue body (e.g., documentation, config). Use judgment to verify these
  by inspecting the working tree.

## Step 9: Commit

If tests pass:

```bash
git add <changed-files>
git commit -m "feat: implement #<slice-number> - <slice-title>

Closes #<slice-number>"
```

Include `Closes #<slice-number>` only if closing conditions are met (step 10).

## Step 10: Close Issue

Close the issue if **all** of these are true:

- Final review is **CLEAN** (all ✅)
- All tests pass
- Non-testable acceptance criteria are satisfied

```bash
gh issue close <number> -R <owner/repo>
```

If not closing, report to the user:

- What was implemented and committed
- Which review findings remain
- Which acceptance criteria were not met
