"""Neo4j-backed persistent Embedding index adapter."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from memorable.retrieval.models import EmbeddingRecord, SearchCandidate
from memorable.storage.neo4j.schema import (
    EXPECTED_VECTOR_INDEX,
    create_vector_index_cypher,
    drop_vector_index_cypher,
)


@runtime_checkable
class Neo4jDriver(Protocol):
    """Minimal driver interface expected by the Neo4j retrieval index."""

    def session(self) -> Any: ...


def _to_iso(dt: datetime) -> str:
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("stored datetimes must be timezone-aware")
    return dt.astimezone(UTC).isoformat(timespec="microseconds")


def _from_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


class Neo4jRetrievalIndex:
    """Persistent Embedding index backed by Neo4j vector search."""

    def __init__(self, driver: Neo4jDriver) -> None:
        self._driver = driver

    def recreate_index(self, dimensions: int) -> None:
        """Drop and recreate the vector index at the given dimensions.

        This is the storage-side of ``reindex`` drift repair: it resolves
        embedding dimension drift in one step. Schema bootstrap stays
        create-if-absent and never drops the index; only ``reindex`` does.
        """
        with self._driver.session() as session:
            session.run(drop_vector_index_cypher())
            session.run(create_vector_index_cypher(dimensions))

    def store(self, record: EmbeddingRecord) -> None:
        """Add or replace a derived Embedding for a source item."""
        with self._driver.session() as session:
            session.run(
                "MERGE (embedding:Embedding {"
                "  space: $space, "
                "  source_id: $source_id, "
                "  source_kind: $source_kind, "
                "  provider_name: $provider_name, "
                "  model_name: $model_name, "
                "  dimensions: $dimensions"
                "}) "
                "ON CREATE SET embedding.created_at = $created_at "
                "SET embedding.indexable_text = $indexable_text, "
                "    embedding.indexable_text_hash = $indexable_text_hash, "
                "    embedding.indexable_text_version = $indexable_text_version, "
                "    embedding.vector = $vector, "
                "    embedding.updated_at = $updated_at",
                space=record.space,
                source_id=record.source_id,
                source_kind=record.source_kind,
                provider_name=record.provider_name,
                model_name=record.model_name,
                dimensions=record.dimensions,
                indexable_text=record.indexable_text,
                indexable_text_hash=record.indexable_text_hash,
                indexable_text_version=record.indexable_text_version,
                vector=record.vector,
                created_at=_to_iso(record.created_at),
                updated_at=_to_iso(record.updated_at),
            )

    def clear_space(self, space: str) -> None:
        """Remove all derived Embeddings for a MemorySpace."""
        with self._driver.session() as session:
            session.run(
                "MATCH (embedding:Embedding {space: $space}) DELETE embedding",
                space=space,
            )

    def delete(self, *, space: str, source_id: str, source_kind: str) -> None:
        """Remove derived Embeddings for one source item."""
        with self._driver.session() as session:
            session.run(
                "MATCH (embedding:Embedding {"
                "  space: $space, source_id: $source_id, source_kind: $source_kind"
                "}) DELETE embedding",
                space=space,
                source_id=source_id,
                source_kind=source_kind,
            )

    def records(self, *, space: str | None = None) -> list[EmbeddingRecord]:
        """Return stored Embeddings, optionally scoped to one MemorySpace."""
        with self._driver.session() as session:
            result = session.run(
                "MATCH (embedding:Embedding) "
                "WHERE ($space IS NULL OR embedding.space = $space) "
                "RETURN embedding.source_id AS source_id, "
                "       embedding.source_kind AS source_kind, "
                "       embedding.space AS space, "
                "       embedding.indexable_text AS indexable_text, "
                "       embedding.vector AS vector, "
                "       embedding.provider_name AS provider_name, "
                "       embedding.model_name AS model_name, "
                "       embedding.dimensions AS dimensions, "
                "       embedding.indexable_text_hash AS indexable_text_hash, "
                "       embedding.indexable_text_version AS indexable_text_version, "
                "       embedding.created_at AS created_at, "
                "       embedding.updated_at AS updated_at "
                "ORDER BY embedding.source_kind ASC, embedding.source_id ASC",
                space=space,
            )
            return [
                EmbeddingRecord(
                    source_id=record["source_id"],
                    source_kind=record["source_kind"],
                    space=record["space"],
                    indexable_text=record["indexable_text"],
                    vector=list(record["vector"]),
                    provider_name=record["provider_name"],
                    model_name=record["model_name"],
                    dimensions=record["dimensions"],
                    indexable_text_hash=record["indexable_text_hash"],
                    indexable_text_version=record["indexable_text_version"],
                    created_at=_from_iso(record["created_at"]),
                    updated_at=_from_iso(record["updated_at"]),
                )
                for record in result
            ]

    def search(
        self,
        space: str,
        query_vector: list[float],
        top_k: int = 10,
        *,
        provider_name: str | None = None,
        model_name: str | None = None,
        dimensions: int | None = None,
    ) -> list[SearchCandidate]:
        """Search compatible Embeddings with Neo4j vector search."""
        effective_dimensions = (
            dimensions if dimensions is not None else len(query_vector)
        )
        with self._driver.session() as session:
            coverage = session.run(
                "MATCH (embedding:Embedding {space: $space}) "
                "WHERE ($provider_name IS NULL "
                "       OR embedding.provider_name = $provider_name) "
                "  AND ($model_name IS NULL "
                "       OR embedding.model_name = $model_name) "
                "  AND embedding.dimensions = $dimensions "
                "RETURN count(embedding) AS count",
                space=space,
                provider_name=provider_name,
                model_name=model_name,
                dimensions=effective_dimensions,
            )
            coverage_record = coverage.single()
            if coverage_record is None or coverage_record["count"] == 0:
                return []

            pool = session.run(
                "MATCH (embedding:Embedding) "
                "WHERE embedding.vector IS NOT NULL "
                "  AND embedding.dimensions = $dimensions "
                "RETURN count(embedding) AS count",
                dimensions=effective_dimensions,
            )
            pool_record = pool.single()
            candidate_limit = 0 if pool_record is None else pool_record["count"]
            if candidate_limit == 0:
                return []

            result = session.run(
                "CALL db.index.vector.queryNodes($index_name, $candidate_limit, "
                "$query_vector) YIELD node, score "
                "WHERE node.space = $space "
                "  AND ($provider_name IS NULL "
                "       OR node.provider_name = $provider_name) "
                "  AND ($model_name IS NULL OR node.model_name = $model_name) "
                "  AND node.dimensions = $dimensions "
                "RETURN node.source_id AS source_id, "
                "       node.source_kind AS source_kind, "
                "       score AS score "
                "ORDER BY score DESC "
                "LIMIT $top_k",
                index_name=EXPECTED_VECTOR_INDEX.name,
                candidate_limit=candidate_limit,
                query_vector=query_vector,
                space=space,
                provider_name=provider_name,
                model_name=model_name,
                dimensions=effective_dimensions,
                top_k=top_k,
            )
            return [
                SearchCandidate(
                    source_id=record["source_id"],
                    source_kind=record["source_kind"],
                    score=record["score"],
                )
                for record in result
            ]
