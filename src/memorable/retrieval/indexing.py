"""Write-time maintenance for derived Embeddings.

Embeddings are derived retrieval data, not canonical memory. This module owns
turning remembered items into Indexable Text, calling the active Embedding
Provider, and upserting through the RetrievalIndex port.
"""

from __future__ import annotations

import hashlib

from memorable.core.models import Decision, Entity, Observation, Relation, Task
from memorable.retrieval.embeddings import EmbeddingProvider
from memorable.retrieval.index import RetrievalIndex
from memorable.retrieval.indexable_text import (
    INDEXABLE_TEXT_VERSION,
    indexable_text_for_decision,
    indexable_text_for_entity,
    indexable_text_for_observation,
    indexable_text_for_relation,
    indexable_text_for_task,
)
from memorable.retrieval.models import EmbeddingRecord


class EmbeddingIndexer:
    """Coordinates Indexable Text -> Embedding -> RetrievalIndex upsert."""

    def __init__(
        self,
        *,
        retrieval_index: RetrievalIndex,
        embedding_provider: EmbeddingProvider,
        dimensions: int,
    ) -> None:
        self._retrieval_index = retrieval_index
        self._embedding_provider = embedding_provider
        self._dimensions = dimensions

    def upsert_entity(self, entity: Entity) -> None:
        """Upsert the derived Embedding for a remembered Entity."""
        self._store_embedding(
            space=entity.space,
            source_id=entity.id,
            source_kind="Entity",
            indexable_text=indexable_text_for_entity(entity),
        )

    def upsert_decision(self, decision: Decision) -> None:
        """Upsert the derived Embedding for a remembered Decision."""
        self._store_embedding(
            space=decision.space,
            source_id=decision.id,
            source_kind="Decision",
            indexable_text=indexable_text_for_decision(decision),
        )

    def upsert_task(self, task: Task) -> None:
        """Upsert the derived Embedding for a remembered Task."""
        self._store_embedding(
            space=task.space,
            source_id=task.id,
            source_kind="Task",
            indexable_text=indexable_text_for_task(task),
        )

    def upsert_observation(self, observation: Observation) -> None:
        """Upsert the derived Embedding for a remembered Observation."""
        self._store_embedding(
            space=observation.space,
            source_id=observation.id,
            source_kind="Observation",
            indexable_text=indexable_text_for_observation(observation),
        )

    def upsert_relation(self, relation: Relation) -> None:
        """Upsert the derived Embedding for a remembered Relation."""
        self._store_embedding(
            space=relation.space,
            source_id=relation.id,
            source_kind="Relation",
            indexable_text=indexable_text_for_relation(relation),
        )

    def _store_embedding(
        self,
        *,
        space: str,
        source_id: str,
        source_kind: str,
        indexable_text: str,
    ) -> None:
        vector = self._embedding_provider.embed(indexable_text)
        self._retrieval_index.store(
            EmbeddingRecord(
                source_id=source_id,
                source_kind=source_kind,
                space=space,
                indexable_text=indexable_text,
                vector=vector,
                provider_name=self._embedding_provider.provider_name,
                model_name=self._embedding_provider.model_name,
                dimensions=self._dimensions,
                indexable_text_hash=hashlib.sha256(
                    indexable_text.encode("utf-8")
                ).hexdigest(),
                indexable_text_version=INDEXABLE_TEXT_VERSION,
            )
        )
