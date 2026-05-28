"""Hybrid GraphRAG retrieval service.

Combines semantic similarity, graph expansion, temporal filtering,
and provenance-aware explanation into ranked retrieval results.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Literal

from memorable.core.application import InspectTaskService, PointInTimeTruthService
from memorable.core.models import Decision, Entity, Observation, Relation, Task
from memorable.core.ports import (
    DecisionRepository,
    EntityRepository,
    ObservationRepository,
    RelationRepository,
    TaskRepository,
)
from memorable.retrieval.embeddings import EmbeddingProvider
from memorable.retrieval.index import InMemoryEmbeddingIndex
from memorable.retrieval.indexable_text import (
    indexable_text_for_decision,
    indexable_text_for_entity,
    indexable_text_for_observation,
    indexable_text_for_relation,
    indexable_text_for_task,
)
from memorable.retrieval.models import EmbeddingRecord, RetrievalResult

if TYPE_CHECKING:
    from memorable.core.context import ApplicationContext


class HybridRetrievalService:
    """Combines semantic search, graph expansion, temporal filtering,
    and provenance-aware explanation.

    Embeddings are derived from Indexable Text and are NOT canonical memory.
    Semantic ranking does NOT decide lifecycle truth -- Current Truth and
    Point-In-Time Truth come from temporal semantics.
    """

    def __init__(
        self,
        entity_repo: EntityRepository,
        decision_repo: DecisionRepository,
        task_repo: TaskRepository,
        observation_repo: ObservationRepository,
        embedding_provider: EmbeddingProvider,
        dimensions: int = 32,
        point_in_time_service: PointInTimeTruthService | None = None,
        inspect_task_service: InspectTaskService | None = None,
        relation_repo: RelationRepository | None = None,
    ) -> None:
        self._entity_repo = entity_repo
        self._decision_repo = decision_repo
        self._task_repo = task_repo
        self._observation_repo = observation_repo
        self._relation_repo = relation_repo
        self._embedding_provider = embedding_provider
        self._dimensions = dimensions
        self._index = InMemoryEmbeddingIndex()
        self._point_in_time_service = (
            point_in_time_service
            if point_in_time_service is not None
            else PointInTimeTruthService(repository=decision_repo)
        )
        self._inspect_task_service = (
            inspect_task_service
            if inspect_task_service is not None
            else InspectTaskService(repository=task_repo)
        )
        self._observation_pit_service = PointInTimeTruthService(
            repository=observation_repo
        )
        self._relation_pit_service: PointInTimeTruthService | None = (
            PointInTimeTruthService(repository=relation_repo)
            if relation_repo is not None
            else None
        )

    def _rebuild_index(self, space: str) -> None:
        """Rebuild the embedding index from all records in the space.

        This is simple but correct for the tracer bullet. A production
        system would maintain the index incrementally.
        """
        self._index = InMemoryEmbeddingIndex()

        for entity in self._entity_repo.list_by_space(space):
            text = indexable_text_for_entity(entity)
            vector = self._embedding_provider.embed(text)
            self._index.store(
                EmbeddingRecord(
                    source_id=entity.id,
                    source_kind="Entity",
                    space=space,
                    indexable_text=text,
                    vector=vector,
                    provider_name=self._embedding_provider.provider_name,
                    model_name=self._embedding_provider.model_name,
                    dimensions=self._dimensions,
                )
            )

        for decision in self._decision_repo.list_by_space(space):
            text = indexable_text_for_decision(decision)
            vector = self._embedding_provider.embed(text)
            self._index.store(
                EmbeddingRecord(
                    source_id=decision.id,
                    source_kind="Decision",
                    space=space,
                    indexable_text=text,
                    vector=vector,
                    provider_name=self._embedding_provider.provider_name,
                    model_name=self._embedding_provider.model_name,
                    dimensions=self._dimensions,
                )
            )

        for task in self._task_repo.list_by_space(space):
            text = indexable_text_for_task(task)
            vector = self._embedding_provider.embed(text)
            self._index.store(
                EmbeddingRecord(
                    source_id=task.id,
                    source_kind="Task",
                    space=space,
                    indexable_text=text,
                    vector=vector,
                    provider_name=self._embedding_provider.provider_name,
                    model_name=self._embedding_provider.model_name,
                    dimensions=self._dimensions,
                )
            )

        for observation in self._observation_repo.list_by_space(space):
            text = indexable_text_for_observation(observation)
            vector = self._embedding_provider.embed(text)
            self._index.store(
                EmbeddingRecord(
                    source_id=observation.id,
                    source_kind="Observation",
                    space=space,
                    indexable_text=text,
                    vector=vector,
                    provider_name=self._embedding_provider.provider_name,
                    model_name=self._embedding_provider.model_name,
                    dimensions=self._dimensions,
                )
            )

        if self._relation_repo is not None:
            for relation in self._relation_repo.list_by_space(space):
                text = indexable_text_for_relation(relation)
                vector = self._embedding_provider.embed(text)
                self._index.store(
                    EmbeddingRecord(
                        source_id=relation.id,
                        source_kind="Relation",
                        space=space,
                        indexable_text=text,
                        vector=vector,
                        provider_name=self._embedding_provider.provider_name,
                        model_name=self._embedding_provider.model_name,
                        dimensions=self._dimensions,
                    )
                )

    def search(
        self,
        space: str,
        query: str,
        mode: Literal["current", "as-of"] = "current",
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
            mode: "current" for Current Truth,
                  "as-of" for Point-In-Time Truth
            as_of: Required when mode is "as-of"
            top_k: Maximum number of results to return
        """
        # Step 1: Rebuild index
        self._rebuild_index(space)

        # Step 2: Semantic candidates
        query_vector = self._embedding_provider.embed(query)
        candidates = self._index.search(
            space=space, query_vector=query_vector, top_k=top_k * 2
        )

        # Step 3: Graph expansion -- collect related IDs
        # Maps source_id → (score, source_kind) so _build_result can
        # dispatch directly without probing all repositories.
        expanded_ids: dict[str, tuple[float, str]] = {}
        semantic_ids: set[str] = set()

        for candidate in candidates:
            semantic_ids.add(candidate.source_id)
            prev_score, _ = expanded_ids.get(
                candidate.source_id, (0.0, candidate.source_kind)
            )
            expanded_ids[candidate.source_id] = (
                max(prev_score, candidate.score),
                candidate.source_kind,
            )

        graph_expanded_ids: set[str] = set()
        for candidate in candidates:
            related = self._graph_expand(
                space, candidate.source_id, candidate.source_kind
            )
            for related_id, related_kind in related:
                if related_id not in expanded_ids:
                    expanded_ids[related_id] = (
                        candidate.score * 0.8,
                        related_kind,
                    )
                    graph_expanded_ids.add(related_id)

        # Step 4: Temporal filtering and result building
        results: list[RetrievalResult] = []
        seen_ids: set[str] = set()

        for source_id, (score, source_kind) in sorted(
            expanded_ids.items(), key=lambda x: x[1][0], reverse=True
        ):
            if source_id in seen_ids:
                continue
            seen_ids.add(source_id)

            result = self._build_result(
                space=space,
                source_id=source_id,
                source_kind=source_kind,
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

        Entity expansion uses Relation-based 1-hop traversal (via
        ``list_by_entity``), skipping superseded/invalidated relations.
        Decision, Task, and Observation expansion still uses a heuristic:
        each relates to all entities in the same space, plus supersession
        chain neighbours where applicable.
        """
        related: list[tuple[str, str]] = []

        if source_kind == "Entity":
            if self._relation_repo is not None:
                relations = self._relation_repo.list_by_entity(space, source_id)
                for relation in relations:
                    if relation.lifecycle_state in (
                        "superseded",
                        "invalidated",
                    ):
                        continue
                    # Extract the other endpoint Entity
                    other_entity_id = (
                        relation.target_entity_id
                        if relation.source_entity_id == source_id
                        else relation.source_entity_id
                    )
                    related.append((other_entity_id, "Entity"))

        elif source_kind == "Decision":
            for entity in self._entity_repo.list_by_space(space):
                related.append((entity.id, "Entity"))
            decision = self._decision_repo.get(space, source_id)
            if decision and decision.supersedes:
                related.append((decision.supersedes, "Decision"))
            if decision and decision.superseded_by:
                related.append((decision.superseded_by, "Decision"))

        elif source_kind == "Task":
            for entity in self._entity_repo.list_by_space(space):
                related.append((entity.id, "Entity"))

        elif source_kind == "Observation":
            for entity in self._entity_repo.list_by_space(space):
                related.append((entity.id, "Entity"))
            observation = self._observation_repo.get(space, source_id)
            if observation and observation.supersedes:
                related.append((observation.supersedes, "Observation"))
            if observation and observation.superseded_by:
                related.append((observation.superseded_by, "Observation"))

        return related

    def _build_result(
        self,
        space: str,
        source_id: str,
        source_kind: str,
        score: float,
        mode: Literal["current", "as-of"],
        as_of: datetime | None,
        is_semantic: bool,
        is_graph_expanded: bool,
    ) -> RetrievalResult | None:
        """Build a RetrievalResult with temporal filtering.

        Dispatches directly to the correct builder using ``source_kind``
        so that only 1 repository ``get()`` call is made per candidate.

        Returns None if the record should be excluded
        by temporal filtering or if the record no longer exists.
        """
        if source_kind == "Entity":
            entity = self._entity_repo.get(space, source_id)
            if entity is None:
                return None
            return self._build_entity_result(
                space,
                entity,
                score,
                is_semantic,
                is_graph_expanded,
            )
        elif source_kind == "Decision":
            decision = self._decision_repo.get(space, source_id)
            if decision is None:
                return None
            return self._build_decision_result(
                space,
                decision,
                score,
                mode,
                as_of,
                is_semantic,
                is_graph_expanded,
            )
        elif source_kind == "Task":
            task = self._task_repo.get(space=space, task_id=source_id)
            if task is None:
                return None
            return self._build_task_result(
                space,
                task,
                score,
                mode,
                as_of,
                is_semantic,
                is_graph_expanded,
            )
        elif source_kind == "Observation":
            observation = self._observation_repo.get(space, source_id)
            if observation is None:
                return None
            return self._build_observation_result(
                space,
                observation,
                score,
                mode,
                as_of,
                is_semantic,
                is_graph_expanded,
            )
        elif source_kind == "Relation" and self._relation_repo is not None:
            relation = self._relation_repo.get(space, source_id)
            if relation is None:
                return None
            return self._build_relation_result(
                space,
                relation,
                score,
                mode,
                as_of,
                is_semantic,
                is_graph_expanded,
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
            explanation.append("graph expansion connected it to related records")

        provenance = self._entity_repo.get_provenance(space, entity.id)
        prov_summary: dict[str, str] = {}
        if provenance:
            prov_summary = {
                "source_id": provenance.source_id,
                "episode_id": provenance.episode_id,
            }
            explanation.append(
                "provenance is available from"
                f" {provenance.source_id}"
                f" / {provenance.episode_id}"
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
        mode: Literal["current", "as-of"],
        as_of: datetime | None,
        is_semantic: bool,
        is_graph_expanded: bool,
    ) -> RetrievalResult | None:
        explanation: list[str] = []

        if mode == "current":
            if decision.lifecycle_state in ("superseded", "invalidated"):
                return None
            lifecycle_state = decision.lifecycle_state
        elif mode == "as-of" and as_of is not None:
            pit_decision = self._point_in_time_service.at(
                space=space, record_id=decision.id, at=as_of
            )
            if pit_decision is None:
                return None
            if pit_decision.id != decision.id:
                return None
            lifecycle_state = pit_decision.lifecycle_state
            if pit_decision.validity_time > as_of:
                return None
        else:
            lifecycle_state = decision.lifecycle_state

        if is_semantic:
            stmt_preview = decision.statement[:60]
            explanation.append(
                f"semantic candidate from Indexable Text for {stmt_preview}"
            )
        if is_graph_expanded:
            explanation.append(
                "graph expansion connected it to related"
                " records and supersession history"
            )

        if mode == "current":
            explanation.append(
                "temporal filter kept it because it is current at query time"
            )
        elif mode == "as-of" and as_of is not None:
            explanation.append(
                f"temporal filter kept it because it was valid at {as_of.isoformat()}"
            )

        # Supersession history context (chain-walk via thin repo.get() calls)
        has_chain = (
            decision.superseded_by is not None or decision.supersedes is not None
        )
        if has_chain:
            supersession_parts = []
            if decision.supersedes:
                old = self._decision_repo.get(space, decision.supersedes)
                if old:
                    inv_time = (
                        old.invalidation_time.isoformat()
                        if old.invalidation_time
                        else "unknown"
                    )
                    supersession_parts.append(f"{old.id} was superseded at {inv_time}")
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
                "provenance is available from"
                f" {provenance.source_id}"
                f" / {provenance.episode_id}"
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
        mode: Literal["current", "as-of"],
        as_of: datetime | None,
        is_semantic: bool,
        is_graph_expanded: bool,
    ) -> RetrievalResult | None:
        explanation: list[str] = []

        if mode == "as-of" and as_of is not None:
            pit_task = self._inspect_task_service.inspect(
                space=space, task_id=task.id, as_of=as_of
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
            explanation.append("graph expansion connected it to related records")

        if mode == "current":
            explanation.append(
                f"temporal filter kept it with lifecycle state: {lifecycle_state}"
            )
        elif mode == "as-of" and as_of is not None:
            explanation.append(
                "temporal filter shows lifecycle state"
                f" at {as_of.isoformat()}:"
                f" {lifecycle_state}"
            )

        provenance = self._task_repo.get_provenance(space=space, task_id=task.id)
        prov_summary: dict[str, str] = {}
        if provenance:
            prov_summary = {
                "source_id": provenance.source_id,
                "episode_id": provenance.episode_id,
            }
            explanation.append(
                "provenance is available from"
                f" {provenance.source_id}"
                f" / {provenance.episode_id}"
            )

        return RetrievalResult(
            source_id=task.id,
            source_kind="Task",
            lifecycle_state=lifecycle_state,
            score=score,
            explanation=explanation,
            provenance_summary=prov_summary,
        )

    def _build_observation_result(
        self,
        space: str,
        observation: Observation,
        score: float,
        mode: Literal["current", "as-of"],
        as_of: datetime | None,
        is_semantic: bool,
        is_graph_expanded: bool,
    ) -> RetrievalResult | None:
        explanation: list[str] = []

        if mode == "current":
            if observation.lifecycle_state in ("superseded", "invalidated"):
                return None
            lifecycle_state = observation.lifecycle_state
        elif mode == "as-of" and as_of is not None:
            pit_observation = self._observation_pit_service.at(
                space=space, record_id=observation.id, at=as_of
            )
            if pit_observation is None:
                return None
            if pit_observation.id != observation.id:
                return None
            lifecycle_state = pit_observation.lifecycle_state
            if pit_observation.validity_time > as_of:
                return None
        else:
            lifecycle_state = observation.lifecycle_state

        if is_semantic:
            stmt_preview = observation.statement[:60]
            explanation.append(
                f"semantic candidate from Indexable Text for {stmt_preview}"
            )
        if is_graph_expanded:
            explanation.append(
                "graph expansion connected it to related"
                " records and supersession history"
            )

        if mode == "current":
            explanation.append(
                "temporal filter kept it because it is current at query time"
            )
        elif mode == "as-of" and as_of is not None:
            explanation.append(
                f"temporal filter kept it because it was valid at {as_of.isoformat()}"
            )

        # Supersession history context
        has_chain = (
            observation.superseded_by is not None or observation.supersedes is not None
        )
        if has_chain:
            supersession_parts = []
            if observation.supersedes:
                old = self._observation_repo.get(space, observation.supersedes)
                if old:
                    inv_time = (
                        old.invalidation_time.isoformat()
                        if old.invalidation_time
                        else "unknown"
                    )
                    supersession_parts.append(f"{old.id} was superseded at {inv_time}")
            if supersession_parts:
                explanation.append(
                    "supersession history: " + "; ".join(supersession_parts)
                )

        provenance = self._observation_repo.get_provenance(space, observation.id)
        prov_summary: dict[str, str] = {}
        if provenance:
            prov_summary = {
                "source_id": provenance.source_id,
                "episode_id": provenance.episode_id,
            }
            explanation.append(
                "provenance is available from"
                f" {provenance.source_id}"
                f" / {provenance.episode_id}"
            )

        return RetrievalResult(
            source_id=observation.id,
            source_kind="Observation",
            lifecycle_state=lifecycle_state,
            score=score,
            explanation=explanation,
            provenance_summary=prov_summary,
        )

    def _build_relation_result(
        self,
        space: str,
        relation: Relation,
        score: float,
        mode: Literal["current", "as-of"],
        as_of: datetime | None,
        is_semantic: bool,
        is_graph_expanded: bool,
    ) -> RetrievalResult | None:
        explanation: list[str] = []

        if mode == "current":
            if relation.lifecycle_state in ("superseded", "invalidated"):
                return None
            lifecycle_state = relation.lifecycle_state
        elif (
            mode == "as-of"
            and as_of is not None
            and self._relation_pit_service is not None
        ):
            pit_relation = self._relation_pit_service.at(
                space=space, record_id=relation.id, at=as_of
            )
            if pit_relation is None:
                return None
            if pit_relation.id != relation.id:
                return None
            lifecycle_state = pit_relation.lifecycle_state
            if pit_relation.validity_time > as_of:
                return None
        else:
            lifecycle_state = relation.lifecycle_state

        if is_semantic:
            stmt_preview = relation.statement[:60]
            explanation.append(
                f"semantic candidate from Indexable Text for {stmt_preview}"
            )
        if is_graph_expanded:
            explanation.append("graph expansion connected it to related records")

        if mode == "current":
            explanation.append(
                "temporal filter kept it because it is current at query time"
            )
        elif mode == "as-of" and as_of is not None:
            explanation.append(
                f"temporal filter kept it because it was valid at {as_of.isoformat()}"
            )

        # Supersession history context
        has_chain = (
            relation.superseded_by is not None or relation.supersedes is not None
        )
        if has_chain and self._relation_repo is not None:
            supersession_parts = []
            if relation.supersedes:
                old = self._relation_repo.get(space, relation.supersedes)
                if old:
                    inv_time = (
                        old.invalidation_time.isoformat()
                        if old.invalidation_time
                        else "unknown"
                    )
                    supersession_parts.append(f"{old.id} was superseded at {inv_time}")
            if supersession_parts:
                explanation.append(
                    "supersession history: " + "; ".join(supersession_parts)
                )

        # _relation_repo is guaranteed non-None by the caller's guard
        provenance = self._relation_repo.get_provenance(space, relation.id)  # type: ignore[union-attr]
        prov_summary: dict[str, str] = {}
        if provenance:
            prov_summary = {
                "source_id": provenance.source_id,
                "episode_id": provenance.episode_id,
            }
            explanation.append(
                "provenance is available from"
                f" {provenance.source_id}"
                f" / {provenance.episode_id}"
            )

        return RetrievalResult(
            source_id=relation.id,
            source_kind="Relation",
            lifecycle_state=lifecycle_state,
            score=score,
            explanation=explanation,
            provenance_summary=prov_summary,
        )


def build_retrieval_service(
    context: ApplicationContext,
    embedding_provider: EmbeddingProvider,
) -> HybridRetrievalService:
    """Build a HybridRetrievalService wired to the given context's repos.

    Callers choose which EmbeddingProvider to inject — this keeps
    ApplicationContext free of embedding concerns.
    """
    return HybridRetrievalService(
        entity_repo=context.entity_repo,
        decision_repo=context.decision_repo,
        task_repo=context.task_repo,
        embedding_provider=embedding_provider,
        observation_repo=context.observation_repo,
        relation_repo=context.relation_repo,
    )
