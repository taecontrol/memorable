# ADR 0013: fastembed As Default Local Embedding Provider

Date: 2026-05-27
Status: Accepted
Refines: ADR 0007

## Context

ADR 0007 required hybrid GraphRAG retrieval in the tracer bullet and established two guardrails: local embedding providers are preferred by default, and remote providers require explicit configuration because memory content may leave the machine.

The tracer bullet was built with a `FakeEmbeddingProvider` that returns hash-based vectors. This unblocked retrieval development but means production search returns results ranked by hash similarity, not semantic similarity. Wiring a real provider is required for V1.

Three local embedding providers were evaluated:

- **fastembed** (by Qdrant): ONNX Runtime, ~50 MB install, no external server, CPU-only. Default model `BAAI/bge-small-en-v1.5` is 67 MB, 384 dimensions, 512-token context, MTEB Retrieval 51.68 nDCG@10. Apache-2.0 license, MIT model license.
- **sentence-transformers** (by UKPLab / Hugging Face): PyTorch backend, ~300 MB to 1 GB install depending on platform, GPU support. Runs the same models at identical quality but carries PyTorch as a transitive dependency, which causes version conflicts and pulls CUDA packages on Linux.
- **Ollama**: GPU-accelerated local server, OpenAI-compatible API, access to larger models (8192-token context, higher MTEB scores). Requires a running daemon and a manual model pull, neither declarable in `pyproject.toml`.

All three can run `BAAI/bge-small-en-v1.5` with identical output quality. The difference is operational: install weight, server dependencies, and platform behavior.

## Decision

Memorable uses **fastembed** as the default local embedding provider and ships it as a required dependency.

The provider matrix is:

| Provider | When to use | Server required | API key required |
|----------|-------------|-----------------|------------------|
| `fastembed` | Default. Local-first, works after `pip install memorable`. | No | No |
| `openrouter` | Explicit remote upgrade for higher quality or larger context. | No (remote API) | Yes |
| `fake` | Tests only. Deterministic hash-based vectors. | No | No |

Default `EmbeddingSettings`:

```yaml
embeddings:
  provider: fastembed
  model: BAAI/bge-small-en-v1.5
  dimensions: 384
```

Provider selection is explicit. If the configured provider cannot start (missing API key for `openrouter`, missing library for an unknown provider name), the system fails loudly with an actionable error. There is no silent fallback to fake embeddings.

Switching providers changes embedding dimensions and invalidates existing embeddings. Embeddings are derived retrieval indexes (ADR 0007) and can be regenerated. V1 does not detect dimension mismatches automatically; switching providers requires a manual re-index.

## Consequences

Positive:

- `pip install memorable` gives working semantic search with zero configuration. No API key, no external server, no manual model pull.
- Memory content stays on the machine by default, satisfying the local-first trust posture.
- The ~50 MB install cost is proportional to existing dependencies (neo4j driver, openai SDK, pyyaml).
- The 512-token context window is sufficient for Indexable Text derived from Entities, Decisions, Observations, Relations, and Tasks.
- Contributors who need a remote provider set `provider: openrouter` in `runtime.yaml` and an API key in `.env`, following ADR 0010's three-layer config.

Negative:

- fastembed is CPU-only. No GPU acceleration. Reported slower on Apple Silicon than sentence-transformers.
- First search triggers a one-time ~67 MB model download with no built-in progress indicator.
- Model loading adds ~1-2 seconds on first embed call per process. Acceptable for interactive CLI and MCP use, but visible.
- fastembed has a smaller model catalog (~30-50 curated models) than sentence-transformers (~15,000). Sufficient for retrieval but limiting if fine-tuned or domain-specific models are needed later.
- Required dependency adds ~50 MB to every install, even if the user intends to use only `openrouter`.

## Alternatives Considered

### Ollama As Default

Ollama offers GPU acceleration, larger models, and longer context windows. However, it requires a second external server alongside Neo4j, a separate binary install outside `pip`, and a manual model pull. This raises the setup barrier for new users and contradicts the goal of working search after `pip install memorable`. Ollama was rejected as both default and optional provider to keep the provider matrix simple.

### sentence-transformers As Default

sentence-transformers runs the same models at identical quality and adds GPU support. However, PyTorch adds 300 MB to 1 GB of install weight, causes version conflicts with other Python projects, and pulls CUDA packages on Linux unless a CPU-only index URL is used (which `pyproject.toml` cannot express). The quality advantage over fastembed is zero on the same model; the only benefit is GPU speed, which does not justify the dependency cost for single-text interactive embedding.

### fastembed As Optional Extra

Making fastembed an optional dependency (`pip install memorable[local]`) keeps the base install lighter. However, the default `EmbeddingSettings` assumes `provider: fastembed`. Combined with the no-silent-fallback rule, a base install would fail on first search with an error asking the user to install an extra they did not know about. This defeats local-first ergonomics.

## Reconsideration Trigger

Revisit this decision if:

- fastembed performance on Apple Silicon becomes a blocking user complaint.
- A retrieval use case requires context windows longer than 512 tokens.
- A lightweight local provider emerges that matches fastembed's install ergonomics with GPU support.
- The project adds a dependency on PyTorch for another reason, making sentence-transformers free.
