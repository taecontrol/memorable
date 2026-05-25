Memorable is a project-scoped memory system for agents. Before changing the product model, read the core docs in this order:

1. `docs/product.md` - product promise, principles, scope, and non-goals.
2. `docs/ubiquitous-language.md` - authoritative language for Memorable Core and agent-facing terms.
3. `docs/adr/` - accepted architecture decisions.
4. `docs/researches/` - research notes and decision background.

## Working Rules

- Treat `docs/ubiquitous-language.md` as the naming source of truth for core code, schemas, product docs, and MCP tools.
- Update the ubiquitous language when a core domain term is introduced, renamed, split, merged, or made authoritative.
- Keep storage vocabulary inside storage contexts. For example, use `Entity` or `Relation` in core language, not Neo4j `Node` or `Edge`.
- Treat Markdown summaries, reports, plans, and reviews as generated views unless their contents are intentionally written back as structured memory.
- Preserve temporal semantics: current truth, point-in-time truth, provenance, lifecycle transitions, correction, supersession, and append-first history are core product concerns.
- Add or update an ADR when a decision changes architecture, storage strategy, core temporal behavior, profile semantics, or agent-facing interfaces.

## Agent skills

### Issue tracker

Issues live in GitHub Issues on `taecontrol/memorable`. See `docs/agents/issue-tracker.md`.

### Triage labels

Default label vocabulary (needs-triage, needs-info, ready-for-agent, ready-for-human, wontfix). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout — `docs/ubiquitous-language.md` + `docs/adr/` at the repo root. See `docs/agents/domain.md`.

## Commits

- No Co-Authored-By: Claude … trailer on commits. AI is a tool, not a co-author.
