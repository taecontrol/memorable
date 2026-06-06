"""Hybrid GraphRAG retrieval service.

Combines semantic similarity, graph expansion, temporal filtering,
and provenance-aware explanation into ranked retrieval results.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import datetime
from typing import TYPE_CHECKING, Literal

from memorable.core.application import InspectTaskService, PointInTimeTruthService
from memorable.core.attributes import (
    AttributeValidationError,
    copy_attribute_values,
    validate_attribute_filter_values,
)
from memorable.core.models import Decision, Entity, Observation, Relation, Task
from memorable.core.ports import (
    AboutRepository,
    DecisionRepository,
    EntityRepository,
    ObservationRepository,
    RelationRepository,
    TaskRepository,
)
from memorable.retrieval.embeddings import EmbeddingProvider
from memorable.retrieval.index import InMemoryEmbeddingIndex, RetrievalIndex
from memorable.retrieval.indexable_text import (
    INDEXABLE_TEXT_VERSION,
    indexable_text_for_decision,
    indexable_text_for_entity,
    indexable_text_for_observation,
    indexable_text_for_relation,
    indexable_text_for_task,
)
from memorable.retrieval.indexing import EmbeddingIndexer
from memorable.retrieval.models import (
    EmbeddingCoverageReport,
    EmbeddingRecord,
    ReindexResult,
    RetrievalResult,
)

if TYPE_CHECKING:
    from memorable.core.context import ApplicationContext
    from memorable.core.profile import MemoryProfile


SOURCE_KINDS = ("Entity", "Decision", "Task", "Observation", "Relation")


class EmbeddingIndexCompatibilityError(RuntimeError):
    """Raised when active search settings cannot use the Embedding index."""


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
        about_repo: AboutRepository | None = None,
        retrieval_index: RetrievalIndex | None = None,
        profile: MemoryProfile | None = None,
    ) -> None:
        self._entity_repo = entity_repo
        self._decision_repo = decision_repo
        self._task_repo = task_repo
        self._observation_repo = observation_repo
        self._relation_repo = relation_repo
        self._about_repo = about_repo
        self._embedding_provider = embedding_provider
        self._dimensions = dimensions
        self._index = (
            retrieval_index if retrieval_index is not None else InMemoryEmbeddingIndex()
        )
        self._profile = profile
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

    def reindex(self, space: str) -> ReindexResult:
        """Recreate the index and backfill derived Embeddings for a MemorySpace.

        Recreating the persistent vector index at the configured dimensions is
        the sanctioned repair for embedding provider/model/dimension drift; the
        storage-specific drop/recreate lives inside the retrieval index adapter.
        """
        self._index.recreate_index(self._dimensions)
        self._index.clear_space(space)
        indexed_by_kind = {
            "Entity": 0,
            "Decision": 0,
            "Task": 0,
            "Observation": 0,
            "Relation": 0,
        }
        indexer = EmbeddingIndexer(
            retrieval_index=self._index,
            embedding_provider=self._embedding_provider,
            dimensions=self._dimensions,
        )

        for entity in self._entity_repo.list_by_space(space):
            indexer.upsert_entity(entity)
            indexed_by_kind["Entity"] += 1

        for decision in self._decision_repo.list_by_space(space):
            indexer.upsert_decision(decision)
            indexed_by_kind["Decision"] += 1

        for task in self._task_repo.list_by_space(space):
            indexer.upsert_task(task)
            indexed_by_kind["Task"] += 1

        for observation in self._observation_repo.list_by_space(space):
            indexer.upsert_observation(observation)
            indexed_by_kind["Observation"] += 1

        if self._relation_repo is not None:
            for relation in self._relation_repo.list_by_space(space):
                indexer.upsert_relation(relation)
                indexed_by_kind["Relation"] += 1

        return ReindexResult(space=space, indexed_by_kind=indexed_by_kind)

    def _empty_kind_counts(self) -> dict[str, int]:
        return {kind: 0 for kind in SOURCE_KINDS}

    def _expected_embedding_hashes(
        self, space: str
    ) -> dict[tuple[str, str], tuple[str, str]]:
        expected: dict[tuple[str, str], tuple[str, str]] = {}

        def add(source_kind: str, source_id: str, indexable_text: str) -> None:
            expected[(source_kind, source_id)] = (
                hashlib.sha256(indexable_text.encode()).hexdigest(),
                INDEXABLE_TEXT_VERSION,
            )

        for entity in self._entity_repo.list_by_space(space):
            add("Entity", entity.id, indexable_text_for_entity(entity))
        for decision in self._decision_repo.list_by_space(space):
            add("Decision", decision.id, indexable_text_for_decision(decision))
        for task in self._task_repo.list_by_space(space):
            add("Task", task.id, indexable_text_for_task(task))
        for observation in self._observation_repo.list_by_space(space):
            add(
                "Observation",
                observation.id,
                indexable_text_for_observation(observation),
            )
        if self._relation_repo is not None:
            for relation in self._relation_repo.list_by_space(space):
                add("Relation", relation.id, indexable_text_for_relation(relation))
        return expected

    def index_coverage(self, space: str) -> EmbeddingCoverageReport:
        """Report active Embedding coverage for a MemorySpace."""
        expected = self._expected_embedding_hashes(space)
        expected_by_kind = self._empty_kind_counts()
        active_by_kind = self._empty_kind_counts()
        missing_by_kind = self._empty_kind_counts()
        stale_by_kind = self._empty_kind_counts()
        unusable_by_kind = self._empty_kind_counts()
        incompatible_by_kind = self._empty_kind_counts()

        records_by_source: dict[tuple[str, str], list[EmbeddingRecord]] = {}
        for record in self._index.records(space=space):
            key = (record.source_kind, record.source_id)
            if key in expected:
                records_by_source.setdefault(key, []).append(record)

        for (source_kind, source_id), (
            expected_hash,
            expected_version,
        ) in expected.items():
            expected_by_kind[source_kind] += 1
            records = records_by_source.get((source_kind, source_id), [])
            active_records = [
                record
                for record in records
                if self._is_active_embedding_metadata(record)
            ]
            incompatible_records = [
                record
                for record in records
                if not self._is_active_embedding_metadata(record)
            ]
            if incompatible_records:
                incompatible_by_kind[source_kind] += 1
            if not active_records:
                missing_by_kind[source_kind] += 1
                continue

            active_by_kind[source_kind] += 1
            usable_records = [
                record
                for record in active_records
                if len(record.vector) == self._dimensions
            ]
            if not usable_records:
                unusable_by_kind[source_kind] += 1
                continue
            if not any(
                record.indexable_text_hash == expected_hash
                and record.indexable_text_version == expected_version
                for record in usable_records
            ):
                stale_by_kind[source_kind] += 1

        return EmbeddingCoverageReport(
            space=space,
            provider_name=self._embedding_provider.provider_name,
            model_name=self._embedding_provider.model_name,
            dimensions=self._dimensions,
            expected_by_kind=expected_by_kind,
            active_by_kind=active_by_kind,
            missing_by_kind=missing_by_kind,
            stale_by_kind=stale_by_kind,
            unusable_by_kind=unusable_by_kind,
            incompatible_by_kind=incompatible_by_kind,
        )

    def _is_active_embedding_metadata(self, record: EmbeddingRecord) -> bool:
        return (
            record.provider_name == self._embedding_provider.provider_name
            and record.model_name == self._embedding_provider.model_name
            and record.dimensions == self._dimensions
        )

    def _ensure_search_index_compatible(self, space: str) -> None:
        report = self.index_coverage(space)
        if report.expected_total == 0:
            return
        if report.active_total == 0:
            msg = (
                f"No compatible Embeddings found for MemorySpace '{space}' using "
                "active Embedding Provider "
                f"'{self._embedding_provider.provider_name}', model "
                f"'{self._embedding_provider.model_name}', dimensions "
                f"{self._dimensions}. Run `memorable reindex --space {space}` "
                "to rebuild derived Embeddings for the active settings."
            )
            raise EmbeddingIndexCompatibilityError(msg)
        if not report.ok:
            raise EmbeddingIndexCompatibilityError(report.actionable_hint)

    def search(
        self,
        space: str,
        query: str,
        mode: Literal["current", "as-of"] = "current",
        as_of: datetime | None = None,
        top_k: int = 10,
        record_type: str | None = None,
        attribute_filter: Mapping[str, object] | None = None,
    ) -> list[RetrievalResult]:
        """Perform hybrid GraphRAG retrieval.

        Steps:
        1. Embed query and find semantic candidates in the persistent index
        2. Graph expansion: find related records for each candidate
        3. Temporal filtering based on mode
        4. Record Subtype filtering when requested
        5. Rank by cosine similarity
        6. Build provenance-aware explanations

        Args:
            space: MemorySpace to search
            query: Natural language query
            mode: "current" for Current Truth,
                  "as-of" for Point-In-Time Truth
            as_of: Required when mode is "as-of"
            top_k: Maximum number of results to return
            record_type: Optional Record Subtype filter
        """
        validated_attribute_filter = self._validated_attribute_filter(
            attribute_filter
        )

        # Step 1: Semantic candidates from the persistent index.
        try:
            query_vector = self._embedding_provider.embed(query)
        except Exception as exc:
            msg = (
                "Embedding Provider failed to embed the search query for "
                f"MemorySpace '{space}' using provider "
                f"'{self._embedding_provider.provider_name}', model "
                f"'{self._embedding_provider.model_name}', dimensions "
                f"{self._dimensions}. Run `memorable doctor` to diagnose "
                f"Embedding settings. Original error: {exc}"
            )
            raise EmbeddingIndexCompatibilityError(msg) from exc
        try:
            candidates = self._index.search(
                space=space,
                query_vector=query_vector,
                top_k=top_k * 2,
                provider_name=self._embedding_provider.provider_name,
                model_name=self._embedding_provider.model_name,
                dimensions=self._dimensions,
            )
        except Exception as exc:
            msg = (
                f"Embedding index search failed for MemorySpace '{space}' "
                "using active Embedding Provider "
                f"'{self._embedding_provider.provider_name}', model "
                f"'{self._embedding_provider.model_name}', dimensions "
                f"{self._dimensions}. Run `memorable doctor` to diagnose "
                "vector index compatibility, then run `memorable reindex "
                f"--space {space}` to rebuild derived Embeddings. "
                f"Original error: {exc}"
            )
            raise EmbeddingIndexCompatibilityError(msg) from exc
        self._ensure_search_index_compatible(space)

        # Step 2: Graph expansion -- collect related IDs
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

        # Step 4: Temporal filtering, result building, and subtype filtering
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
            if result is None:
                continue
            if record_type is not None and result.record_type != record_type:
                continue
            if validated_attribute_filter is not None and not _matches_attribute_filter(
                result,
                validated_attribute_filter,
            ):
                continue
            results.append(result)

        # Step 5: Final ranking by score
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]

    def _validated_attribute_filter(
        self,
        attribute_filter: Mapping[str, object] | None,
    ) -> dict[str, object] | None:
        if not attribute_filter:
            return None
        if self._profile is None:
            raise AttributeValidationError(
                "Attribute filters require a MemoryProfile with Entity "
                "Attribute declarations."
            )
        return validate_attribute_filter_values(
            [entity.attributes for entity in self._profile.entities],
            attribute_filter,
        )

    def _graph_expand(
        self, space: str, source_id: str, source_kind: str
    ) -> list[tuple[str, str]]:
        """Find related records via graph traversal.

        Entity expansion uses Relation-based 1-hop traversal plus About links
        to records about the Entity. Decision, Task, and Observation expansion
        uses About links to Entities plus supersession chain neighbours where
        applicable. There is no all-Entities fallback.
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
            if self._about_repo is not None:
                for record_id in self._about_repo.records_for_entity(space, source_id):
                    record_kind = self._record_kind(space, record_id)
                    if record_kind is not None:
                        related.append((record_id, record_kind))

        elif source_kind == "Decision":
            related.extend(self._about_entities(space, source_id))
            decision = self._decision_repo.get(space, source_id)
            if decision and decision.supersedes:
                related.append((decision.supersedes, "Decision"))
            if decision and decision.superseded_by:
                related.append((decision.superseded_by, "Decision"))

        elif source_kind == "Task":
            related.extend(self._about_entities(space, source_id))

        elif source_kind == "Observation":
            related.extend(self._about_entities(space, source_id))
            observation = self._observation_repo.get(space, source_id)
            if observation and observation.supersedes:
                related.append((observation.supersedes, "Observation"))
            if observation and observation.superseded_by:
                related.append((observation.superseded_by, "Observation"))

        return related

    def _about_entities(self, space: str, record_id: str) -> list[tuple[str, str]]:
        if self._about_repo is None:
            return []
        return [
            (entity_id, "Entity")
            for entity_id in self._about_repo.entities_for_record(space, record_id)
        ]

    def _record_kind(self, space: str, record_id: str) -> str | None:
        if self._decision_repo.get(space, record_id) is not None:
            return "Decision"
        if self._task_repo.get(space=space, task_id=record_id) is not None:
            return "Task"
        if self._observation_repo.get(space, record_id) is not None:
            return "Observation"
        return None

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
            attributes=copy_attribute_values(entity.attributes),
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
            record_type=decision.record_type,
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
            record_type=task.record_type,
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
            record_type=observation.record_type,
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


def _matches_attribute_filter(
    result: RetrievalResult,
    attribute_filter: Mapping[str, object],
) -> bool:
    if result.source_kind != "Entity":
        return False
    return all(
        result.attributes.get(name) == value
        for name, value in attribute_filter.items()
    )


def build_retrieval_service(
    context: ApplicationContext,
    embedding_provider: EmbeddingProvider,
    *,
    dimensions: int = 32,
    profile: MemoryProfile | None = None,
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
        dimensions=dimensions,
        observation_repo=context.observation_repo,
        relation_repo=context.relation_repo,
        about_repo=context.about_repo,
        retrieval_index=context.retrieval_index,
        profile=profile,
    )
