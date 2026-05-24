---
name: code-review
description: >
  Review code changes against Memorable's Python architecture rules and coding
  guidelines. Produces a structured checklist verdict (✅/❌/🟡) covering
  boundary duplication, domain language, lint, tests, TDD order, typing, and
  module design. Use when the user asks to review code, review a PR, review a
  diff, check code quality, or says "code review".
---

# Code Review

Review the current branch diff against Memorable's rules. Produce a verdict table.

## Process

1. **Collect context** — run these in parallel:
   - `git diff main..HEAD` (or the base branch the user specifies)
   - `git log main..HEAD --oneline --reverse` (commit history)
   - `uv run ruff check src/ tests/` (lint)
   - `uv run pytest tests/ -v --tb=short` (tests)
   - If the branch references a GitHub issue, fetch it with `gh issue view`.

2. **Evaluate each rule** from the checklist in [RULES.md](RULES.md).
   - ✅ Rule satisfied.
   - ❌ Rule violated — include file, line, and what to fix.
   - 🟡 Cannot verify or minor concern — explain why.

3. **Report** — output a markdown table with one row per rule, then a summary
   with blocking issues listed first and recommendations second.

## Output Format

```
## Code Review: <branch or PR title>

| # | Rule | Verdict | Notes |
|---|------|---------|-------|
| 1 | No duplicated policy | ✅ | ... |
| ...                                  |

### Blocking
- ...

### Recommendations
- ...
```
