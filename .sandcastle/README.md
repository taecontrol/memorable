# Sandcastle PRD Flow

Run an AFK PRD implementation factory for Memorable using Sandcastle, Docker,
OpenCode, GitHub Issues, and a fresh per-run Neo4j container.

## Usage

```bash
pnpm implement-prd <prd-issue-url-or-number>
```

Examples:

```bash
pnpm implement-prd 42
pnpm implement-prd https://github.com/taecontrol/memorable/issues/42
```

## Prerequisites

- Docker is running.
- `gh` is authenticated for `taecontrol/memorable`.
- OpenCode OAuth auth exists at `~/.local/share/opencode/auth.json`.
- Dependencies are installed with `pnpm install`.

Optional first-run image build:

```bash
pnpm sandcastle:build-image
```

The runner also builds the image automatically if it is missing.

## Issue Conventions

- Pass an explicit PRD issue number or URL.
- Child slice issues must reference the PRD in their body or comments.
- Supported parent formats: `Parent: #N` or a `## Parent` section containing `#N`.
- Only child slices labeled `ready-for-agent` are implemented.
- `ready-for-human` and other non-AFK slices are skipped and listed in the PR.
- Dependencies are read from `## Blocked by` issue references.

## What The Runner Does

- Fetches the PRD and child slice issues with `gh` on the host.
- Creates or reuses `feat/<prd-number>-<prd-title-slug>` from `origin/main`.
- Starts a fresh `neo4j:5.26` container and private Docker network.
- Starts one long-lived Sandcastle Docker sandbox with OpenCode OAuth mounted.
- Runs each ready slice through implement, review, and bounded fix attempts.
- Runs per-slice `uv run ruff check .` and `uv run pytest tests/ -v --tb=short`.
- Commits one host-owned commit per completed slice.
- Runs final CI-equivalent verification and final architect review.
- Pushes the branch and creates or updates a PR.
- Comments on the PRD issue with the opened PR and implemented/skipped slices.

## Failure Behavior

On failure, the runner preserves useful debug state instead of cleaning it up:

- Sandcastle worktree path is printed.
- Neo4j container and Docker network names are printed.
- Random host ports for Neo4j browser and Bolt are printed.

Successful runs clean up the Neo4j container, network, and clean Sandcastle
worktree.

## Auth And Secrets

- Do not commit OpenCode or GitHub credentials.
- GitHub operations run on the host through authenticated `gh`.
- OpenCode uses the host OAuth file mounted into the sandbox.
- No OpenAI API key is required by this flow.
