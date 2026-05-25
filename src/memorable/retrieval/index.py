"""In-memory embedding index for semantic search.

Stores EmbeddingRecords and searches by cosine similarity,
scoped to a MemorySpace.
"""

from __future__ import annotations

import math

from memorable.retrieval.models import EmbeddingRecord, SearchCandidate


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


class InMemoryEmbeddingIndex:
    """In-memory vector store that supports cosine similarity search."""

    def __init__(self) -> None:
        self._records: list[EmbeddingRecord] = []

    def store(self, record: EmbeddingRecord) -> None:
        """Add an embedding record to the index."""
        self._records.append(record)

    def search(
        self,
        space: str,
        query_vector: list[float],
        top_k: int = 10,
    ) -> list[SearchCandidate]:
        """Find the top-k most similar records in the given space.

        Returns SearchCandidate list ordered by similarity descending.
        """
        scored = []
        for record in self._records:
            if record.space != space:
                continue
            score = _cosine_similarity(query_vector, record.vector)
            scored.append(
                SearchCandidate(
                    source_id=record.source_id,
                    source_kind=record.source_kind,
                    score=score,
                )
            )

        scored.sort(key=lambda c: c.score, reverse=True)
        return scored[:top_k]
