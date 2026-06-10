# ADR 0026: Per-Backend Vector Index — sqlite-vec For The SQLite Backend

> Renumbered from a duplicate "ADR 0022" — that number belongs to Typed Durable Attributes On Types.

Date: 2026-06-07
Status: Accepted
Refines: ADR 0020

## Context

ADR 0020 established a persistent Embedding index behind a retrieval-owned port (`RetrievalIndex`), so search embeds the query once and reads candidates from a durable index instead of re-embedding the whole MemorySpace. Its production adapter stored Embeddings in Neo4j's `memorable_embeddings_vector` index, and it explicitly rejected an external vector store while Neo4j was the only runtime.

ADR 0025 adds a co-equal SQLite backend and makes it the default. SQLite has no built-in vector index, so the SQLite backend needs its own `RetrievalIndex` implementation. The port already isolates this choice: it is the cheapest thing in the system to replace, and Embeddings are derived — regenerable from Indexable Text via `recreate_index` — so changing the vector index is a reindex, never a canonical-data migration.

Two facts bound the decision:

- The realistic per-MemorySpace ceiling is ~10k retrievable items. At that size, brute-force KNN over stored vectors is sufficient; approximate-nearest-neighbor (ANN) indexing is not yet needed. numpy-vectorized cosine over 10k × 384 is sub-10ms; the legacy pure-Python `_cosine_similarity` triple loop is ~1–2s and must not be used at that scale.
- `sqlite-vec` is a SQLite loadable extension providing vector storage and KNN in the same database file. It is pre-v1 (0.1.9) with a small maintainer base, but it is MIT-licensed, ships platform wheels covering Python 3.14 with no compile step, and — verified empirically — loads cleanly on Memorable's mandated toolchain (uv-managed CPython via python-build-standalone, which enables loadable SQLite extensions) and on Homebrew, Linux-distro, conda-forge, and Windows ≥3.11 interpreters. It does not load on python.org-macOS / macOS-system / default-pyenv interpreters, whose stdlib `sqlite3` links Apple's libsqlite3 with extension loading disabled.

The forces:

- The SQLite backend needs a persistent vector index satisfying the ADR 0020 contract (metadata: MemorySpace, source id / kind, Indexable Text hash, provider, model, dimensions, vector; provider/model/dimension-compatible search; includes superseded, invalidated, and completed records).
- Index maintenance must stay synchronous and fail-loud (ADR 0020); silent staleness or silent slow fallback is worse than a visible error.
- The vector index must be swappable without touching the storage-backend decision.
- A loadable-extension dependency must not silently degrade the default install promise.

## Decision

For the SQLite backend, use `sqlite-vec` as the single persistent `RetrievalIndex` implementation, behind the existing port. The vector lives in the same SQLite database and the same transaction as the canonical record, so the record and its Embedding are written atomically.

The vector index is a per-backend choice, not a global one. The Neo4j backend keeps its `memorable_embeddings_vector` index (ADR 0020) unchanged. Selecting Neo4j neither requires nor probes `sqlite-vec`; selecting SQLite does.

### Fail-loud capability probe, scoped to the SQLite backend

When the SQLite backend is constructed, the adapter probes whether `sqlite-vec` can load on the active interpreter. If it cannot, construction fails loudly with an actionable message (use a uv-managed / Homebrew / conda-forge / Windows ≥3.11 interpreter, or select the Neo4j backend), consistent with ADR 0020's fail-loud posture. The probe runs only for the SQLite backend; the Neo4j path is unaffected and continues to work as before.

### No silent fallback in V1

Memorable does not ship a silent numpy / brute-force runtime fallback that activates when `sqlite-vec` fails to load. A user on a known-bad interpreter gets an honest error, not slower search they cannot see. A numpy/BLOB brute-force adapter remains a documented, ready alternative behind the same port — it backs the in-memory test index today and is available as a drop-in — but it is not shipped as a second production path whose ranking and filtering semantics must be kept aligned with `sqlite-vec`.

### sqlite-vec is replaceable, not load-bearing

Because Embeddings are derived and `recreate_index` rebuilds them from canonical records, the pre-v1 status of `sqlite-vec` is bounded. If its on-disk format breaks across versions or the project stalls, the repair is a reindex into whatever adapter replaces it. No canonical memory is at risk.

## Consequences

Positive:

- The default (SQLite) backend gets a persistent vector index in the same file and transaction as canonical memory — atomic record+Embedding writes, satisfying the ADR 0020 contract.
- Verified install on the mandated uv toolchain and the common maintained interpreters; covers Python 3.14 with no compile step.
- The vector decision is isolated from the storage decision and can be superseded on its own; a future swap is a reindex, not a data migration.
- Fail-loud behavior keeps a missing extension from silently degrading retrieval.

Negative:

- A pre-v1 (0.1.9), small-maintainer dependency now sits in the default install's retrieval path. Its on-disk format is not frozen; an upgrade may require a reindex.
- python.org-macOS / macOS-system / default-pyenv interpreters cannot load it; those users must switch interpreter or select the Neo4j backend. The default install promise is dented for that minority, mitigated by an actionable error and by blessing `uvx` / `uv tool install` as the install path in docs.
- `sqlite-vec` KNN is brute-force (no ANN); fine at the ~10k ceiling, it will need replacement if per-space size grows by one or two orders of magnitude.
- Keeping the numpy/BLOB alternative documented but unused risks bit-rot unless the conformance suite exercises it via the in-memory index.

## Alternatives Considered

### Defer sqlite-vec — ship BLOB column + numpy brute-force as the SQLite vector index

A persistent vector stored as a BLOB column with numpy-vectorized cosine clears the ~10k ceiling, adds no loadable-extension dependency, works on every interpreter, and is trivially atomic (the vector is a column on the same row). Rejected as the V1 default — but only narrowly — because the install risk that motivated it was empirically refuted on the mandated toolchain, and `sqlite-vec` gives a real vector index, SQL-level metadata filtering, and an ANN upgrade path without re-engineering. It remains the documented fallback and the test-time index, and is the first candidate if the `sqlite-vec` dependency calculus changes.

### sqlite-vec primary with a silent numpy fallback

Rejected: two production vector paths whose ranking and filtering semantics must stay identical is more code and a standing correctness surface, for the benefit of auto-rescuing a narrow known-bad interpreter set that an actionable error already handles. An honest failure is preferable to silent degradation.

### Bundle a custom SQLite (pysqlite3-binary / apsw) to guarantee extension loading everywhere

Rejected for V1: `pysqlite3-binary` ships Linux-x86_64 wheels only (no macOS / Windows / arm64), and `apsw`, while broadly available with a Python 3.14 matrix, is not a DB-API drop-in and would impose a mechanical port of the SQLite adapter. Neither is justified to rescue a minority interpreter set the probe already reports clearly.

### External / separate vector store (revisiting ADR 0020's rejection)

Still rejected: it reintroduces an out-of-process dependency, against the embedded-default goal of ADR 0025, and Memorable already owns Embedding generation (ADR 0013). Keeping the vector index inside the same embedded database preserves single-file portability and atomic record+Embedding writes.

## Reconsideration Trigger

Revisit if:

- per-MemorySpace size grows beyond brute-force KNN's comfortable range, requiring ANN (consider `sqlite-vec` ANN when stable, or a graph-native engine per ADR 0025's trigger);
- `sqlite-vec` stalls, breaks its on-disk format across versions, or its load failures on common interpreters become frequent — fall back to the documented numpy/BLOB adapter via reindex;
- the install-environment picture changes (e.g. python.org-macOS enables extension loading, or a portable cross-platform SQLite bundle with Python 3.14 coverage appears);
- multiple Embeddings per source item (chunking / multimodal) change the index shape.
