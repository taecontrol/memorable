"""Hybrid GraphRAG retrieval service.

Combines semantic similarity, graph expansion, temporal filtering,
and provenance-aware explanation into ranked retrieval results.
"""

from __future__ import annotations

from datetime import datetime

from memorable.core.models import Decision, Entity, Task
from memorable.core.repositories import (
    InMemoryDecisionRepository,
    InMemoryEntityRepository,
    InMemoryTaskRepository,
)
from memorable.retrieval.embeddings import EmbeddingProvider
from memorable.retrieval.index import InMemoryEmbeddingIndex
from memorable.retrieval.indexable_text import (
    indexable_text_for_decision,
    indexable_text_for_entity,
    indexable_text_for_task,
)
from memorable.retrieval.models import EmbeddingRecord, RetrievalResult


class HybridRetrievalService:
    """Combines semantic search, graph expansion, temporal filtering,
    and provenance-aware explanation.

    Embeddings are derived from Indexable Text and are NOT canonical memory.
    Semantic ranking does NOT decide lifecycle truth -- Current Truth and
    Point-In-Time Truth come from temporal semantics.
    """

    def __init__(
        self,
        entity_repo: InMemoryEntityRepository,
        decision_repo: InMemoryDecisionRepository,
        task_repo: InMemoryTaskRepository,
        embedding_provider: EmbeddingProvider,
        dimensions: int = 32,
    ) -> None:
        self._entity_repo = entity_repo
        self._decision_repo = decision_repo
        self._task_repo = task_repo
        self._provider = embedding_provider
        self._dimensions = dimensions
        self._index = InMemoryEmbeddingIndex()

    def _rebuild_index(self, space: str) -> None:
        """Rebuild the embedding index from all records in the space.

        This is simple but correct for the tracer bullet. A production
        system would maintain the index incrementally.
        """
        self._index = InMemoryEmbeddingIndex()

        # Index all entities
        for (s, _), entity in self._entity_repo._entities.items():
            if s != space:
                continue
            text = indexable_text_for_entity(entity)
            vector = self._provider.embed(text)
            self._index.store(
                EmbeddingRecord(
                    source_id=entity.id,
                    source_kind="Entity",
                    space=space,
                    indexable_text=text,
                    vector=vector,
                    provider_name=self._provider.provider_name,
                    model_name=self._provider.model_name,
                    dimensions=self._dimensions,
                )
            )

        # Index all decisions (including superseded, for point-in-time)
        for (s, _), decision in self._decision_repo._decisions.items():
            if s != space:
                continue
            text = indexable_text_for_decision(decision)
            vector = self._provider.embed(text)
            self._index.store(
                EmbeddingRecord(
                    source_id=decision.id,
                    source_kind="Decision",
                    space=space,
                    indexable_text=text,
                    vector=vector,
                    provider_name=self._provider.provider_name,
                    model_name=self._provider.model_name,
                    dimensions=self._dimensions,
                )
            )

        # Index all tasks
        for (s, _), task in self._task_repo._tasks.items():
            if s != space:
                continue
            text = indexable_text_for_task(task)
            vector = self._provider.embed(text)
            self._index.store(
                EmbeddingRecord(
                    source_id=task.id,
                    source_kind="Task",
                    space=space,
                    indexable_text=text,
                    vector=vector,
                    provider_name=self._provider.provider_name,
                    model_name=self._provider.model_name,
                    dimensions=self._dimensions,
                )
            )

    def search(
        self,
        space: str,
        query: str,
        mode: str = "current",
        as_of: datetime | None = None,
        top_k: int = 10,
    ) -> list[RetrievalResult]:
        """Perform hybrid GraphRAG retrieval.

        Steps:
        1. Rebuild index from current repository state
        2. Embed query and find semantic candidates
        3. Graph expansion: find related records for each candidate
        4. Temporal filtering based on mode
        5. Rank by cosine similarity
        6. Build provenance-aware explanations

        Args:
            space: MemorySpace to search
            query: Natural language query
            mode: "current" for Current Truth, "as-of" for Point-In-Time Truth
            as_of: Required when mode is "as-of"
            top_k: Maximum number of results to return
        """
        # Step 1: Rebuild index
        self._rebuild_index(space)

        # Step 2: Semantic candidates
        query_vector = self._provider.embed(query)
        candidates = self._index.search(
            space=space, query_vector=query_vector, top_k=top_k * 2
        )

        # Step 3: Graph expansion -- collect related IDs
        expanded_ids: dict[str, float] = {}
        semantic_ids: set[str] = set()

        for candidate in candidates:
            semantic_ids.add(candidate.source_id)
            expanded_ids[candidate.source_id] = max(
                expanded_ids.get(candidate.source_id, 0.0),
                candidate.score,
            )

        graph_expanded_ids: set[str] = set()
        for candidate in candidates:
            related = self._graph_expand(space, candidate.source_id, candidate.source_kind)
            for related_id, related_kind in related:
                if related_id not in expanded_ids:
                    # Use a reduced score for graph-expanded items
                    expanded_ids[related_id] = candidate.score * 0.8
                    graph_expanded_ids.add(related_id)

        # Step 4: Temporal filtering and result building
        results: list[RetrievalResult] = []
        seen_ids: set[str] = set()

        for source_id, score in sorted(
            expanded_ids.items(), key=lambda x: x[1], reverse=True
        ):
            if source_id in seen_ids:
                continue
            seen_ids.add(source_id)

            result = self._build_result(
                space=space,
                source_id=source_id,
                score=score,
                mode=mode,
                as_of=as_of,
                is_semantic=source_id in semantic_ids,
                is_graph_expanded=source_id in graph_expanded_ids,
            )
            if result is not None:
                results.append(result)

        # Step 5: Final ranking by score
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]

    def _graph_expand(
        self, space: str, source_id: str, source_kind: str
    ) -> list[tuple[str, str]]:
        """Find related records via graph traversal.

        For the tracer bullet, this uses a simple heuristic:
        entities relate to all decisions and tasks in the same space,
        and decisions/tasks relate to all entities.
        """
        related: list[tuple[str, str]] = []

        if source_kind == "Entity":
            # Entity connects to decisions and tasks in the same space
            for (s, _), decision in self._decision_repo._decisions.items():
                if s == space:
                    related.append((decision.id, "Decision"))
            for (s, _), task in self._task_repo._tasks.items():
                if s == space:
                    related.append((task.id, "Task"))

        elif source_kind == "Decision":
            # Decision connects to entities in the same space
            for (s, _), entity in self._entity_repo._entities.items():
                if s == space:
                    related.append((entity.id, "Entity"))
            # Also connect to supersession chain
            decision = self._decision_repo.get(space, source_id)
            if decision and decision.supersedes:
                related.append((decision.supersedes, "Decision"))
            if decision and decision.superseded_by:
                related.append((decision.superseded_by, "Decision"))

        elif source_kind == "Task":
            # Task connects to entities in the same space
            for (s, _), entity in self._entity_repo._entities.items():
                if s == space:
                    related.append((entity.id, "Entity"))

        return related

    def _build_result(
        self,
        space: str,
        source_id: str,
        score: float,
        mode: str,
        as_of: datetime | None,
        is_semantic: bool,
        is_graph_expanded: bool,
    ) -> RetrievalResult | None:
        """Build a RetrievalResult with temporal filtering and explanation.

        Returns None if the record should be excluded by temporal filtering.
        """
        explanation: list[str] = []

        # Try to find the record
        entity = self._entity_repo.get(space, source_id)
        decision = self._decision_repo.get(space, source_id)
        task = self._task_repo.get(space=space, task_id=source_id)

        if entity is not None:
            return self._build_entity_result(
                space, entity, score, is_semantic, is_graph_expanded
            )
        elif decision is not None:
            return self._build_decision_result(
                space, decision, score, mode, as_of,
                is_semantic, is_graph_expanded,
            )
        elif task is not None:
            return self._build_task_result(
                space, task, score, mode, as_of,
                is_semantic, is_graph_expanded,
            )

        return None

    def _build_entity_result(
        self,
        space: str,
        entity: Entity,
        score: float,
        is_semantic: bool,
        is_graph_expanded: bool,
    ) -> RetrievalResult:
        explanation: list[str] = []
        if is_semantic:
            explanation.append(
                f"semantic candidate from Indexable Text for {entity.name}"
            )
        if is_graph_expanded:
            explanation.append(
                "graph expansion connected it to related records"
            )

        provenance = self._entity_repo.get_provenance(space, entity.id)
        prov_summary: dict[str, str] = {}
        if provenance:
            prov_summary = {
                "source_id": provenance.source_id,
                "episode_id": provenance.episode_id,
            }
            explanation.append(
                f"provenance is available from {provenance.source_id} / {provenance.episode_id}"
            )

        return RetrievalResult(
            source_id=entity.id,
            source_kind="Entity",
            lifecycle_state="current",
            score=score,
            explanation=explanation,
            provenance_summary=prov_summary,
        )

    def _build_decision_result(
        self,
        space: str,
        decision: Decision,
        score: float,
        mode: str,
        as_of: datetime | None,
        is_semantic: bool,
        is_graph_expanded: bool,
    ) -> RetrievalResult | None:
        explanation: list[str] = []

        if mode == "current":
            # Exclude superseded decisions in current mode
            if decision.lifecycle_state == "superseded":
                return None
            lifecycle_state = decision.lifecycle_state
        elif mode == "as-of" and as_of is not None:
            # Use point-in-time truth
            pit_decision = self._decision_repo.get_at(space, decision.id, as_of)
            if pit_decision is None:
                return None
            # If the point-in-time result is different from what we found,
            # it means we should use the PIT version
            if pit_decision.id != decision.id:
                return None
            lifecycle_state = pit_decision.lifecycle_state
            # Check if this decision was valid at the given time
            if pit_decision.validity_time > as_of:
                return None
        else:
            lifecycle_state = decision.lifecycle_state

        if is_semantic:
            explanation.append(
                f"semantic candidate from Indexable Text for {decision.statement[:60]}"
            )
        if is_graph_expanded:
            explanation.append(
                "graph expansion connected it to related records and supersession history"
            )

        # Temporal filter explanation
        if mode == "current":
            explanation.append(
                "temporal filter kept it because it is current at query time"
            )
        elif mode == "as-of" and as_of is not None:
            explanation.append(
                f"temporal filter kept it because it was valid at {as_of.isoformat()}"
            )

        # Supersession history context
        history = self._decision_repo.get_history(space, decision.id)
        if len(history) > 1 or decision.supersedes:
            supersession_parts = []
            if decision.supersedes:
                old = self._decision_repo.get(space, decision.supersedes)
                if old:
                    supersession_parts.append(
                        f"{old.id} was superseded at "
                        f"{old.invalidation_time.isoformat() if old.invalidation_time else 'unknown'}"
                    )
            if supersession_parts:
                explanation.append(
                    "supersession history: " + "; ".join(supersession_parts)
                )

        provenance = self._decision_repo.get_provenance(space, decision.id)
        prov_summary: dict[str, str] = {}
        if provenance:
            prov_summary = {
                "source_id": provenance.source_id,
                "episode_id": provenance.episode_id,
            }
            explanation.append(
                f"provenance is available from {provenance.source_id} / {provenance.episode_id}"
            )

        return RetrievalResult(
            source_id=decision.id,
            source_kind="Decision",
            lifecycle_state=lifecycle_state,
            score=score,
            explanation=explanation,
            provenance_summary=prov_summary,
        )

    def _build_task_result(
        self,
        space: str,
        task: Task,
        score: float,
        mode: str,
        as_of: datetime | None,
        is_semantic: bool,
        is_graph_expanded: bool,
    ) -> RetrievalResult | None:
        explanation: list[str] = []

        if mode == "as-of" and as_of is not None:
            pit_task = self._task_repo.get_at(
                space=space, task_id=task.id, at=as_of
            )
            if pit_task is None:
                return None
            lifecycle_state = pit_task.lifecycle_state
        else:
            lifecycle_state = task.lifecycle_state

        if is_semantic:
            explanation.append(
                f"semantic candidate from Indexable Text for {task.title[:60]}"
            )
        if is_graph_expanded:
            explanation.append(
                "graph expansion connected it to related records"
            )

        if mode == "current":
            explanation.append(
                f"temporal filter kept it with lifecycle state: {lifecycle_state}"
            )
        elif mode == "as-of" and as_of is not None:
            explanation.append(
                f"temporal filter shows lifecycle state at {as_of.isoformat()}: {lifecycle_state}"
            )

        provenance = self._task_repo.get_provenance(
            space=space, task_id=task.id
        )
        prov_summary: dict[str, str] = {}
        if provenance:
            prov_summary = {
                "source_id": provenance.source_id,
                "episode_id": provenance.episode_id,
            }
            explanation.append(
                f"provenance is available from {provenance.source_id} / {provenance.episode_id}"
            )

        return RetrievalResult(
            source_id=task.id,
            source_kind="Task",
            lifecycle_state=lifecycle_state,
            score=score,
            explanation=explanation,
            provenance_summary=prov_summary,
        )
