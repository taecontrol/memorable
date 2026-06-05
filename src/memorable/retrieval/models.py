"""Data models for the retrieval subsystem.

These are NOT canonical memory -- they are derived representations
used for search and ranking.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True)
class EmbeddingRecord:
    """A vector representation derived from Indexable Text.

    Embeddings are NOT canonical memory. They are derived from
    Indexable Text for semantic retrieval purposes only.
    """

    source_id: str
    source_kind: str  # "Entity", "Decision", "Task", "Observation", "Relation"
    space: str
    indexable_text: str
    vector: list[float]
    provider_name: str
    model_name: str
    dimensions: int
    indexable_text_hash: str = ""
    indexable_text_version: str = "1"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class ReindexResult:
    """Result of rebuilding derived Embeddings for a MemorySpace."""

    space: str
    indexed_by_kind: dict[str, int]

    @property
    def indexed_total(self) -> int:
        return sum(self.indexed_by_kind.values())


@dataclass(frozen=True)
class SearchCandidate:
    """An intermediate result from cosine similarity search."""

    source_id: str
    source_kind: str
    score: float


@dataclass(frozen=True)
class RetrievalResult:
    """A ranked retrieval result with provenance-aware explanation.

    Each result explains why it was returned, including lifecycle state
    and provenance summary.
    """

    source_id: str
    source_kind: str
    lifecycle_state: str
    score: float
    explanation: list[str]
    provenance_summary: dict[str, str]
