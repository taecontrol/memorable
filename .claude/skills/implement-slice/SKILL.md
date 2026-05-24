---
name: implement-slice
description: >
  Implement a GitHub issue slice end-to-end using TDD with automated code review.
  Takes a GitHub issue URL, validates git state, creates a feature branch from the
  parent issue, implements via TDD, reviews, and auto-commits. Use when the user
  says "implement slice", "implement this slice", passes a GitHub issue link to
  implement, or says "/implement-slice".
argument-hint: "<github-issue-url>"
---

# Implement Slice

Implement a single vertical slice from a GitHub issue using TDD and automated
code review. See [WORKFLOW.md](WORKFLOW.md) for the full step-by-step process.

## Quick Start

The user provides a GitHub issue URL. The skill:

1. Validates clean git state and correct branch
2. Fetches slice + parent issue context via `gh`
3. Creates/verifies feature branch from parent issue
4. Spawns implementer subagent (python-developer + tdd skill)
5. Spawns reviewer subagent (python-developer + code-review skill)
6. Loops up to 2 rounds until review is clean
7. Auto-commits and closes issue if all criteria pass

## Conventions

- **Parent detection**: slice issue body contains `Parent: #N`
- **Branch naming**: `feat/<parent-number>-<slugified-parent-title>`
- **All slices for a parent share one branch** — no branch-per-slice
- **Commit message**: `feat: implement #<slice> - <slice-title>`
