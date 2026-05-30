# Memorable

Memorable is a project-scoped GraphRAG memory system for agents.

It stores structured project memory in Neo4j and retrieves it through the
`memorable` CLI and MCP server.

## Quickstart

Use Memorable as a one-shot tool with `uvx`:

```bash
uvx memorable --help
```

For regular use, install it once:

```bash
uv tool install memorable
```

The commands below assume the persistent install. If you prefer `uvx`, prefix
each command with `uvx`.

Start in the project directory whose memory you want to manage:

```bash
mkdir memorable-quickstart
cd memorable-quickstart
```

Start the local Neo4j runtime:

```bash
memorable db start
```

Initialize the MemorySpace and write the Minimal MemoryProfile scaffold:

```bash
memorable init --space memorable-quickstart --description "Quickstart memory"
```

The scaffold lives at `.memorable/memory.yaml`:

```yaml
version: 1

space:
  name: "memorable-quickstart"
  description: "Quickstart memory"

entities: []
relations: []
records: []
```

The Minimal scaffold has no `write_policy` block. Kernel record types persist
immediately without profile declaration, so you can remember Decisions,
Observations, and Tasks before adding project-specific types.

Check the runtime before writing memory:

```bash
memorable doctor
```

Remember your first Decision:

```bash
memorable remember decision \
  --id decision-first-memory \
  --statement "Use Memorable to keep project decisions searchable." \
  --source quickstart \
  --at 2026-05-30T00:00:00Z \
  --reason "Verify a fresh install can persist a kernel Decision."
```

Search for it with GraphRAG Retrieval:

```bash
memorable search --query "project decisions searchable"
```

The JSON result should include a hit like:

```json
{
  "source_id": "decision-first-memory",
  "source_kind": "Decision"
}
```

## More Information

Start with the product charter in [`docs/product.md`](docs/product.md).

Maintainers cutting `0.0.x` releases should follow the [release version ladder](docs/release-version-ladder.md).
