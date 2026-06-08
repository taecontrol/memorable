# Memorable

Memorable gives your AI coding agent a long-term memory for a project — what was
decided, what changed, and what's true now — so it doesn't lose context between
sessions and you don't have to repeat yourself.

Instead of scattering this across Markdown files, Memorable stores it as
structured, searchable memory that your agent can write to and read back. You use
it two ways:

- **With your agent** — the **MCP server** (`memorable-mcp`) plugs Memorable into
  Claude, Cursor, and other MCP clients so the agent remembers and recalls on its
  own. This is the main way to use it.
- **By hand** — the **`memorable` CLI** lets you write, search, and inspect memory
  directly from the terminal.

Under the hood it's a GraphRAG memory system backed by embedded SQLite by
default, with Neo4j available when you explicitly select a server backend.

## Install

Run it as a one-shot tool with `uvx`:

```bash
uvx --from memorable-kg memorable --help
```

Or install it once for regular use:

```bash
uv tool install memorable-kg
```

The published distribution is `memorable-kg`; the installed commands are
`memorable` and `memorable-mcp`. The examples below assume the persistent
install — if you prefer `uvx`, prefix each command with `uvx --from memorable-kg`.

Requirements: Python 3.14+, and Docker (only if you use the bundled local Neo4j;
not needed when you point Memorable at a remote/cloud Neo4j).

## Quickstart

Start in the project directory whose memory you want to manage:

```bash
mkdir memorable-quickstart
cd memorable-quickstart
```

No database server or Docker step is required. By default, Memorable stores
project memory in embedded SQLite at `.memorable/memory.db`.

Set up memory for this project. This creates a starter config file you can grow
into later:

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

This file describes your project's memory. You can leave the three lists empty
to start — they're there for when you want to teach Memorable about your
specific domain:

- **`entities`** — the *things* in your project worth remembering, like a
  service, an API, or a person.
- **`relations`** — how those things connect, like "service A depends on
  service B."
- **`records`** — your own kinds of memory, when the built-in ones aren't
  specific enough. Each custom record `extends` a writable type — `Decision`,
  `Observation`, or `Task`.

Memorable validates this file strictly and fails loud: unknown keys are
rejected (so a typo surfaces immediately instead of being silently ignored), and
an `extends` must name one of those writable types.

You don't need any of that to get going. Memorable already understands a few
universal kinds of memory — **Decisions**, **Observations**, and **Tasks** — so
you can start saving and searching memory right away, then add project-specific
types later as you need them.

When your agent writes through the MCP server, it can also link a Decision,
Observation, or Task to the Entities it is *about*. Stapling records to the thing
they concern lets you later pull up *every* record about a given Entity — a
complete enumeration that semantic search alone can't guarantee.

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

Search for it — by meaning, not just keywords:

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

## Configuration

Memorable resolves its runtime configuration from four layered sources, each
overriding the one before it:

1. **Built-in defaults** (shown below).
2. **`.memorable/runtime.yaml`** — committed, shared project defaults.
3. **`.memorable/runtime.local.yaml`** — gitignored, per-developer overrides.
4. **`.memorable/.env`** (or environment variables) — secrets and mapped overrides.

Inspect the resolved values and where each one came from:

```bash
memorable db status
```

### What you can configure

Durable non-secret settings live in `runtime.yaml` / `runtime.local.yaml`.
Mapped `MEMORABLE_*` variables can override live commands from automation;
`memorable db status` intentionally shows the file-resolved value and source.
Secrets (Neo4j password, embedding API key) come from `.env` or the
environment.

| Setting | Env var | Default | Notes |
|---|---|---|---|
| `storage.backend` | `MEMORABLE_STORAGE_BACKEND` | `sqlite` | Storage backend selector. Use `sqlite` for the embedded local file, or `neo4j` for an explicitly selected server backend. |
| `sqlite.path` | `MEMORABLE_SQLITE_PATH` | `.memorable/memory.db` | SQLite database path, resolved relative to the project. |
| `neo4j.uri` | `MEMORABLE_NEO4J_URI` | `bolt://127.0.0.1:7687` | Bolt URI (IPv4 loopback by default to avoid ambiguous `localhost` resolution). Use `neo4j+s://…` for cloud. |
| `neo4j.user` | `MEMORABLE_NEO4J_USER` | `neo4j` | Database user. |
| `neo4j.database` | `MEMORABLE_NEO4J_DATABASE` | `neo4j` | Physical Neo4j database to open sessions against. It must already exist. |
| `neo4j.password` | `MEMORABLE_NEO4J_PASSWORD` | `memorable` | **Secret** — set via `.env`/env. |
| `docker.neo4j_version` | — | `5.26` | Image tag for the local container. |
| `docker.http_port` | — | `7474` | Local Neo4j HTTP port. |
| `docker.bolt_port` | — | `7687` | Local Neo4j Bolt port. |
| `embeddings.provider` | — | `fastembed` | `fastembed`, `openrouter`, or `fake`. |
| `embeddings.model` | — | `BAAI/bge-small-en-v1.5` | Model name for the provider. |
| `embeddings.dimensions` | — | `384` | Vector size; must match the model. |
| `embeddings.api_key` | `MEMORABLE_OPENROUTER_API_KEY` | — | **Secret** — required for `openrouter`. |

### Storage backend

SQLite is the embedded default storage backend. With no runtime config,
Memorable stores memory in `.memorable/memory.db` and uses no database server.
To use Neo4j, select Neo4j explicitly with `storage.backend: neo4j` in
runtime config.

### MemorySpace vs Neo4j database

A MemorySpace is Memorable's logical project boundary. It is named in
`.memorable/memory.yaml` under `space.name`, stored as a `space` tag on memory,
and used as a query filter for reads and writes. Many MemorySpaces can coexist
in one Neo4j database.

`neo4j.database` selects the physical Neo4j database that Memorable opens Neo4j
sessions against. It defaults to `neo4j`, can be set in `runtime.yaml` or
`runtime.local.yaml`, and can be overridden for live commands with
`MEMORABLE_NEO4J_DATABASE`. Memorable connects to the configured database; it
does not create, drop, or migrate Neo4j databases.

The bundled local runtime uses Neo4j Community Edition, which cannot create
additional physical databases. The selector targets the default/existing local
database or an externally provisioned Enterprise/Aura database; it is not a way
to spin up a second local store on the shipped image.

### Embeddings

To search by meaning, Memorable turns your memory into vectors (number lists that
capture meaning) using an *embedding provider*. Three are built in:

- **`fastembed`** (default) — runs locally via ONNX, no API key, no network.
  Default model `BAAI/bge-small-en-v1.5` at 384 dimensions.
- **`openrouter`** — remote, OpenAI-compatible API. Default model
  `google/gemini-embedding-2-preview`, whose native size is 3072 dimensions
  (it supports Matryoshka truncation to 128–3072; recommended 768, 1536, or
  3072). Memorable's built-in default for this provider is 768.
- **`fake`** — deterministic hash-based vectors for tests; do not use for real
  memory.

#### Using OpenRouter for embeddings

`.memorable/runtime.yaml` (committed):

```yaml
embeddings:
  provider: openrouter
  model: google/gemini-embedding-2-preview
  dimensions: 3072  # native size; or truncate to 1536 / 768
```

`.memorable/.env` (gitignored — keep the key out of version control):

```bash
MEMORABLE_OPENROUTER_API_KEY=sk-or-...
```

`provider`, `model`, and `dimensions` are not read from environment variables —
they must live in `runtime.yaml` / `runtime.local.yaml`. Only the API key comes
from `.env`/env.

> **Important:** `dimensions` must match the model you choose. The vector index
> is created from this value, so if you switch providers/models after writing
> memory, re-create the space against a clean database.

Verify the provider can produce a real Embedding:

```bash
memorable doctor
```

The `embedding_provider_embeds` check builds the provider, embeds a short probe,
and verifies the returned dimensions. For `fastembed`, first use may download the
local model (~67MB).

## Neo4j

### Local (Docker)

SQLite is the default and needs no container. To use the bundled local Neo4j,
first select Neo4j in `.memorable/runtime.yaml`:

```yaml
storage:
  backend: neo4j
```

Then `memorable db start` runs a packaged `docker-compose.yml` (Neo4j with the
APOC plugin, a persistent `memorable-neo4j-data` volume). Manage it with:

```bash
memorable db start    # docker compose up -d
memorable db stop     # docker compose down
memorable db status   # show resolved config + value sources
```

To customize the container (extra plugins, memory limits, etc.), eject the
template and edit your local copy — it then takes precedence over the packaged
one:

```bash
memorable db eject    # writes .memorable/docker-compose.yml
```

### Remote / cloud Neo4j

Point Memorable at an existing instance instead of running Docker. In
`.memorable/runtime.yaml`:

```yaml
storage:
  backend: neo4j
neo4j:
  uri: neo4j+s://<your-instance>.databases.neo4j.io
  user: neo4j
  database: <your-database-name>  # optional; defaults to neo4j
```

And the password in `.memorable/.env`:

```bash
MEMORABLE_NEO4J_PASSWORD=<your-password>
```

When the URI is remote (`neo4j+s://`, `neo4j+ssc://`, or a non-localhost host),
`memorable db start`/`stop` become no-ops — there is no local container to
manage. Run `memorable doctor` to confirm connectivity.

## CLI reference

Setup & diagnostics:

| Command | Purpose |
|---|---|
| `memorable init` | Create `.memorable/memory.yaml` scaffold and initialize the MemorySpace. |
| `memorable doctor [--json]` | Run health checks (connectivity, constraints, vector index, embeddings, profile). |
| `memorable status` | Print the diagnostic status payload. |
| `memorable db start\|stop\|status\|eject` | Manage / inspect the local Neo4j runtime when `storage.backend: neo4j` is selected. |
| `memorable profile show` | Show the loaded MemoryProfile. |

Writing memory (`remember`):

| Command | Writes |
|---|---|
| `memorable remember entity` | An Entity (`--id --type --name --source --at`). |
| `memorable remember decision` | A Decision (`--id --statement --source --at`, optional `--supersedes`). |
| `memorable remember observation` | An Observation (same shape as decision). |
| `memorable remember task` | A Task (`--id --title --source --at`). |
| `memorable remember relation` | A Relation between two entities (`--id --source-entity-id --target-entity-id --relation-type --statement --source --at`). |

Most write commands also accept `--space`, `--writer` (default
`agent:memorable`), and `--reason`.

Lifecycle, truth & history:

| Command | Purpose |
|---|---|
| `memorable complete task --id --at` | Mark a Task complete. |
| `memorable task inspect --id [--as-of]` | Snapshot a Task's lifecycle. |
| `memorable truth current --id` | Current truth following the supersession chain. |
| `memorable truth as-of --id --at` | Point-in-time truth. |
| `memorable inspect history --id` | Full supersession chain with lifecycle states. |
| `memorable inspect provenance --id` | Source, writer, reason, validity times. |
| `memorable invalidate --id --record-type --at` | Mark a record invalidated (no successor). |
| `memorable correct --id --record-type --new-statement --source --at` | Append a corrected statement. |

Erasure (escape hatch):

| Command | Purpose |
|---|---|
| `memorable forget --id --target-type decision\|observation\|task\|entity` | Hard-delete a record or Entity by id. |

Forget is erasure, not a lifecycle transition: it removes memory outright rather
than superseding or invalidating it, so it sits outside append-first history.
Forgetting an Entity cascades to its provenance and the relations that hang off
it. Reach for it only when the answer is "this should never have been written" —
not to retire stale truth.

Search:

| Command | Purpose |
|---|---|
| `memorable search --query [--mode current\|as-of] [--as-of]` | Hybrid GraphRAG retrieval. |

Run any command with `--help` for its full option list.

## MCP server

This is the main way to use Memorable: the MCP server connects it to your AI
agent (Claude, Cursor, and other MCP clients), so the agent can save and recall
memory on its own — no manual CLI commands.

Once connected, the agent can call **`memorable_guide`** to learn the system
in-band — call it with no topic for an index, or pass a topic (`overview`,
`writing`, `retrieval`, `temporal`, `profiles`, `recipes`, `reference`) before
writing memory or choosing how to retrieve.

The agent can also erase memory through **`memorable_forget_record`** and
**`memorable_forget_entity`** — the sanctioned escape hatch for memory that
should never have been written. These hard-delete by id (Entity-forget cascades)
and fail loud when the id is absent.

Start it manually to test:

```bash
memorable-mcp
```

Wire it into an MCP client. For Claude Desktop (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "memorable": {
      "command": "memorable-mcp"
    }
  }
}
```

If you installed with `uvx` instead of `uv tool install`, use:

```json
{
  "mcpServers": {
    "memorable": {
      "command": "uvx",
      "args": ["--from", "memorable-kg", "memorable-mcp"]
    }
  }
}
```

The server operates on the `.memorable/` of its working directory, so launch it
from (or configure your client to run it in) the project whose memory you want.
It picks up that project's `.memorable/.env`, so you do not need to repeat
secrets in the client config.

> If the client can't run the server inside the project (no `.memorable/.env`
> on disk), pass secrets via an `env` block instead. Note that when a
> `.memorable/.env` *does* exist it takes precedence and any `env` values are
> ignored:
>
> ```json
> { "command": "memorable-mcp", "env": { "MEMORABLE_OPENROUTER_API_KEY": "sk-or-..." } }
> ```

## More information

Start with the product charter in [`docs/product.md`](docs/product.md).

Maintainers cutting `0.0.x` releases should follow the [release version ladder](docs/release-version-ladder.md).
