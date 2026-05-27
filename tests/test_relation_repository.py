"""Tests for Relation repository, application service, and temporal lifecycle.

Covers slice #61 acceptance criteria:
- RelationRepository protocol with save, get, get_provenance, list_by_space,
  mark_superseded, list_by_entity
- InMemoryRelationRepository implements the full protocol including list_by_entity
- list_by_entity returns Relations where entity is source or target
- RememberRelationService validates relation type, entity existence, self-relations
- RememberRelationService creates provenance with record_kind="relation"
- Supersession wiring works for Relations
- ApplicationContext has relation_repo defaulting to InMemoryRelationRepository
- DEFAULT_PROFILE_YAML includes a relations section
- Generic temporal services (CurrentTruth, PointInTimeTruth, InspectHistory,
  Invalidate, Correct) work with Relations
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

# --- Fixture data ---

FIXTURE_TIMESTAMP_V1 = datetime(2026, 5, 26, 9, 0, 0, tzinfo=UTC)
FIXTURE_TIMESTAMP_V2 = datetime(2026, 5, 26, 9, 10, 0, tzinfo=UTC)

REL_V1_ID = "rel:auth-depends-on-token:v1"
REL_V2_ID = "rel:auth-depends-on-token:v2"
ENTITY_A_ID = "entity:auth-module"
ENTITY_B_ID = "entity:token-service"
ENTITY_C_ID = "entity:user-service"
SOURCE_ID = "source:agent-session"
SPACE = "memorable"

STATEMENT_V1 = "auth-module depends on token-service for JWT validation"
STATEMENT_V2 = "auth-module depends on token-service for OAuth2 token exchange"


# =====================================================================
# InMemoryRelationRepository tests
# =====================================================================


class TestInMemoryRelationRepositorySaveAndRetrieve:
    """InMemoryRelationRepository stores and retrieves Relations."""

    def _make_relation(
        self,
        rel_id: str = REL_V1_ID,
        source: str = ENTITY_A_ID,
        target: str = ENTITY_B_ID,
    ):
        from memorable.core.models import Provenance, Relation

        relation = Relation(
            id=rel_id,
            source_entity_id=source,
            target_entity_id=target,
            relation_type="depends-on",
            statement=STATEMENT_V1,
            space=SPACE,
            validity_time=FIXTURE_TIMESTAMP_V1,
            invalidation_time=None,
            lifecycle_state="current",
            supersedes=None,
            superseded_by=None,
        )
        provenance = Provenance(
            record_id=rel_id,
            record_kind="relation",
            source_id=SOURCE_ID,
            episode_id="episode:agent-session:2026-05-26T09:00:00+00:00",
            writer="agent:test",
            reason="initial relation",
            creation_time=FIXTURE_TIMESTAMP_V1,
            validity_time=FIXTURE_TIMESTAMP_V1,
        )
        return relation, provenance

    def test_save_and_get_relation(self) -> None:
        from memorable.core.repositories import InMemoryRelationRepository

        repo = InMemoryRelationRepository()
        rel, prov = self._make_relation()

        repo.save(rel, prov)
        retrieved = repo.get(space=SPACE, record_id=REL_V1_ID)

        assert retrieved is not None
        assert retrieved.id == REL_V1_ID
        assert retrieved.source_entity_id == ENTITY_A_ID
        assert retrieved.target_entity_id == ENTITY_B_ID
        assert retrieved.relation_type == "depends-on"
        assert retrieved.statement == STATEMENT_V1

    def test_get_returns_none_for_missing(self) -> None:
        from memorable.core.repositories import InMemoryRelationRepository

        repo = InMemoryRelationRepository()
        assert repo.get(space=SPACE, record_id="rel:missing") is None

    def test_retrieve_provenance(self) -> None:
        from memorable.core.repositories import InMemoryRelationRepository

        repo = InMemoryRelationRepository()
        rel, prov = self._make_relation()

        repo.save(rel, prov)
        retrieved_prov = repo.get_provenance(space=SPACE, record_id=REL_V1_ID)

        assert retrieved_prov is not None
        assert retrieved_prov.source_id == SOURCE_ID
        assert retrieved_prov.record_kind == "relation"

    def test_get_provenance_returns_none_for_missing(self) -> None:
        from memorable.core.repositories import InMemoryRelationRepository

        repo = InMemoryRelationRepository()
        assert repo.get_provenance(space=SPACE, record_id="rel:missing") is None

    def test_list_by_space(self) -> None:
        from memorable.core.repositories import InMemoryRelationRepository

        repo = InMemoryRelationRepository()
        r1, p1 = self._make_relation(rel_id="rel:1")
        r2, p2 = self._make_relation(
            rel_id="rel:2",
            source=ENTITY_B_ID,
            target=ENTITY_C_ID,
        )

        repo.save(r1, p1)
        repo.save(r2, p2)

        relations = repo.list_by_space(SPACE)
        assert len(relations) == 2
        ids = {r.id for r in relations}
        assert ids == {"rel:1", "rel:2"}

    def test_mark_superseded_updates_old_relation(self) -> None:
        from memorable.core.repositories import InMemoryRelationRepository

        repo = InMemoryRelationRepository()
        rel, prov = self._make_relation()

        repo.save(rel, prov)
        repo.mark_superseded(
            space=SPACE,
            record_id=REL_V1_ID,
            superseded_by=REL_V2_ID,
            invalidation_time=FIXTURE_TIMESTAMP_V2,
        )

        updated = repo.get(space=SPACE, record_id=REL_V1_ID)
        assert updated is not None
        assert updated.lifecycle_state == "superseded"
        assert updated.invalidation_time == FIXTURE_TIMESTAMP_V2
        assert updated.superseded_by == REL_V2_ID


# =====================================================================
# list_by_entity tests
# =====================================================================


class TestListByEntity:
    """list_by_entity returns Relations where entity is source or target."""

    def _make_relation(
        self,
        rel_id: str,
        source: str,
        target: str,
        space: str = SPACE,
    ):
        from memorable.core.models import Provenance, Relation

        relation = Relation(
            id=rel_id,
            source_entity_id=source,
            target_entity_id=target,
            relation_type="depends-on",
            statement=f"{source} depends on {target}",
            space=space,
            validity_time=FIXTURE_TIMESTAMP_V1,
            invalidation_time=None,
            lifecycle_state="current",
            supersedes=None,
            superseded_by=None,
        )
        provenance = Provenance(
            record_id=rel_id,
            record_kind="relation",
            source_id=SOURCE_ID,
            episode_id="episode:agent-session:2026-05-26T09:00:00+00:00",
            writer="agent:test",
            reason="test relation",
            creation_time=FIXTURE_TIMESTAMP_V1,
            validity_time=FIXTURE_TIMESTAMP_V1,
        )
        return relation, provenance

    def test_returns_relations_where_entity_is_source(self) -> None:
        from memorable.core.repositories import InMemoryRelationRepository

        repo = InMemoryRelationRepository()
        r1, p1 = self._make_relation("rel:1", ENTITY_A_ID, ENTITY_B_ID)
        r2, p2 = self._make_relation("rel:2", ENTITY_A_ID, ENTITY_C_ID)
        r3, p3 = self._make_relation("rel:3", ENTITY_B_ID, ENTITY_C_ID)

        repo.save(r1, p1)
        repo.save(r2, p2)
        repo.save(r3, p3)

        results = repo.list_by_entity(space=SPACE, entity_id=ENTITY_A_ID)
        ids = {r.id for r in results}
        assert ids == {"rel:1", "rel:2"}

    def test_returns_relations_where_entity_is_target(self) -> None:
        from memorable.core.repositories import InMemoryRelationRepository

        repo = InMemoryRelationRepository()
        r1, p1 = self._make_relation("rel:1", ENTITY_A_ID, ENTITY_B_ID)
        r2, p2 = self._make_relation("rel:2", ENTITY_C_ID, ENTITY_B_ID)

        repo.save(r1, p1)
        repo.save(r2, p2)

        results = repo.list_by_entity(space=SPACE, entity_id=ENTITY_B_ID)
        ids = {r.id for r in results}
        assert ids == {"rel:1", "rel:2"}

    def test_returns_empty_for_unrelated_entity(self) -> None:
        from memorable.core.repositories import InMemoryRelationRepository

        repo = InMemoryRelationRepository()
        r1, p1 = self._make_relation("rel:1", ENTITY_A_ID, ENTITY_B_ID)
        repo.save(r1, p1)

        results = repo.list_by_entity(space=SPACE, entity_id=ENTITY_C_ID)
        assert results == []

    def test_filters_by_space(self) -> None:
        from memorable.core.repositories import InMemoryRelationRepository

        repo = InMemoryRelationRepository()
        r1, p1 = self._make_relation("rel:1", ENTITY_A_ID, ENTITY_B_ID, space="space-a")
        r2, p2 = self._make_relation("rel:2", ENTITY_A_ID, ENTITY_C_ID, space="space-b")

        repo.save(r1, p1)
        repo.save(r2, p2)

        results = repo.list_by_entity(space="space-a", entity_id=ENTITY_A_ID)
        assert len(results) == 1
        assert results[0].id == "rel:1"


# =====================================================================
# Protocol satisfaction tests
# =====================================================================


class TestRelationRepositoryProtocolSatisfaction:
    """InMemoryRelationRepository satisfies TemporalRecordRepository protocol."""

    def test_relation_repo_inherits_from_temporal(self) -> None:
        from memorable.core.repositories import (
            InMemoryRelationRepository,
            InMemoryTemporalRepository,
        )

        repo = InMemoryRelationRepository()
        assert isinstance(repo, InMemoryTemporalRepository)

    def test_relation_repo_satisfies_temporal_record_protocol(self) -> None:
        from memorable.core.ports import TemporalRecordRepository
        from memorable.core.repositories import InMemoryRelationRepository

        repo = InMemoryRelationRepository()
        assert isinstance(repo, TemporalRecordRepository)

    def test_relation_repo_has_all_required_methods(self) -> None:
        from memorable.core.repositories import InMemoryRelationRepository

        repo = InMemoryRelationRepository()
        required = (
            "save",
            "get",
            "get_provenance",
            "list_by_space",
            "mark_superseded",
            "list_by_entity",
        )
        for method in required:
            assert hasattr(repo, method), f"Missing method: {method}"
            assert callable(getattr(repo, method))


# =====================================================================
# RememberRelationService tests
# =====================================================================

VALID_PROFILE_YAML = """\
version: 1

space:
  name: memorable
  description: Agent memory system

entities:
  - name: Module
  - name: Service

relations:
  - name: depends-on
  - name: owns

records:
  - name: ArchitectureDecision
    extends: Decision
  - name: GeneralObservation
    extends: Observation
"""


class TestRememberRelationService:
    """RememberRelationService validates and creates Relations with provenance."""

    def _make_service(self):
        from memorable.core.application import RememberRelationService
        from memorable.core.profile import load_profile_from_yaml
        from memorable.core.repositories import (
            InMemoryEntityRepository,
            InMemoryRelationRepository,
        )

        relation_repo = InMemoryRelationRepository()
        entity_repo = InMemoryEntityRepository()
        profile = load_profile_from_yaml(VALID_PROFILE_YAML)
        service = RememberRelationService(
            relation_repo=relation_repo,
            entity_repo=entity_repo,
            profile=profile,
        )
        return service, relation_repo, entity_repo

    def _store_entities(self, entity_repo):
        from memorable.core.models import Entity, Provenance

        for eid, etype, name in [
            (ENTITY_A_ID, "Module", "auth-module"),
            (ENTITY_B_ID, "Service", "token-service"),
            (ENTITY_C_ID, "Service", "user-service"),
        ]:
            entity = Entity(id=eid, entity_type=etype, name=name, space=SPACE)
            prov = Provenance(
                record_id=eid,
                record_kind="entity",
                source_id=SOURCE_ID,
                episode_id="episode:test:2026-05-26T09:00:00+00:00",
                writer="agent:test",
                reason="test entity",
                creation_time=FIXTURE_TIMESTAMP_V1,
                validity_time=FIXTURE_TIMESTAMP_V1,
            )
            entity_repo.save(entity, prov)

    def test_remember_relation_stores_with_provenance(self) -> None:
        service, relation_repo, entity_repo = self._make_service()
        self._store_entities(entity_repo)

        result = service.remember(
            space=SPACE,
            relation_id=REL_V1_ID,
            source_entity_id=ENTITY_A_ID,
            target_entity_id=ENTITY_B_ID,
            relation_type="depends-on",
            statement=STATEMENT_V1,
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMP_V1,
        )

        assert result.relation.id == REL_V1_ID
        assert result.relation.lifecycle_state == "current"
        assert result.provenance.source_id == SOURCE_ID
        assert result.provenance.record_kind == "relation"
        assert result.provenance.creation_time == FIXTURE_TIMESTAMP_V1

        stored = relation_repo.get(space=SPACE, record_id=REL_V1_ID)
        assert stored is not None

    def test_rejects_undeclared_relation_type(self) -> None:
        service, _relation_repo, entity_repo = self._make_service()
        self._store_entities(entity_repo)

        with pytest.raises(ValueError, match="not declared"):
            service.remember(
                space=SPACE,
                relation_id="rel:x",
                source_entity_id=ENTITY_A_ID,
                target_entity_id=ENTITY_B_ID,
                relation_type="unknown-type",
                statement="A connects to B",
                source_id=SOURCE_ID,
                at=FIXTURE_TIMESTAMP_V1,
            )

    def test_rejects_missing_source_entity(self) -> None:
        service, _relation_repo, entity_repo = self._make_service()
        self._store_entities(entity_repo)

        with pytest.raises(ValueError, match="source.*not found"):
            service.remember(
                space=SPACE,
                relation_id="rel:x",
                source_entity_id="entity:nonexistent",
                target_entity_id=ENTITY_B_ID,
                relation_type="depends-on",
                statement="ghost depends on B",
                source_id=SOURCE_ID,
                at=FIXTURE_TIMESTAMP_V1,
            )

    def test_rejects_missing_target_entity(self) -> None:
        service, _relation_repo, entity_repo = self._make_service()
        self._store_entities(entity_repo)

        with pytest.raises(ValueError, match="target.*not found"):
            service.remember(
                space=SPACE,
                relation_id="rel:x",
                source_entity_id=ENTITY_A_ID,
                target_entity_id="entity:nonexistent",
                relation_type="depends-on",
                statement="A depends on ghost",
                source_id=SOURCE_ID,
                at=FIXTURE_TIMESTAMP_V1,
            )

    def test_rejects_self_relation(self) -> None:
        service, _relation_repo, entity_repo = self._make_service()
        self._store_entities(entity_repo)

        with pytest.raises(ValueError, match="self-relation"):
            service.remember(
                space=SPACE,
                relation_id="rel:x",
                source_entity_id=ENTITY_A_ID,
                target_entity_id=ENTITY_A_ID,
                relation_type="depends-on",
                statement="A depends on A",
                source_id=SOURCE_ID,
                at=FIXTURE_TIMESTAMP_V1,
            )

    def test_remember_with_supersession(self) -> None:
        service, relation_repo, entity_repo = self._make_service()
        self._store_entities(entity_repo)

        # Remember v1
        service.remember(
            space=SPACE,
            relation_id=REL_V1_ID,
            source_entity_id=ENTITY_A_ID,
            target_entity_id=ENTITY_B_ID,
            relation_type="depends-on",
            statement=STATEMENT_V1,
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMP_V1,
        )

        # Remember v2, superseding v1
        result = service.remember(
            space=SPACE,
            relation_id=REL_V2_ID,
            source_entity_id=ENTITY_A_ID,
            target_entity_id=ENTITY_B_ID,
            relation_type="depends-on",
            statement=STATEMENT_V2,
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMP_V2,
            supersedes=REL_V1_ID,
        )

        assert result.relation.id == REL_V2_ID
        assert result.relation.supersedes == REL_V1_ID
        assert result.relation.lifecycle_state == "current"

        # v1 should now be marked superseded
        v1 = relation_repo.get(space=SPACE, record_id=REL_V1_ID)
        assert v1 is not None
        assert v1.lifecycle_state == "superseded"
        assert v1.invalidation_time == FIXTURE_TIMESTAMP_V2
        assert v1.superseded_by == REL_V2_ID

    def test_remember_sets_writer(self) -> None:
        service, _relation_repo, entity_repo = self._make_service()
        self._store_entities(entity_repo)

        result = service.remember(
            space=SPACE,
            relation_id=REL_V1_ID,
            source_entity_id=ENTITY_A_ID,
            target_entity_id=ENTITY_B_ID,
            relation_type="depends-on",
            statement=STATEMENT_V1,
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMP_V1,
            writer="agent:test-writer",
        )

        assert result.provenance.writer == "agent:test-writer"


# =====================================================================
# ApplicationContext + DEFAULT_PROFILE_YAML tests
# =====================================================================


class TestRelationInApplicationContext:
    """relation_repo is wired into ApplicationContext."""

    def test_context_has_relation_repo(self) -> None:
        from memorable.core.context import ApplicationContext

        ctx = ApplicationContext()
        assert hasattr(ctx, "relation_repo")
        assert ctx.relation_repo is not None

    def test_default_context_has_relation_repo(self) -> None:
        from memorable.core.context import default_context

        assert hasattr(default_context, "relation_repo")
        assert default_context.relation_repo is not None

    def test_reset_clears_relation_repo(self) -> None:
        from memorable.core.context import ApplicationContext
        from memorable.core.models import Provenance, Relation

        ctx = ApplicationContext()
        rel = Relation(
            id=REL_V1_ID,
            source_entity_id=ENTITY_A_ID,
            target_entity_id=ENTITY_B_ID,
            relation_type="depends-on",
            statement=STATEMENT_V1,
            space=SPACE,
            validity_time=FIXTURE_TIMESTAMP_V1,
            invalidation_time=None,
            lifecycle_state="current",
            supersedes=None,
            superseded_by=None,
        )
        prov = Provenance(
            record_id=REL_V1_ID,
            record_kind="relation",
            source_id=SOURCE_ID,
            episode_id="episode:test:2026-05-26T09:00:00+00:00",
            writer="agent:test",
            reason="test",
            creation_time=FIXTURE_TIMESTAMP_V1,
            validity_time=FIXTURE_TIMESTAMP_V1,
        )
        ctx.relation_repo.save(rel, prov)
        ctx.reset()
        assert ctx.relation_repo.get(space=SPACE, record_id=REL_V1_ID) is None

    def test_relation_repo_is_in_memory_relation_repository(self) -> None:
        from memorable.core.context import ApplicationContext
        from memorable.core.repositories import InMemoryRelationRepository

        ctx = ApplicationContext()
        assert isinstance(ctx.relation_repo, InMemoryRelationRepository)


class TestDefaultProfileYAMLHasRelations:
    """DEFAULT_PROFILE_YAML includes a relations section."""

    def test_default_profile_has_relations_section(self) -> None:
        from memorable.core.context import DEFAULT_PROFILE_YAML
        from memorable.core.profile import load_profile_from_yaml

        profile = load_profile_from_yaml(DEFAULT_PROFILE_YAML)
        assert len(profile.relations) > 0

    def test_default_profile_includes_depends_on(self) -> None:
        from memorable.core.context import DEFAULT_PROFILE_YAML
        from memorable.core.profile import load_profile_from_yaml

        profile = load_profile_from_yaml(DEFAULT_PROFILE_YAML)
        relation_names = {r.name for r in profile.relations}
        assert "depends-on" in relation_names


# =====================================================================
# Generic temporal services work with Relations
# =====================================================================


class TestCurrentTruthServiceWithRelation:
    """CurrentTruthService follows supersession chain for Relations."""

    def _setup_chain(self):
        from memorable.core.application import (
            CurrentTruthService,
            RememberRelationService,
        )
        from memorable.core.profile import load_profile_from_yaml
        from memorable.core.repositories import (
            InMemoryEntityRepository,
            InMemoryRelationRepository,
        )

        relation_repo = InMemoryRelationRepository()
        entity_repo = InMemoryEntityRepository()
        profile = load_profile_from_yaml(VALID_PROFILE_YAML)

        # Store entities
        from memorable.core.models import Entity, Provenance

        for eid, etype, name in [
            (ENTITY_A_ID, "Module", "auth-module"),
            (ENTITY_B_ID, "Service", "token-service"),
        ]:
            entity = Entity(id=eid, entity_type=etype, name=name, space=SPACE)
            prov = Provenance(
                record_id=eid,
                record_kind="entity",
                source_id=SOURCE_ID,
                episode_id="episode:test:2026-05-26T09:00:00+00:00",
                writer="agent:test",
                reason="test",
                creation_time=FIXTURE_TIMESTAMP_V1,
                validity_time=FIXTURE_TIMESTAMP_V1,
            )
            entity_repo.save(entity, prov)

        remember = RememberRelationService(
            relation_repo=relation_repo,
            entity_repo=entity_repo,
            profile=profile,
        )

        remember.remember(
            space=SPACE,
            relation_id=REL_V1_ID,
            source_entity_id=ENTITY_A_ID,
            target_entity_id=ENTITY_B_ID,
            relation_type="depends-on",
            statement=STATEMENT_V1,
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMP_V1,
        )
        remember.remember(
            space=SPACE,
            relation_id=REL_V2_ID,
            source_entity_id=ENTITY_A_ID,
            target_entity_id=ENTITY_B_ID,
            relation_type="depends-on",
            statement=STATEMENT_V2,
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMP_V2,
            supersedes=REL_V1_ID,
        )

        return CurrentTruthService(repository=relation_repo), relation_repo

    def test_current_truth_returns_superseding_relation(self) -> None:
        service, _repo = self._setup_chain()

        result = service.current(space=SPACE, record_id=REL_V1_ID)
        assert result is not None
        assert result.id == REL_V2_ID

    def test_current_truth_returns_self_when_not_superseded(self) -> None:
        from memorable.core.application import (
            CurrentTruthService,
            RememberRelationService,
        )
        from memorable.core.models import Entity, Provenance
        from memorable.core.profile import load_profile_from_yaml
        from memorable.core.repositories import (
            InMemoryEntityRepository,
            InMemoryRelationRepository,
        )

        relation_repo = InMemoryRelationRepository()
        entity_repo = InMemoryEntityRepository()
        profile = load_profile_from_yaml(VALID_PROFILE_YAML)

        for eid, etype, name in [
            (ENTITY_A_ID, "Module", "auth-module"),
            (ENTITY_B_ID, "Service", "token-service"),
        ]:
            entity = Entity(id=eid, entity_type=etype, name=name, space=SPACE)
            prov = Provenance(
                record_id=eid,
                record_kind="entity",
                source_id=SOURCE_ID,
                episode_id="episode:test:2026-05-26T09:00:00+00:00",
                writer="agent:test",
                reason="test",
                creation_time=FIXTURE_TIMESTAMP_V1,
                validity_time=FIXTURE_TIMESTAMP_V1,
            )
            entity_repo.save(entity, prov)

        remember = RememberRelationService(
            relation_repo=relation_repo,
            entity_repo=entity_repo,
            profile=profile,
        )
        remember.remember(
            space=SPACE,
            relation_id=REL_V1_ID,
            source_entity_id=ENTITY_A_ID,
            target_entity_id=ENTITY_B_ID,
            relation_type="depends-on",
            statement=STATEMENT_V1,
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMP_V1,
        )

        service = CurrentTruthService(repository=relation_repo)
        result = service.current(space=SPACE, record_id=REL_V1_ID)
        assert result is not None
        assert result.id == REL_V1_ID


class TestPointInTimeTruthServiceWithRelation:
    """PointInTimeTruthService returns Relation valid at a given time."""

    def _setup_chain(self):
        from memorable.core.application import (
            PointInTimeTruthService,
            RememberRelationService,
        )
        from memorable.core.models import Entity, Provenance
        from memorable.core.profile import load_profile_from_yaml
        from memorable.core.repositories import (
            InMemoryEntityRepository,
            InMemoryRelationRepository,
        )

        relation_repo = InMemoryRelationRepository()
        entity_repo = InMemoryEntityRepository()
        profile = load_profile_from_yaml(VALID_PROFILE_YAML)

        for eid, etype, name in [
            (ENTITY_A_ID, "Module", "auth-module"),
            (ENTITY_B_ID, "Service", "token-service"),
        ]:
            entity = Entity(id=eid, entity_type=etype, name=name, space=SPACE)
            prov = Provenance(
                record_id=eid,
                record_kind="entity",
                source_id=SOURCE_ID,
                episode_id="episode:test:2026-05-26T09:00:00+00:00",
                writer="agent:test",
                reason="test",
                creation_time=FIXTURE_TIMESTAMP_V1,
                validity_time=FIXTURE_TIMESTAMP_V1,
            )
            entity_repo.save(entity, prov)

        remember = RememberRelationService(
            relation_repo=relation_repo,
            entity_repo=entity_repo,
            profile=profile,
        )

        remember.remember(
            space=SPACE,
            relation_id=REL_V1_ID,
            source_entity_id=ENTITY_A_ID,
            target_entity_id=ENTITY_B_ID,
            relation_type="depends-on",
            statement=STATEMENT_V1,
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMP_V1,
        )
        remember.remember(
            space=SPACE,
            relation_id=REL_V2_ID,
            source_entity_id=ENTITY_A_ID,
            target_entity_id=ENTITY_B_ID,
            relation_type="depends-on",
            statement=STATEMENT_V2,
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMP_V2,
            supersedes=REL_V1_ID,
        )

        return PointInTimeTruthService(repository=relation_repo), relation_repo

    def test_before_supersession_returns_v1(self) -> None:
        service, _repo = self._setup_chain()

        at_query = datetime(2026, 5, 26, 9, 5, 0, tzinfo=UTC)
        result = service.at(space=SPACE, record_id=REL_V1_ID, at=at_query)
        assert result is not None
        assert result.id == REL_V1_ID

    def test_after_supersession_returns_v2(self) -> None:
        service, _repo = self._setup_chain()

        at_query = datetime(2026, 5, 26, 9, 15, 0, tzinfo=UTC)
        result = service.at(space=SPACE, record_id=REL_V1_ID, at=at_query)
        assert result is not None
        assert result.id == REL_V2_ID


class TestInspectHistoryServiceWithRelation:
    """InspectHistoryService returns full supersession chain for Relations."""

    def _setup_chain(self):
        from memorable.core.application import (
            InspectHistoryService,
            RememberRelationService,
        )
        from memorable.core.models import Entity, Provenance
        from memorable.core.profile import load_profile_from_yaml
        from memorable.core.repositories import (
            InMemoryEntityRepository,
            InMemoryRelationRepository,
        )

        relation_repo = InMemoryRelationRepository()
        entity_repo = InMemoryEntityRepository()
        profile = load_profile_from_yaml(VALID_PROFILE_YAML)

        for eid, etype, name in [
            (ENTITY_A_ID, "Module", "auth-module"),
            (ENTITY_B_ID, "Service", "token-service"),
        ]:
            entity = Entity(id=eid, entity_type=etype, name=name, space=SPACE)
            prov = Provenance(
                record_id=eid,
                record_kind="entity",
                source_id=SOURCE_ID,
                episode_id="episode:test:2026-05-26T09:00:00+00:00",
                writer="agent:test",
                reason="test",
                creation_time=FIXTURE_TIMESTAMP_V1,
                validity_time=FIXTURE_TIMESTAMP_V1,
            )
            entity_repo.save(entity, prov)

        remember = RememberRelationService(
            relation_repo=relation_repo,
            entity_repo=entity_repo,
            profile=profile,
        )

        remember.remember(
            space=SPACE,
            relation_id=REL_V1_ID,
            source_entity_id=ENTITY_A_ID,
            target_entity_id=ENTITY_B_ID,
            relation_type="depends-on",
            statement=STATEMENT_V1,
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMP_V1,
        )
        remember.remember(
            space=SPACE,
            relation_id=REL_V2_ID,
            source_entity_id=ENTITY_A_ID,
            target_entity_id=ENTITY_B_ID,
            relation_type="depends-on",
            statement=STATEMENT_V2,
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMP_V2,
            supersedes=REL_V1_ID,
        )

        return InspectHistoryService(repository=relation_repo), relation_repo

    def test_history_returns_full_chain(self) -> None:
        service, _repo = self._setup_chain()

        history = service.history(space=SPACE, record_id=REL_V1_ID)
        assert len(history) == 2
        assert history[0].id == REL_V1_ID
        assert history[1].id == REL_V2_ID

    def test_history_single_when_not_superseded(self) -> None:
        from memorable.core.application import (
            InspectHistoryService,
            RememberRelationService,
        )
        from memorable.core.models import Entity, Provenance
        from memorable.core.profile import load_profile_from_yaml
        from memorable.core.repositories import (
            InMemoryEntityRepository,
            InMemoryRelationRepository,
        )

        relation_repo = InMemoryRelationRepository()
        entity_repo = InMemoryEntityRepository()
        profile = load_profile_from_yaml(VALID_PROFILE_YAML)

        for eid, etype, name in [
            (ENTITY_A_ID, "Module", "auth-module"),
            (ENTITY_B_ID, "Service", "token-service"),
        ]:
            entity = Entity(id=eid, entity_type=etype, name=name, space=SPACE)
            prov = Provenance(
                record_id=eid,
                record_kind="entity",
                source_id=SOURCE_ID,
                episode_id="episode:test:2026-05-26T09:00:00+00:00",
                writer="agent:test",
                reason="test",
                creation_time=FIXTURE_TIMESTAMP_V1,
                validity_time=FIXTURE_TIMESTAMP_V1,
            )
            entity_repo.save(entity, prov)

        remember = RememberRelationService(
            relation_repo=relation_repo,
            entity_repo=entity_repo,
            profile=profile,
        )
        remember.remember(
            space=SPACE,
            relation_id=REL_V1_ID,
            source_entity_id=ENTITY_A_ID,
            target_entity_id=ENTITY_B_ID,
            relation_type="depends-on",
            statement=STATEMENT_V1,
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMP_V1,
        )

        service = InspectHistoryService(repository=relation_repo)
        history = service.history(space=SPACE, record_id=REL_V1_ID)
        assert len(history) == 1
        assert history[0].id == REL_V1_ID


class TestInvalidateServiceWithRelation:
    """InvalidateService invalidates a Relation."""

    def _setup(self):
        from memorable.core.application import (
            InvalidateService,
            RememberRelationService,
        )
        from memorable.core.models import Entity, Provenance
        from memorable.core.profile import load_profile_from_yaml
        from memorable.core.repositories import (
            InMemoryEntityRepository,
            InMemoryRelationRepository,
        )

        relation_repo = InMemoryRelationRepository()
        entity_repo = InMemoryEntityRepository()
        profile = load_profile_from_yaml(VALID_PROFILE_YAML)

        for eid, etype, name in [
            (ENTITY_A_ID, "Module", "auth-module"),
            (ENTITY_B_ID, "Service", "token-service"),
        ]:
            entity = Entity(id=eid, entity_type=etype, name=name, space=SPACE)
            prov = Provenance(
                record_id=eid,
                record_kind="entity",
                source_id=SOURCE_ID,
                episode_id="episode:test:2026-05-26T09:00:00+00:00",
                writer="agent:test",
                reason="test",
                creation_time=FIXTURE_TIMESTAMP_V1,
                validity_time=FIXTURE_TIMESTAMP_V1,
            )
            entity_repo.save(entity, prov)

        remember = RememberRelationService(
            relation_repo=relation_repo,
            entity_repo=entity_repo,
            profile=profile,
        )
        remember.remember(
            space=SPACE,
            relation_id=REL_V1_ID,
            source_entity_id=ENTITY_A_ID,
            target_entity_id=ENTITY_B_ID,
            relation_type="depends-on",
            statement=STATEMENT_V1,
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMP_V1,
        )

        return InvalidateService(repository=relation_repo), relation_repo

    def test_invalidate_relation(self) -> None:
        service, repo = self._setup()

        invalidation_time = datetime(2026, 5, 26, 10, 0, 0, tzinfo=UTC)
        result = service.invalidate(
            space=SPACE,
            record_id=REL_V1_ID,
            at=invalidation_time,
        )

        assert result.record_id == REL_V1_ID
        assert result.lifecycle_state == "invalidated"
        assert result.invalidation_time == invalidation_time

        stored = repo.get(space=SPACE, record_id=REL_V1_ID)
        assert stored is not None
        assert stored.lifecycle_state == "invalidated"
        assert stored.invalidation_time == invalidation_time

    def test_invalidate_rejects_already_invalidated(self) -> None:
        service, _repo = self._setup()

        invalidation_time = datetime(2026, 5, 26, 10, 0, 0, tzinfo=UTC)
        service.invalidate(space=SPACE, record_id=REL_V1_ID, at=invalidation_time)

        with pytest.raises(ValueError, match="already invalidated"):
            service.invalidate(space=SPACE, record_id=REL_V1_ID, at=invalidation_time)


class TestCorrectServiceWithRelation:
    """CorrectService corrects a Relation statement."""

    def _setup(self):
        from memorable.core.application import RememberRelationService
        from memorable.core.models import Entity, Provenance
        from memorable.core.profile import load_profile_from_yaml
        from memorable.core.repositories import (
            InMemoryEntityRepository,
            InMemoryRelationRepository,
        )

        relation_repo = InMemoryRelationRepository()
        entity_repo = InMemoryEntityRepository()
        profile = load_profile_from_yaml(VALID_PROFILE_YAML)

        for eid, etype, name in [
            (ENTITY_A_ID, "Module", "auth-module"),
            (ENTITY_B_ID, "Service", "token-service"),
        ]:
            entity = Entity(id=eid, entity_type=etype, name=name, space=SPACE)
            prov = Provenance(
                record_id=eid,
                record_kind="entity",
                source_id=SOURCE_ID,
                episode_id="episode:test:2026-05-26T09:00:00+00:00",
                writer="agent:test",
                reason="test",
                creation_time=FIXTURE_TIMESTAMP_V1,
                validity_time=FIXTURE_TIMESTAMP_V1,
            )
            entity_repo.save(entity, prov)

        remember = RememberRelationService(
            relation_repo=relation_repo,
            entity_repo=entity_repo,
            profile=profile,
        )
        remember.remember(
            space=SPACE,
            relation_id=REL_V1_ID,
            source_entity_id=ENTITY_A_ID,
            target_entity_id=ENTITY_B_ID,
            relation_type="depends-on",
            statement=STATEMENT_V1,
            source_id=SOURCE_ID,
            at=FIXTURE_TIMESTAMP_V1,
        )

        return relation_repo

    def test_correct_relation_statement(self) -> None:
        from memorable.core.application import CorrectService

        repo = self._setup()
        service = CorrectService(repository=repo)

        correction_time = datetime(2026, 5, 26, 10, 0, 0, tzinfo=UTC)
        result = service.correct(
            space=SPACE,
            record_id=REL_V1_ID,
            new_statement="auth-module depends on token-service for session management",
            record_kind="relation",
            source="source:human-review",
            writer="human:reviewer",
            at=correction_time,
            reason="wrong description",
        )

        assert result.record_id == REL_V1_ID
        assert result.old_statement == STATEMENT_V1
        assert (
            result.new_statement
            == "auth-module depends on token-service for session management"
        )

        stored = repo.get(space=SPACE, record_id=REL_V1_ID)
        assert stored is not None
        assert (
            stored.statement
            == "auth-module depends on token-service for session management"
        )

    def test_correct_relation_replaces_provenance(self) -> None:
        from memorable.core.application import CorrectService

        repo = self._setup()
        service = CorrectService(repository=repo)

        correction_time = datetime(2026, 5, 26, 10, 0, 0, tzinfo=UTC)
        service.correct(
            space=SPACE,
            record_id=REL_V1_ID,
            new_statement="corrected statement",
            record_kind="relation",
            source="source:human-review",
            writer="human:reviewer",
            at=correction_time,
            reason="typo fix",
        )

        provenance = repo.get_provenance(space=SPACE, record_id=REL_V1_ID)
        assert provenance is not None
        assert provenance.record_kind == "relation"
        assert provenance.source_id == "source:human-review"
        assert provenance.writer == "human:reviewer"
        assert "Corrected from:" in provenance.reason
        assert "typo fix" in provenance.reason

    def test_correct_rejects_invalidated_relation(self) -> None:
        from memorable.core.application import CorrectService, InvalidateService

        repo = self._setup()

        invalidation_time = datetime(2026, 5, 26, 10, 0, 0, tzinfo=UTC)
        InvalidateService(repository=repo).invalidate(
            space=SPACE,
            record_id=REL_V1_ID,
            at=invalidation_time,
        )

        service = CorrectService(repository=repo)
        with pytest.raises(ValueError, match="invalidated"):
            service.correct(
                space=SPACE,
                record_id=REL_V1_ID,
                new_statement="anything",
                record_kind="relation",
                source="source:human-review",
                writer="human:reviewer",
                at=invalidation_time,
            )


class TestRelationRepositoryProtocolDefinition:
    """RelationRepository protocol is defined in ports.py."""

    def test_relation_repository_protocol_exists(self) -> None:
        from memorable.core.ports import RelationRepository

        protocol_methods = {
            name for name in dir(RelationRepository) if not name.startswith("_")
        }
        assert "save" in protocol_methods
        assert "get" in protocol_methods
        assert "get_provenance" in protocol_methods
        assert "list_by_space" in protocol_methods
        assert "mark_superseded" in protocol_methods
        assert "list_by_entity" in protocol_methods
