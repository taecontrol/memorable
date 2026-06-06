"""Tests for Neo4j adapters.

Unit tests use a fake driver to verify adapter logic without Neo4j.
Integration tests (marked with @pytest.mark.integration) need a running Neo4j.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from memorable.core.models import Decision, Entity, Provenance, Relation, Task

# --- Fake driver for unit tests ---


class FakeNeo4jDate:
    """Fake storage-native date returned by the Neo4j driver."""

    def __init__(self, value: date) -> None:
        self._value = value

    def to_native(self) -> date:
        return self._value


class FakeResult:
    def __init__(self, records: list[dict] | None = None) -> None:
        self._records = records or []

    def single(self) -> dict | None:
        return self._records[0] if self._records else None

    def __iter__(self):
        return iter(self._records)


class FakeSession:
    """Simulates Neo4j session with in-memory node storage.

    Supports the Cypher patterns used by MemorySpace, Entity, Decision,
    Task, and Provenance adapters.
    """

    def __init__(self, store: dict) -> None:
        self._store = store

    def __enter__(self) -> FakeSession:
        return self

    def __exit__(self, *args: object) -> None:
        pass

    def run(self, query: str, **params: object) -> FakeResult:
        # --- MemorySpace queries ---
        if "MemorySpace" in query and "CREATE" in query:
            name = params.get("name", "")
            spaces = self._store.setdefault("MemorySpace", {})
            spaces[str(name)] = {"name": name}
            return FakeResult([{"name": name}])
        if "MemorySpace" in query and "MATCH" in query:
            name = params.get("name", "")
            spaces = self._store.get("MemorySpace", {})
            space = spaces.get(str(name))
            if space:
                return FakeResult([space])
            return FakeResult()

        # --- Constraint queries (idempotent, just succeed) ---
        if "CREATE CONSTRAINT" in query:
            return FakeResult()

        # --- Provenance retrieval (must be checked BEFORE record MATCH) ---
        # Exclude SET queries (save_provenance writes) and CREATE queries
        # (record save with embedded provenance creation).
        if (
            "Provenance" in query
            and "MATCH" in query
            and "SET" not in query
            and "CREATE" not in query
        ):
            space = str(params.get("space", ""))
            record_id = str(params.get("id", ""))
            provs = self._store.get("Provenance", {})
            if "Entity" in query:
                prov = provs.get(("entity", space, record_id))
            elif "Decision" in query:
                prov = provs.get(("decision", space, record_id))
            elif "Task" in query:
                prov = provs.get(("task", space, record_id))
            elif "Relation" in query:
                prov = provs.get(("relation", space, record_id))
            else:
                prov = None
            if prov:
                return FakeResult([prov])
            return FakeResult()

        # --- Entity MERGE ---
        if "Entity" in query and "MERGE" in query:
            entities = self._store.setdefault("Entity", {})
            space = str(params.get("space", ""))
            entity_id = str(params.get("id", ""))
            key = (space, entity_id)
            attribute_prefix = str(params.get("attribute_prefix", "attr__"))
            attribute_properties = {
                key: _fake_storage_attribute_value(value)
                for key, value in dict(
                    params.get("attribute_properties", {})
                ).items()
            }
            existing = dict(entities.get(key, {}))
            for existing_key in list(existing):
                if existing_key.startswith(attribute_prefix):
                    existing.pop(existing_key)
            existing.update(attribute_properties)
            entities[key] = {
                **existing,
                "id": entity_id,
                "entity_type": params.get("entity_type", ""),
                "name": params.get("name", ""),
                "space": space,
            }
            # Also store provenance if present
            if "record_id" in params:
                provs = self._store.setdefault("Provenance", {})
                provs[("entity", space, entity_id)] = {
                    "record_id": params.get("record_id", ""),
                    "record_kind": params.get("record_kind", ""),
                    "source_id": params.get("source_id", ""),
                    "episode_id": params.get("episode_id", ""),
                    "writer": params.get("writer", ""),
                    "reason": params.get("reason", ""),
                    "creation_time": params.get("creation_time", ""),
                    "validity_time": params.get("validity_time", ""),
                }
            return FakeResult()

        # --- Entity MATCH (single or list) ---
        # Exclude queries that also contain Relation (e.g. Relation save
        # does MATCH Entity ... CREATE Relation).
        if "Entity" in query and "MATCH" in query and "Relation" not in query:
            space = str(params.get("space", ""))
            if "id" not in params:
                entities = self._store.get("Entity", {})
                results = [
                    {**e, "entity_properties": dict(e)}
                    for (s, _), e in entities.items()
                    if s == space
                ]
                return FakeResult(results)
            entity_id = str(params["id"])
            entities = self._store.get("Entity", {})
            entity = entities.get((space, entity_id))
            if entity:
                return FakeResult([{**entity, "entity_properties": dict(entity)}])
            return FakeResult()

        # --- Decision CREATE ---
        if "Decision" in query and "CREATE" in query:
            decisions = self._store.setdefault("Decision", {})
            space = str(params.get("space", ""))
            decision_id = str(params.get("id", ""))
            key = (space, decision_id)
            decisions[key] = {
                "id": decision_id,
                "statement": params.get("statement", ""),
                "space": space,
                "validity_time": params.get("validity_time", ""),
                "invalidation_time": params.get("invalidation_time"),
                "lifecycle_state": params.get("lifecycle_state", ""),
                "supersedes": params.get("supersedes"),
                "superseded_by": params.get("superseded_by"),
                "record_type": params.get("record_type"),
            }
            if "record_id" in params:
                provs = self._store.setdefault("Provenance", {})
                provs[("decision", space, decision_id)] = {
                    "record_id": params.get("record_id", ""),
                    "record_kind": params.get("record_kind", ""),
                    "source_id": params.get("source_id", ""),
                    "episode_id": params.get("episode_id", ""),
                    "writer": params.get("writer", ""),
                    "reason": params.get("reason", ""),
                    "creation_time": params.get("creation_time", ""),
                    "validity_time": params.get("prov_validity_time", ""),
                }
            return FakeResult()

        # --- Decision save_provenance (Provenance + Decision + SET) ---
        if "Provenance" in query and "Decision" in query and "SET" in query:
            space = str(params.get("space", ""))
            record_id = str(params.get("id", ""))
            provs = self._store.setdefault("Provenance", {})
            provs[("decision", space, record_id)] = {
                "record_id": params.get("record_id", ""),
                "record_kind": params.get("record_kind", ""),
                "source_id": params.get("source_id", ""),
                "episode_id": params.get("episode_id", ""),
                "writer": params.get("writer", ""),
                "reason": params.get("reason", ""),
                "creation_time": params.get("creation_time", ""),
                "validity_time": params.get("validity_time", ""),
            }
            return FakeResult()

        # --- Decision MATCH + SET (mark_superseded, invalidate, correct) ---
        if "Decision" in query and "SET" in query:
            space = str(params.get("space", ""))
            decision_id = str(params.get("id", ""))
            decisions = self._store.get("Decision", {})
            key = (space, decision_id)
            if key in decisions:
                if "superseded_by" in params:
                    decisions[key]["superseded_by"] = params.get("superseded_by")
                if "invalidation_time" in params:
                    decisions[key]["invalidation_time"] = params.get(
                        "invalidation_time"
                    )
                if "lifecycle_state" in params:
                    decisions[key]["lifecycle_state"] = params.get("lifecycle_state")
                if "statement" in params:
                    decisions[key]["statement"] = params.get("statement")
            return FakeResult()

        # --- Decision MATCH (single or list) ---
        if "Decision" in query and "MATCH" in query:
            space = str(params.get("space", ""))
            if "id" not in params:
                decisions = self._store.get("Decision", {})
                results = [d for (s, _), d in decisions.items() if s == space]
                return FakeResult(results)
            decision_id = str(params["id"])
            decisions = self._store.get("Decision", {})
            decision = decisions.get((space, decision_id))
            if decision:
                return FakeResult([decision])
            return FakeResult()

        # --- Task CREATE ---
        if "Task" in query and "CREATE" in query:
            tasks = self._store.setdefault("Task", {})
            space = str(params.get("space", ""))
            task_id = str(params.get("id", ""))
            key = (space, task_id)
            tasks[key] = {
                "id": task_id,
                "title": params.get("title", ""),
                "space": space,
                "lifecycle_state": params.get("lifecycle_state", ""),
                "validity_time": params.get("validity_time", ""),
                "completion_time": params.get("completion_time"),
                "completion_event_id": params.get("completion_event_id"),
                "record_type": params.get("record_type"),
            }
            if "record_id" in params:
                provs = self._store.setdefault("Provenance", {})
                provs[("task", space, task_id)] = {
                    "record_id": params.get("record_id", ""),
                    "record_kind": params.get("record_kind", ""),
                    "source_id": params.get("source_id", ""),
                    "episode_id": params.get("episode_id", ""),
                    "writer": params.get("writer", ""),
                    "reason": params.get("reason", ""),
                    "creation_time": params.get("creation_time", ""),
                    "validity_time": params.get("prov_validity_time", ""),
                }
            return FakeResult()

        # --- Task save_provenance (Provenance + Task + SET) ---
        if "Provenance" in query and "Task" in query and "SET" in query:
            space = str(params.get("space", ""))
            task_id = str(params.get("id", ""))
            provs = self._store.setdefault("Provenance", {})
            provs[("task", space, task_id)] = {
                "record_id": params.get("record_id", ""),
                "record_kind": params.get("record_kind", ""),
                "source_id": params.get("source_id", ""),
                "episode_id": params.get("episode_id", ""),
                "writer": params.get("writer", ""),
                "reason": params.get("reason", ""),
                "creation_time": params.get("creation_time", ""),
                "validity_time": params.get("validity_time", ""),
            }
            return FakeResult()

        # --- Task complete (MATCH + SET) ---
        if "Task" in query and "SET" in query:
            space = str(params.get("space", ""))
            task_id = str(params.get("id", ""))
            tasks = self._store.get("Task", {})
            key = (space, task_id)
            if key in tasks:
                tasks[key]["lifecycle_state"] = params.get(
                    "lifecycle_state", "completed"
                )
                tasks[key]["completion_time"] = params.get("completion_time")
                tasks[key]["completion_event_id"] = params.get("completion_event_id")
            return FakeResult()

        # --- Task MATCH (single or list) ---
        if "Task" in query and "MATCH" in query:
            space = str(params.get("space", ""))
            if "id" not in params:
                tasks = self._store.get("Task", {})
                results = [t for (s, _), t in tasks.items() if s == space]
                return FakeResult(results)
            task_id = str(params["id"])
            tasks = self._store.get("Task", {})
            task = tasks.get((space, task_id))
            if task:
                return FakeResult([task])
            return FakeResult()

        # --- Relation CREATE ---
        if "Relation" in query and "CREATE" in query and "Provenance" in query:
            relations = self._store.setdefault("Relation", {})
            space = str(params.get("space", ""))
            relation_id = str(params.get("id", ""))
            key = (space, relation_id)
            relations[key] = {
                "id": relation_id,
                "source_entity_id": params.get("source_entity_id", ""),
                "target_entity_id": params.get("target_entity_id", ""),
                "relation_type": params.get("relation_type", ""),
                "statement": params.get("statement", ""),
                "space": space,
                "validity_time": params.get("validity_time", ""),
                "invalidation_time": params.get("invalidation_time"),
                "lifecycle_state": params.get("lifecycle_state", ""),
                "supersedes": params.get("supersedes"),
                "superseded_by": params.get("superseded_by"),
            }
            if "record_id" in params:
                provs = self._store.setdefault("Provenance", {})
                provs[("relation", space, relation_id)] = {
                    "record_id": params.get("record_id", ""),
                    "record_kind": params.get("record_kind", ""),
                    "source_id": params.get("source_id", ""),
                    "episode_id": params.get("episode_id", ""),
                    "writer": params.get("writer", ""),
                    "reason": params.get("reason", ""),
                    "creation_time": params.get("creation_time", ""),
                    "validity_time": params.get("prov_validity_time", ""),
                }
            return FakeResult()

        # --- Relation save_provenance (Provenance + Relation + SET) ---
        if "Provenance" in query and "Relation" in query and "SET" in query:
            space = str(params.get("space", ""))
            record_id = str(params.get("id", ""))
            provs = self._store.setdefault("Provenance", {})
            provs[("relation", space, record_id)] = {
                "record_id": params.get("record_id", ""),
                "record_kind": params.get("record_kind", ""),
                "source_id": params.get("source_id", ""),
                "episode_id": params.get("episode_id", ""),
                "writer": params.get("writer", ""),
                "reason": params.get("reason", ""),
                "creation_time": params.get("creation_time", ""),
                "validity_time": params.get("validity_time", ""),
            }
            return FakeResult()

        # --- Relation MATCH + SET (mark_superseded, invalidate, correct) ---
        if "Relation" in query and "SET" in query:
            space = str(params.get("space", ""))
            relation_id = str(params.get("id", ""))
            relations = self._store.get("Relation", {})
            key = (space, relation_id)
            if key in relations:
                if "superseded_by" in params:
                    relations[key]["superseded_by"] = params.get("superseded_by")
                if "invalidation_time" in params:
                    relations[key]["invalidation_time"] = params.get(
                        "invalidation_time"
                    )
                if "lifecycle_state" in params:
                    relations[key]["lifecycle_state"] = params.get("lifecycle_state")
                if "statement" in params:
                    relations[key]["statement"] = params.get("statement")
            return FakeResult()

        # --- Relation list_by_entity (graph traversal via FROM|TO) ---
        if "Relation" in query and "FROM|TO" in query:
            space = str(params.get("space", ""))
            entity_id = str(params.get("entity_id", ""))
            relations = self._store.get("Relation", {})
            results = [
                r
                for (s, _), r in relations.items()
                if s == space
                and (
                    r["source_entity_id"] == entity_id
                    or r["target_entity_id"] == entity_id
                )
            ]
            return FakeResult(results)

        # --- Relation MATCH (single or list) ---
        if "Relation" in query and "MATCH" in query:
            space = str(params.get("space", ""))
            if "id" not in params:
                relations = self._store.get("Relation", {})
                results = [r for (s, _), r in relations.items() if s == space]
                return FakeResult(results)
            relation_id = str(params["id"])
            relations = self._store.get("Relation", {})
            relation = relations.get((space, relation_id))
            if relation:
                return FakeResult([relation])
            return FakeResult()

        return FakeResult()


def _fake_storage_attribute_value(value: object) -> object:
    if type(value) is date:
        return FakeNeo4jDate(value)
    if isinstance(value, list):
        return list(value)
    return value


class FakeDriver:
    def __init__(self) -> None:
        self._store: dict = {}
        self._session = FakeSession(self._store)

    def session(self, **kwargs: object) -> FakeSession:
        return self._session


# --- Fixtures ---


def _make_provenance(
    record_id: str, record_kind: str, ts: datetime | None = None
) -> Provenance:
    """Create a test Provenance instance."""
    ts = ts or datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC)
    return Provenance(
        record_id=record_id,
        record_kind=record_kind,
        source_id="src-1",
        episode_id="ep-1",
        writer="test-agent",
        reason="test reason",
        creation_time=ts,
        validity_time=ts,
    )


# --- Datetime serialization tests ---


def test_datetime_serialization_is_utc_fixed_width_and_sortable() -> None:
    """Stored datetimes sort as strings the same way they sort as instants."""
    from memorable.storage.neo4j.repository import _from_iso, _to_iso

    timestamps = [
        datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC),
        datetime(2025, 1, 1, 0, 0, 0, 1, tzinfo=UTC),
        datetime(2025, 1, 1, 1, 0, 0, 250000, tzinfo=timezone(timedelta(hours=1))),
        datetime(2024, 12, 31, 19, 0, 0, 500000, tzinfo=timezone(timedelta(hours=-5))),
        datetime(2025, 1, 1, 0, 0, 1, tzinfo=UTC),
    ]

    serialized = [_to_iso(timestamp) for timestamp in timestamps]

    assert serialized == [
        "2025-01-01T00:00:00.000000+00:00",
        "2025-01-01T00:00:00.000001+00:00",
        "2025-01-01T00:00:00.250000+00:00",
        "2025-01-01T00:00:00.500000+00:00",
        "2025-01-01T00:00:01.000000+00:00",
    ]
    assert sorted(serialized) == [
        _to_iso(timestamp) for timestamp in sorted(timestamps)
    ]
    for timestamp in timestamps:
        assert _from_iso(_to_iso(timestamp)) == timestamp


# --- MemorySpace adapter tests ---


def test_adapter_implements_repository_port() -> None:
    """Neo4jMemorySpaceRepository must satisfy the MemorySpaceRepository protocol."""
    from memorable.storage.neo4j.repository import Neo4jMemorySpaceRepository

    assert hasattr(Neo4jMemorySpaceRepository, "create_space")
    assert hasattr(Neo4jMemorySpaceRepository, "get_space")
    assert hasattr(Neo4jMemorySpaceRepository, "exists")


def test_adapter_create_space_returns_memory_space() -> None:
    """create_space must return a MemorySpace domain object."""
    from memorable.core.models import MemorySpace
    from memorable.storage.neo4j.repository import Neo4jMemorySpaceRepository

    repo = Neo4jMemorySpaceRepository(driver=FakeDriver())
    space = repo.create_space("test-project")

    assert isinstance(space, MemorySpace)
    assert space.name == "test-project"


def test_adapter_get_space_returns_none_when_missing() -> None:
    """get_space must return None for a non-existent MemorySpace."""
    from memorable.storage.neo4j.repository import Neo4jMemorySpaceRepository

    repo = Neo4jMemorySpaceRepository(driver=FakeDriver())
    assert repo.get_space("nonexistent") is None


def test_adapter_exists_reflects_created_spaces() -> None:
    """exists must return True after create_space and False before."""
    from memorable.storage.neo4j.repository import Neo4jMemorySpaceRepository

    repo = Neo4jMemorySpaceRepository(driver=FakeDriver())
    assert not repo.exists("my-project")
    repo.create_space("my-project")
    assert repo.exists("my-project")


def test_adapter_does_not_expose_storage_vocabulary() -> None:
    """The adapter's public interface must not use Node, Edge, label, or Cypher."""
    import inspect

    from memorable.storage.neo4j.repository import Neo4jMemorySpaceRepository

    public_methods = [
        name for name in dir(Neo4jMemorySpaceRepository) if not name.startswith("_")
    ]
    storage_terms = {"node", "edge", "label", "relationship", "cypher"}
    for method_name in public_methods:
        assert method_name.lower() not in storage_terms, (
            f"Public method '{method_name}' uses storage vocabulary"
        )

    for method_name in public_methods:
        method = getattr(Neo4jMemorySpaceRepository, method_name)
        if callable(method):
            sig = inspect.signature(method)
            for param_name in sig.parameters:
                if param_name == "self":
                    continue
                for term in storage_terms:
                    assert term not in param_name.lower(), (
                        f"Parameter '{param_name}' in "
                        f"'{method_name}' uses storage vocabulary"
                    )


def test_adapter_create_duplicate_raises() -> None:
    """Creating a MemorySpace that already exists should raise ValueError."""
    from memorable.storage.neo4j.repository import Neo4jMemorySpaceRepository

    repo = Neo4jMemorySpaceRepository(driver=FakeDriver())
    repo.create_space("dup")
    with pytest.raises(ValueError, match="already exists"):
        repo.create_space("dup")


# --- Entity adapter tests ---


class TestNeo4jEntityRepository:
    """Unit tests for Neo4jEntityRepository."""

    def test_implements_entity_repository_protocol(self) -> None:
        """Neo4jEntityRepository must have all EntityRepository methods."""
        from memorable.storage.neo4j.repository import Neo4jEntityRepository

        assert hasattr(Neo4jEntityRepository, "save")
        assert hasattr(Neo4jEntityRepository, "get")
        assert hasattr(Neo4jEntityRepository, "get_provenance")
        assert hasattr(Neo4jEntityRepository, "list_by_space")

    def test_save_and_get_roundtrip(self) -> None:
        """save then get returns the same Entity."""
        from memorable.storage.neo4j.repository import Neo4jEntityRepository

        repo = Neo4jEntityRepository(driver=FakeDriver())
        entity = Entity(
            id="ent-1", entity_type="component", name="Auth Service", space="proj-a"
        )
        provenance = _make_provenance("ent-1", "entity")

        repo.save(entity, provenance)
        result = repo.get("proj-a", "ent-1")

        assert result is not None
        assert result.id == "ent-1"
        assert result.entity_type == "component"
        assert result.name == "Auth Service"
        assert result.space == "proj-a"

    def test_save_and_get_roundtrip_preserves_entity_attributes(self) -> None:
        """save then get returns an Entity's durable Attributes."""
        from memorable.storage.neo4j.repository import Neo4jEntityRepository

        repo = Neo4jEntityRepository(driver=FakeDriver())
        entity = Entity(
            id="ent-1",
            entity_type="reference",
            name="Example Reference",
            space="proj-a",
            attributes={"url": "https://example.test", "medium": "video"},
        )
        provenance = _make_provenance("ent-1", "entity")

        repo.save(entity, provenance)
        result = repo.get("proj-a", "ent-1")

        assert result is not None
        assert result.attributes == {
            "url": "https://example.test",
            "medium": "video",
        }

    def test_save_and_get_roundtrip_preserves_typed_entity_attributes(self) -> None:
        """save then get returns number, date, and list[string] Attributes."""
        from memorable.storage.neo4j.repository import Neo4jEntityRepository

        repo = Neo4jEntityRepository(driver=FakeDriver())
        entity = Entity(
            id="ent-1",
            entity_type="reference",
            name="Example Reference",
            space="proj-a",
            attributes={
                "rating": 5,
                "published_on": date(2026, 6, 6),
                "aliases": [],
            },
        )
        provenance = _make_provenance("ent-1", "entity")

        repo.save(entity, provenance)
        result = repo.get("proj-a", "ent-1")

        assert result is not None
        assert result.attributes == {
            "rating": 5,
            "published_on": date(2026, 6, 6),
            "aliases": [],
        }

    def test_get_returns_none_for_missing(self) -> None:
        """get returns None when entity does not exist."""
        from memorable.storage.neo4j.repository import Neo4jEntityRepository

        repo = Neo4jEntityRepository(driver=FakeDriver())
        assert repo.get("proj-a", "nonexistent") is None

    def test_list_by_space_returns_entities_in_space(self) -> None:
        """list_by_space returns only entities in the given space."""
        from memorable.storage.neo4j.repository import Neo4jEntityRepository

        repo = Neo4jEntityRepository(driver=FakeDriver())
        e1 = Entity(id="e1", entity_type="api", name="Users API", space="proj-a")
        e2 = Entity(id="e2", entity_type="api", name="Orders API", space="proj-a")
        e3 = Entity(id="e3", entity_type="api", name="Other", space="proj-b")

        repo.save(e1, _make_provenance("e1", "entity"))
        repo.save(e2, _make_provenance("e2", "entity"))
        repo.save(e3, _make_provenance("e3", "entity"))

        results = repo.list_by_space("proj-a")
        assert len(results) == 2
        ids = {e.id for e in results}
        assert ids == {"e1", "e2"}

    def test_list_by_space_returns_empty_for_unknown_space(self) -> None:
        """list_by_space returns empty list for a space with no entities."""
        from memorable.storage.neo4j.repository import Neo4jEntityRepository

        repo = Neo4jEntityRepository(driver=FakeDriver())
        assert repo.list_by_space("empty-space") == []

    def test_get_provenance_returns_provenance_after_save(self) -> None:
        """get_provenance returns the provenance stored with the entity."""
        from memorable.storage.neo4j.repository import Neo4jEntityRepository

        repo = Neo4jEntityRepository(driver=FakeDriver())
        entity = Entity(
            id="ent-1", entity_type="component", name="Auth", space="proj-a"
        )
        ts = datetime(2025, 3, 1, 12, 0, 0, tzinfo=UTC)
        provenance = Provenance(
            record_id="ent-1",
            record_kind="entity",
            source_id="src-42",
            episode_id="ep-7",
            writer="agent-x",
            reason="discovered in codebase",
            creation_time=ts,
            validity_time=ts,
        )

        repo.save(entity, provenance)
        result = repo.get_provenance("proj-a", "ent-1")

        assert result is not None
        assert result.record_id == "ent-1"
        assert result.record_kind == "entity"
        assert result.source_id == "src-42"
        assert result.episode_id == "ep-7"
        assert result.writer == "agent-x"
        assert result.reason == "discovered in codebase"

    def test_get_provenance_returns_none_for_missing(self) -> None:
        """get_provenance returns None when entity has no provenance."""
        from memorable.storage.neo4j.repository import Neo4jEntityRepository

        repo = Neo4jEntityRepository(driver=FakeDriver())
        assert repo.get_provenance("proj-a", "nonexistent") is None

    def test_save_is_idempotent_upsert(self) -> None:
        """Saving the same entity twice updates rather than duplicates."""
        from memorable.storage.neo4j.repository import Neo4jEntityRepository

        repo = Neo4jEntityRepository(driver=FakeDriver())
        entity_v1 = Entity(
            id="ent-1", entity_type="component", name="Auth v1", space="proj-a"
        )
        entity_v2 = Entity(
            id="ent-1", entity_type="component", name="Auth v2", space="proj-a"
        )

        repo.save(entity_v1, _make_provenance("ent-1", "entity"))
        repo.save(entity_v2, _make_provenance("ent-1", "entity"))

        result = repo.get("proj-a", "ent-1")
        assert result is not None
        assert result.name == "Auth v2"

        # list should still only have one
        results = repo.list_by_space("proj-a")
        assert len(results) == 1

    def test_resave_updates_provenance_not_accumulates(self) -> None:
        """Re-saving an entity overwrites provenance instead of accumulating."""
        from memorable.storage.neo4j.repository import Neo4jEntityRepository

        repo = Neo4jEntityRepository(driver=FakeDriver())
        entity = Entity(
            id="ent-1", entity_type="component", name="Auth", space="proj-a"
        )
        ts1 = datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC)
        prov_a = Provenance(
            record_id="rec-a",
            record_kind="entity",
            source_id="src-old",
            episode_id="ep-old",
            writer="agent-old",
            reason="initial discovery",
            creation_time=ts1,
            validity_time=ts1,
        )

        repo.save(entity, prov_a)

        # Re-save with different provenance
        ts2 = datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)
        prov_b = Provenance(
            record_id="rec-b",
            record_kind="entity",
            source_id="src-new",
            episode_id="ep-new",
            writer="agent-new",
            reason="updated observation",
            creation_time=ts2,
            validity_time=ts2,
        )

        repo.save(entity, prov_b)

        # get_provenance should return prov_b (the latest), not prov_a
        result = repo.get_provenance("proj-a", "ent-1")
        assert result is not None
        assert result.record_id == "rec-b"
        assert result.source_id == "src-new"
        assert result.writer == "agent-new"
        assert result.reason == "updated observation"


# --- Decision adapter tests ---


class TestNeo4jDecisionRepository:
    """Unit tests for Neo4jDecisionRepository."""

    def test_implements_decision_repository_protocol(self) -> None:
        """Neo4jDecisionRepository must have all DecisionRepository methods."""
        from memorable.storage.neo4j.repository import Neo4jDecisionRepository

        assert hasattr(Neo4jDecisionRepository, "save")
        assert hasattr(Neo4jDecisionRepository, "get")
        assert hasattr(Neo4jDecisionRepository, "get_provenance")
        assert hasattr(Neo4jDecisionRepository, "list_by_space")
        assert hasattr(Neo4jDecisionRepository, "list_projections_by_space")
        assert hasattr(Neo4jDecisionRepository, "mark_superseded")

    def test_save_and_get_roundtrip(self) -> None:
        """save then get returns the same Decision."""
        from memorable.storage.neo4j.repository import Neo4jDecisionRepository

        repo = Neo4jDecisionRepository(driver=FakeDriver())
        ts = datetime(2025, 2, 1, 9, 0, 0, tzinfo=UTC)
        decision = Decision(
            id="dec-1",
            statement="Use PostgreSQL for metadata",
            space="proj-a",
            validity_time=ts,
            invalidation_time=None,
            lifecycle_state="active",
            supersedes=None,
            superseded_by=None,
            record_type="ArchitectureDecision",
        )
        provenance = _make_provenance("dec-1", "decision")

        repo.save(decision, provenance)
        result = repo.get("proj-a", "dec-1")

        assert result is not None
        assert result.id == "dec-1"
        assert result.statement == "Use PostgreSQL for metadata"
        assert result.space == "proj-a"
        assert result.lifecycle_state == "active"
        assert result.invalidation_time is None
        assert result.supersedes is None
        assert result.superseded_by is None
        assert result.record_type == "ArchitectureDecision"

    def test_get_returns_none_for_missing(self) -> None:
        """get returns None when decision does not exist."""
        from memorable.storage.neo4j.repository import Neo4jDecisionRepository

        repo = Neo4jDecisionRepository(driver=FakeDriver())
        assert repo.get("proj-a", "nonexistent") is None

    def test_list_by_space_returns_decisions_in_space(self) -> None:
        """list_by_space returns only decisions in the given space."""
        from memorable.storage.neo4j.repository import Neo4jDecisionRepository

        repo = Neo4jDecisionRepository(driver=FakeDriver())
        ts = datetime(2025, 2, 1, 9, 0, 0, tzinfo=UTC)

        d1 = Decision(
            id="d1",
            statement="Use Neo4j",
            space="proj-a",
            validity_time=ts,
            invalidation_time=None,
            lifecycle_state="active",
            supersedes=None,
            superseded_by=None,
        )
        d2 = Decision(
            id="d2",
            statement="Use REST",
            space="proj-a",
            validity_time=ts,
            invalidation_time=None,
            lifecycle_state="active",
            supersedes=None,
            superseded_by=None,
        )
        d3 = Decision(
            id="d3",
            statement="Use GraphQL",
            space="proj-b",
            validity_time=ts,
            invalidation_time=None,
            lifecycle_state="active",
            supersedes=None,
            superseded_by=None,
        )

        repo.save(d1, _make_provenance("d1", "decision"))
        repo.save(d2, _make_provenance("d2", "decision"))
        repo.save(d3, _make_provenance("d3", "decision"))

        results = repo.list_by_space("proj-a")
        assert len(results) == 2
        ids = {d.id for d in results}
        assert ids == {"d1", "d2"}

    def test_mark_superseded_updates_fields(self) -> None:
        """mark_superseded sets superseded_by, invalidation_time, lifecycle_state."""
        from memorable.storage.neo4j.repository import Neo4jDecisionRepository

        repo = Neo4jDecisionRepository(driver=FakeDriver())
        ts = datetime(2025, 2, 1, 9, 0, 0, tzinfo=UTC)
        inv_time = datetime(2025, 3, 1, 12, 0, 0, tzinfo=UTC)

        decision = Decision(
            id="dec-1",
            statement="Use MySQL",
            space="proj-a",
            validity_time=ts,
            invalidation_time=None,
            lifecycle_state="active",
            supersedes=None,
            superseded_by=None,
        )
        repo.save(decision, _make_provenance("dec-1", "decision"))

        repo.mark_superseded("proj-a", "dec-1", "dec-2", inv_time)

        result = repo.get("proj-a", "dec-1")
        assert result is not None
        assert result.superseded_by == "dec-2"
        assert result.invalidation_time == inv_time
        assert result.lifecycle_state == "superseded"

    def test_get_provenance_returns_provenance_after_save(self) -> None:
        """get_provenance returns the provenance stored with the decision."""
        from memorable.storage.neo4j.repository import Neo4jDecisionRepository

        repo = Neo4jDecisionRepository(driver=FakeDriver())
        ts = datetime(2025, 2, 1, 9, 0, 0, tzinfo=UTC)
        decision = Decision(
            id="dec-1",
            statement="Use Neo4j",
            space="proj-a",
            validity_time=ts,
            invalidation_time=None,
            lifecycle_state="active",
            supersedes=None,
            superseded_by=None,
        )
        provenance = Provenance(
            record_id="dec-1",
            record_kind="decision",
            source_id="src-10",
            episode_id="ep-5",
            writer="agent-y",
            reason="ADR discussion",
            creation_time=ts,
            validity_time=ts,
        )

        repo.save(decision, provenance)
        result = repo.get_provenance("proj-a", "dec-1")

        assert result is not None
        assert result.record_id == "dec-1"
        assert result.record_kind == "decision"
        assert result.source_id == "src-10"
        assert result.writer == "agent-y"

    def test_get_provenance_returns_none_for_missing(self) -> None:
        """get_provenance returns None when decision has no provenance."""
        from memorable.storage.neo4j.repository import Neo4jDecisionRepository

        repo = Neo4jDecisionRepository(driver=FakeDriver())
        assert repo.get_provenance("proj-a", "nonexistent") is None

    def test_invalidate_sets_lifecycle_and_time(self) -> None:
        """invalidate sets lifecycle_state to invalidated and records time."""
        from memorable.storage.neo4j.repository import Neo4jDecisionRepository

        repo = Neo4jDecisionRepository(driver=FakeDriver())
        ts = datetime(2025, 2, 1, 9, 0, 0, tzinfo=UTC)
        inv_time = datetime(2025, 3, 1, 12, 0, 0, tzinfo=UTC)

        decision = Decision(
            id="dec-1",
            statement="Use MySQL",
            space="proj-a",
            validity_time=ts,
            invalidation_time=None,
            lifecycle_state="current",
            supersedes=None,
            superseded_by=None,
        )
        repo.save(decision, _make_provenance("dec-1", "decision"))

        repo.invalidate("proj-a", "dec-1", inv_time)

        result = repo.get("proj-a", "dec-1")
        assert result is not None
        assert result.lifecycle_state == "invalidated"
        assert result.invalidation_time == inv_time

    def test_correct_updates_statement_in_place(self) -> None:
        """correct updates the statement without changing other fields."""
        from memorable.storage.neo4j.repository import Neo4jDecisionRepository

        repo = Neo4jDecisionRepository(driver=FakeDriver())
        ts = datetime(2025, 2, 1, 9, 0, 0, tzinfo=UTC)

        decision = Decision(
            id="dec-1",
            statement="Use Graphiti for storage.",
            space="proj-a",
            validity_time=ts,
            invalidation_time=None,
            lifecycle_state="current",
            supersedes=None,
            superseded_by=None,
        )
        repo.save(decision, _make_provenance("dec-1", "decision"))

        repo.correct("proj-a", "dec-1", "Use Neo4j for storage.")

        result = repo.get("proj-a", "dec-1")
        assert result is not None
        assert result.statement == "Use Neo4j for storage."
        assert result.lifecycle_state == "current"
        assert result.invalidation_time is None

    def test_save_provenance_replaces_existing(self) -> None:
        """save_provenance replaces the provenance for a decision."""
        from memorable.storage.neo4j.repository import Neo4jDecisionRepository

        repo = Neo4jDecisionRepository(driver=FakeDriver())
        ts = datetime(2025, 2, 1, 9, 0, 0, tzinfo=UTC)
        correction_ts = datetime(2025, 3, 1, 12, 0, 0, tzinfo=UTC)

        decision = Decision(
            id="dec-1",
            statement="Use Neo4j",
            space="proj-a",
            validity_time=ts,
            invalidation_time=None,
            lifecycle_state="current",
            supersedes=None,
            superseded_by=None,
        )
        repo.save(decision, _make_provenance("dec-1", "decision"))

        new_prov = Provenance(
            record_id="dec-1",
            record_kind="decision",
            source_id="src-correction",
            episode_id="ep-correction",
            writer="human:reviewer",
            reason="Corrected from: 'Use Graphiti'.",
            creation_time=correction_ts,
            validity_time=correction_ts,
        )
        repo.save_provenance("proj-a", "dec-1", new_prov)

        result = repo.get_provenance("proj-a", "dec-1")
        assert result is not None
        assert result.source_id == "src-correction"
        assert result.writer == "human:reviewer"
        assert "Corrected from" in result.reason


# --- Task adapter tests ---


class TestNeo4jTaskRepository:
    """Unit tests for Neo4jTaskRepository."""

    def test_implements_task_repository_protocol(self) -> None:
        """Neo4jTaskRepository must have all TaskRepository methods."""
        from memorable.storage.neo4j.repository import Neo4jTaskRepository

        assert hasattr(Neo4jTaskRepository, "save")
        assert hasattr(Neo4jTaskRepository, "get")
        assert hasattr(Neo4jTaskRepository, "get_provenance")
        assert hasattr(Neo4jTaskRepository, "save_provenance")
        assert hasattr(Neo4jTaskRepository, "list_by_space")
        assert hasattr(Neo4jTaskRepository, "list_projections_by_space")
        assert hasattr(Neo4jTaskRepository, "complete")

    def test_save_and_get_roundtrip(self) -> None:
        """save then get returns the same Task."""
        from memorable.storage.neo4j.repository import Neo4jTaskRepository

        repo = Neo4jTaskRepository(driver=FakeDriver())
        ts = datetime(2025, 4, 1, 8, 0, 0, tzinfo=UTC)
        task = Task(
            id="task-1",
            title="Implement auth flow",
            space="proj-a",
            lifecycle_state="open",
            validity_time=ts,
            completion_time=None,
            completion_event_id=None,
            record_type="FollowUp",
        )
        provenance = _make_provenance("task-1", "task")

        repo.save(task, provenance)
        result = repo.get(space="proj-a", task_id="task-1")

        assert result is not None
        assert result.id == "task-1"
        assert result.title == "Implement auth flow"
        assert result.space == "proj-a"
        assert result.lifecycle_state == "open"
        assert result.completion_time is None
        assert result.completion_event_id is None
        assert result.record_type == "FollowUp"

    def test_get_returns_none_for_missing(self) -> None:
        """get returns None when task does not exist."""
        from memorable.storage.neo4j.repository import Neo4jTaskRepository

        repo = Neo4jTaskRepository(driver=FakeDriver())
        assert repo.get(space="proj-a", task_id="nonexistent") is None

    def test_list_by_space_returns_tasks_in_space(self) -> None:
        """list_by_space returns only tasks in the given space."""
        from memorable.storage.neo4j.repository import Neo4jTaskRepository

        repo = Neo4jTaskRepository(driver=FakeDriver())
        ts = datetime(2025, 4, 1, 8, 0, 0, tzinfo=UTC)

        t1 = Task(
            id="t1",
            title="Task A",
            space="proj-a",
            lifecycle_state="open",
            validity_time=ts,
            completion_time=None,
            completion_event_id=None,
        )
        t2 = Task(
            id="t2",
            title="Task B",
            space="proj-a",
            lifecycle_state="open",
            validity_time=ts,
            completion_time=None,
            completion_event_id=None,
        )
        t3 = Task(
            id="t3",
            title="Task C",
            space="proj-b",
            lifecycle_state="open",
            validity_time=ts,
            completion_time=None,
            completion_event_id=None,
        )

        repo.save(t1, _make_provenance("t1", "task"))
        repo.save(t2, _make_provenance("t2", "task"))
        repo.save(t3, _make_provenance("t3", "task"))

        results = repo.list_by_space("proj-a")
        assert len(results) == 2
        ids = {t.id for t in results}
        assert ids == {"t1", "t2"}

    def test_complete_updates_lifecycle(self) -> None:
        """complete sets lifecycle_state, completion_time, completion_event_id."""
        from memorable.storage.neo4j.repository import Neo4jTaskRepository

        repo = Neo4jTaskRepository(driver=FakeDriver())
        ts = datetime(2025, 4, 1, 8, 0, 0, tzinfo=UTC)
        comp_time = datetime(2025, 4, 5, 16, 0, 0, tzinfo=UTC)

        task = Task(
            id="task-1",
            title="Implement auth",
            space="proj-a",
            lifecycle_state="open",
            validity_time=ts,
            completion_time=None,
            completion_event_id=None,
        )
        repo.save(task, _make_provenance("task-1", "task"))

        repo.complete(
            space="proj-a",
            task_id="task-1",
            completion_time=comp_time,
            completion_event_id="evt-99",
        )

        result = repo.get(space="proj-a", task_id="task-1")
        assert result is not None
        assert result.lifecycle_state == "completed"
        assert result.completion_time == comp_time
        assert result.completion_event_id == "evt-99"

    def test_get_provenance_returns_provenance_after_save(self) -> None:
        """get_provenance returns the provenance stored with the task."""
        from memorable.storage.neo4j.repository import Neo4jTaskRepository

        repo = Neo4jTaskRepository(driver=FakeDriver())
        ts = datetime(2025, 4, 1, 8, 0, 0, tzinfo=UTC)
        task = Task(
            id="task-1",
            title="Do thing",
            space="proj-a",
            lifecycle_state="open",
            validity_time=ts,
            completion_time=None,
            completion_event_id=None,
        )
        provenance = Provenance(
            record_id="task-1",
            record_kind="task",
            source_id="src-20",
            episode_id="ep-3",
            writer="agent-z",
            reason="sprint planning",
            creation_time=ts,
            validity_time=ts,
        )

        repo.save(task, provenance)
        result = repo.get_provenance(space="proj-a", task_id="task-1")

        assert result is not None
        assert result.record_id == "task-1"
        assert result.record_kind == "task"
        assert result.source_id == "src-20"
        assert result.writer == "agent-z"

    def test_save_provenance_replaces_task_provenance(self) -> None:
        """save_provenance replaces provenance for an existing Task."""
        from memorable.storage.neo4j.repository import Neo4jTaskRepository

        repo = Neo4jTaskRepository(driver=FakeDriver())
        ts = datetime(2025, 4, 1, 8, 0, 0, tzinfo=UTC)
        task = Task(
            id="task-1",
            title="Do thing",
            space="proj-a",
            lifecycle_state="open",
            validity_time=ts,
            completion_time=None,
            completion_event_id=None,
        )
        repo.save(task, _make_provenance("task-1", "task"))
        replacement = Provenance(
            record_id="task-1",
            record_kind="task",
            source_id="src-correction",
            episode_id="ep-correction",
            writer="human:reviewer",
            reason="corrected About membership",
            creation_time=ts,
            validity_time=ts,
        )

        repo.save_provenance(space="proj-a", task_id="task-1", provenance=replacement)

        result = repo.get_provenance(space="proj-a", task_id="task-1")
        assert result is not None
        assert result.source_id == "src-correction"
        assert result.writer == "human:reviewer"
        assert result.reason == "corrected About membership"

    def test_get_provenance_returns_none_for_missing(self) -> None:
        """get_provenance returns None when task has no provenance."""
        from memorable.storage.neo4j.repository import Neo4jTaskRepository

        repo = Neo4jTaskRepository(driver=FakeDriver())
        assert repo.get_provenance(space="proj-a", task_id="nonexistent") is None


# --- Relation adapter tests ---


class TestNeo4jRelationRepository:
    """Unit tests for Neo4jRelationRepository."""

    def test_implements_relation_repository_protocol(self) -> None:
        """Neo4jRelationRepository must have all RelationRepository methods."""
        from memorable.storage.neo4j.repository import Neo4jRelationRepository

        assert hasattr(Neo4jRelationRepository, "save")
        assert hasattr(Neo4jRelationRepository, "get")
        assert hasattr(Neo4jRelationRepository, "get_provenance")
        assert hasattr(Neo4jRelationRepository, "list_by_space")
        assert hasattr(Neo4jRelationRepository, "list_projections_by_space")
        assert hasattr(Neo4jRelationRepository, "mark_superseded")
        assert hasattr(Neo4jRelationRepository, "list_by_entity")
        assert hasattr(Neo4jRelationRepository, "invalidate")
        assert hasattr(Neo4jRelationRepository, "correct")
        assert hasattr(Neo4jRelationRepository, "save_provenance")

    def test_save_and_get_roundtrip(self) -> None:
        """save then get returns the same Relation."""
        from memorable.storage.neo4j.repository import (
            Neo4jEntityRepository,
            Neo4jRelationRepository,
        )

        driver = FakeDriver()
        entity_repo = Neo4jEntityRepository(driver=driver)
        repo = Neo4jRelationRepository(driver=driver)
        ts = datetime(2025, 2, 1, 9, 0, 0, tzinfo=UTC)

        # Entities must exist for MATCH in save()
        entity_repo.save(
            Entity(id="ent-1", entity_type="component", name="Auth", space="proj-a"),
            _make_provenance("ent-1", "entity"),
        )
        entity_repo.save(
            Entity(id="ent-2", entity_type="component", name="DB", space="proj-a"),
            _make_provenance("ent-2", "entity"),
        )

        relation = Relation(
            id="rel-1",
            source_entity_id="ent-1",
            target_entity_id="ent-2",
            relation_type="depends-on",
            statement="Auth depends on Database",
            space="proj-a",
            validity_time=ts,
            invalidation_time=None,
            lifecycle_state="current",
            supersedes=None,
            superseded_by=None,
        )
        provenance = _make_provenance("rel-1", "relation")

        repo.save(relation, provenance)
        result = repo.get("proj-a", "rel-1")

        assert result is not None
        assert result.id == "rel-1"
        assert result.source_entity_id == "ent-1"
        assert result.target_entity_id == "ent-2"
        assert result.relation_type == "depends-on"
        assert result.statement == "Auth depends on Database"
        assert result.space == "proj-a"
        assert result.lifecycle_state == "current"
        assert result.invalidation_time is None
        assert result.supersedes is None
        assert result.superseded_by is None

    def test_get_returns_none_for_missing(self) -> None:
        """get returns None when relation does not exist."""
        from memorable.storage.neo4j.repository import Neo4jRelationRepository

        repo = Neo4jRelationRepository(driver=FakeDriver())
        assert repo.get("proj-a", "nonexistent") is None

    def test_list_by_space_returns_relations_in_space(self) -> None:
        """list_by_space returns only relations in the given space."""
        from memorable.storage.neo4j.repository import (
            Neo4jEntityRepository,
            Neo4jRelationRepository,
        )

        driver = FakeDriver()
        entity_repo = Neo4jEntityRepository(driver=driver)
        repo = Neo4jRelationRepository(driver=driver)
        ts = datetime(2025, 2, 1, 9, 0, 0, tzinfo=UTC)

        # Entities in proj-a
        entity_repo.save(
            Entity(id="e1", entity_type="api", name="Users", space="proj-a"),
            _make_provenance("e1", "entity"),
        )
        entity_repo.save(
            Entity(id="e2", entity_type="api", name="Orders", space="proj-a"),
            _make_provenance("e2", "entity"),
        )
        entity_repo.save(
            Entity(id="e3", entity_type="api", name="Billing", space="proj-a"),
            _make_provenance("e3", "entity"),
        )
        # Entity in proj-b
        entity_repo.save(
            Entity(id="e4", entity_type="api", name="X", space="proj-b"),
            _make_provenance("e4", "entity"),
        )
        entity_repo.save(
            Entity(id="e5", entity_type="api", name="Y", space="proj-b"),
            _make_provenance("e5", "entity"),
        )

        r1 = Relation(
            id="r1",
            source_entity_id="e1",
            target_entity_id="e2",
            relation_type="depends-on",
            statement="Users depends on Orders",
            space="proj-a",
            validity_time=ts,
            invalidation_time=None,
            lifecycle_state="current",
            supersedes=None,
            superseded_by=None,
        )
        r2 = Relation(
            id="r2",
            source_entity_id="e2",
            target_entity_id="e3",
            relation_type="owns",
            statement="Orders owns Billing",
            space="proj-a",
            validity_time=ts,
            invalidation_time=None,
            lifecycle_state="current",
            supersedes=None,
            superseded_by=None,
        )
        r3 = Relation(
            id="r3",
            source_entity_id="e4",
            target_entity_id="e5",
            relation_type="uses",
            statement="X uses Y",
            space="proj-b",
            validity_time=ts,
            invalidation_time=None,
            lifecycle_state="current",
            supersedes=None,
            superseded_by=None,
        )

        repo.save(r1, _make_provenance("r1", "relation"))
        repo.save(r2, _make_provenance("r2", "relation"))
        repo.save(r3, _make_provenance("r3", "relation"))

        results = repo.list_by_space("proj-a")
        assert len(results) == 2
        ids = {r.id for r in results}
        assert ids == {"r1", "r2"}

    def test_mark_superseded_updates_fields(self) -> None:
        """mark_superseded sets superseded_by, invalidation_time, lifecycle_state."""
        from memorable.storage.neo4j.repository import (
            Neo4jEntityRepository,
            Neo4jRelationRepository,
        )

        driver = FakeDriver()
        entity_repo = Neo4jEntityRepository(driver=driver)
        repo = Neo4jRelationRepository(driver=driver)
        ts = datetime(2025, 2, 1, 9, 0, 0, tzinfo=UTC)
        inv_time = datetime(2025, 3, 1, 12, 0, 0, tzinfo=UTC)

        entity_repo.save(
            Entity(id="ent-1", entity_type="component", name="A", space="proj-a"),
            _make_provenance("ent-1", "entity"),
        )
        entity_repo.save(
            Entity(id="ent-2", entity_type="component", name="B", space="proj-a"),
            _make_provenance("ent-2", "entity"),
        )

        relation = Relation(
            id="rel-1",
            source_entity_id="ent-1",
            target_entity_id="ent-2",
            relation_type="depends-on",
            statement="A depends on B",
            space="proj-a",
            validity_time=ts,
            invalidation_time=None,
            lifecycle_state="current",
            supersedes=None,
            superseded_by=None,
        )
        repo.save(relation, _make_provenance("rel-1", "relation"))

        repo.mark_superseded("proj-a", "rel-1", "rel-2", inv_time)

        result = repo.get("proj-a", "rel-1")
        assert result is not None
        assert result.superseded_by == "rel-2"
        assert result.invalidation_time == inv_time
        assert result.lifecycle_state == "superseded"

    def test_get_provenance_returns_provenance_after_save(self) -> None:
        """get_provenance returns the provenance stored with the relation."""
        from memorable.storage.neo4j.repository import (
            Neo4jEntityRepository,
            Neo4jRelationRepository,
        )

        driver = FakeDriver()
        entity_repo = Neo4jEntityRepository(driver=driver)
        repo = Neo4jRelationRepository(driver=driver)
        ts = datetime(2025, 2, 1, 9, 0, 0, tzinfo=UTC)

        entity_repo.save(
            Entity(id="ent-1", entity_type="component", name="A", space="proj-a"),
            _make_provenance("ent-1", "entity"),
        )
        entity_repo.save(
            Entity(id="ent-2", entity_type="component", name="B", space="proj-a"),
            _make_provenance("ent-2", "entity"),
        )

        relation = Relation(
            id="rel-1",
            source_entity_id="ent-1",
            target_entity_id="ent-2",
            relation_type="depends-on",
            statement="A depends on B",
            space="proj-a",
            validity_time=ts,
            invalidation_time=None,
            lifecycle_state="current",
            supersedes=None,
            superseded_by=None,
        )
        provenance = Provenance(
            record_id="rel-1",
            record_kind="relation",
            source_id="src-10",
            episode_id="ep-5",
            writer="agent-y",
            reason="discovered dependency",
            creation_time=ts,
            validity_time=ts,
        )

        repo.save(relation, provenance)
        result = repo.get_provenance("proj-a", "rel-1")

        assert result is not None
        assert result.record_id == "rel-1"
        assert result.record_kind == "relation"
        assert result.source_id == "src-10"
        assert result.writer == "agent-y"

    def test_get_provenance_returns_none_for_missing(self) -> None:
        """get_provenance returns None when relation has no provenance."""
        from memorable.storage.neo4j.repository import Neo4jRelationRepository

        repo = Neo4jRelationRepository(driver=FakeDriver())
        assert repo.get_provenance("proj-a", "nonexistent") is None

    def test_invalidate_sets_lifecycle_and_time(self) -> None:
        """invalidate sets lifecycle_state to invalidated and records time."""
        from memorable.storage.neo4j.repository import (
            Neo4jEntityRepository,
            Neo4jRelationRepository,
        )

        driver = FakeDriver()
        entity_repo = Neo4jEntityRepository(driver=driver)
        repo = Neo4jRelationRepository(driver=driver)
        ts = datetime(2025, 2, 1, 9, 0, 0, tzinfo=UTC)
        inv_time = datetime(2025, 3, 1, 12, 0, 0, tzinfo=UTC)

        entity_repo.save(
            Entity(id="ent-1", entity_type="component", name="A", space="proj-a"),
            _make_provenance("ent-1", "entity"),
        )
        entity_repo.save(
            Entity(id="ent-2", entity_type="component", name="B", space="proj-a"),
            _make_provenance("ent-2", "entity"),
        )

        relation = Relation(
            id="rel-1",
            source_entity_id="ent-1",
            target_entity_id="ent-2",
            relation_type="depends-on",
            statement="A depends on B",
            space="proj-a",
            validity_time=ts,
            invalidation_time=None,
            lifecycle_state="current",
            supersedes=None,
            superseded_by=None,
        )
        repo.save(relation, _make_provenance("rel-1", "relation"))

        repo.invalidate("proj-a", "rel-1", inv_time)

        result = repo.get("proj-a", "rel-1")
        assert result is not None
        assert result.lifecycle_state == "invalidated"
        assert result.invalidation_time == inv_time

    def test_correct_updates_statement_in_place(self) -> None:
        """correct updates the statement without changing other fields."""
        from memorable.storage.neo4j.repository import (
            Neo4jEntityRepository,
            Neo4jRelationRepository,
        )

        driver = FakeDriver()
        entity_repo = Neo4jEntityRepository(driver=driver)
        repo = Neo4jRelationRepository(driver=driver)
        ts = datetime(2025, 2, 1, 9, 0, 0, tzinfo=UTC)

        entity_repo.save(
            Entity(id="ent-1", entity_type="component", name="A", space="proj-a"),
            _make_provenance("ent-1", "entity"),
        )
        entity_repo.save(
            Entity(id="ent-2", entity_type="component", name="B", space="proj-a"),
            _make_provenance("ent-2", "entity"),
        )

        relation = Relation(
            id="rel-1",
            source_entity_id="ent-1",
            target_entity_id="ent-2",
            relation_type="depends-on",
            statement="A depends on B (wrong)",
            space="proj-a",
            validity_time=ts,
            invalidation_time=None,
            lifecycle_state="current",
            supersedes=None,
            superseded_by=None,
        )
        repo.save(relation, _make_provenance("rel-1", "relation"))

        repo.correct("proj-a", "rel-1", "A depends on B (corrected)")

        result = repo.get("proj-a", "rel-1")
        assert result is not None
        assert result.statement == "A depends on B (corrected)"
        assert result.lifecycle_state == "current"
        assert result.invalidation_time is None

    def test_save_provenance_replaces_existing(self) -> None:
        """save_provenance replaces the provenance for a relation."""
        from memorable.storage.neo4j.repository import (
            Neo4jEntityRepository,
            Neo4jRelationRepository,
        )

        driver = FakeDriver()
        entity_repo = Neo4jEntityRepository(driver=driver)
        repo = Neo4jRelationRepository(driver=driver)
        ts = datetime(2025, 2, 1, 9, 0, 0, tzinfo=UTC)
        correction_ts = datetime(2025, 3, 1, 12, 0, 0, tzinfo=UTC)

        entity_repo.save(
            Entity(id="ent-1", entity_type="component", name="A", space="proj-a"),
            _make_provenance("ent-1", "entity"),
        )
        entity_repo.save(
            Entity(id="ent-2", entity_type="component", name="B", space="proj-a"),
            _make_provenance("ent-2", "entity"),
        )

        relation = Relation(
            id="rel-1",
            source_entity_id="ent-1",
            target_entity_id="ent-2",
            relation_type="depends-on",
            statement="A depends on B",
            space="proj-a",
            validity_time=ts,
            invalidation_time=None,
            lifecycle_state="current",
            supersedes=None,
            superseded_by=None,
        )
        repo.save(relation, _make_provenance("rel-1", "relation"))

        new_prov = Provenance(
            record_id="rel-1",
            record_kind="relation",
            source_id="src-correction",
            episode_id="ep-correction",
            writer="human:reviewer",
            reason="Corrected provenance.",
            creation_time=correction_ts,
            validity_time=correction_ts,
        )
        repo.save_provenance("proj-a", "rel-1", new_prov)

        result = repo.get_provenance("proj-a", "rel-1")
        assert result is not None
        assert result.source_id == "src-correction"
        assert result.writer == "human:reviewer"
        assert "Corrected" in result.reason

    def test_list_by_entity_returns_relations_for_entity(self) -> None:
        """list_by_entity returns relations where entity is source or target."""
        from memorable.storage.neo4j.repository import (
            Neo4jEntityRepository,
            Neo4jRelationRepository,
        )

        driver = FakeDriver()
        entity_repo = Neo4jEntityRepository(driver=driver)
        repo = Neo4jRelationRepository(driver=driver)
        ts = datetime(2025, 2, 1, 9, 0, 0, tzinfo=UTC)

        entity_repo.save(
            Entity(id="e1", entity_type="component", name="A", space="proj-a"),
            _make_provenance("e1", "entity"),
        )
        entity_repo.save(
            Entity(id="e2", entity_type="component", name="B", space="proj-a"),
            _make_provenance("e2", "entity"),
        )
        entity_repo.save(
            Entity(id="e3", entity_type="component", name="C", space="proj-a"),
            _make_provenance("e3", "entity"),
        )

        # e1 -> e2
        r1 = Relation(
            id="r1",
            source_entity_id="e1",
            target_entity_id="e2",
            relation_type="depends-on",
            statement="A depends on B",
            space="proj-a",
            validity_time=ts,
            invalidation_time=None,
            lifecycle_state="current",
            supersedes=None,
            superseded_by=None,
        )
        # e3 -> e1 (e1 is target here)
        r2 = Relation(
            id="r2",
            source_entity_id="e3",
            target_entity_id="e1",
            relation_type="owns",
            statement="C owns A",
            space="proj-a",
            validity_time=ts,
            invalidation_time=None,
            lifecycle_state="current",
            supersedes=None,
            superseded_by=None,
        )
        # e2 -> e3 (does not involve e1)
        r3 = Relation(
            id="r3",
            source_entity_id="e2",
            target_entity_id="e3",
            relation_type="uses",
            statement="B uses C",
            space="proj-a",
            validity_time=ts,
            invalidation_time=None,
            lifecycle_state="current",
            supersedes=None,
            superseded_by=None,
        )

        repo.save(r1, _make_provenance("r1", "relation"))
        repo.save(r2, _make_provenance("r2", "relation"))
        repo.save(r3, _make_provenance("r3", "relation"))

        results = repo.list_by_entity("proj-a", "e1")
        assert len(results) == 2
        ids = {r.id for r in results}
        assert ids == {"r1", "r2"}

    def test_list_by_entity_excludes_other_spaces(self) -> None:
        """list_by_entity does not return relations from other spaces."""
        from memorable.storage.neo4j.repository import (
            Neo4jEntityRepository,
            Neo4jRelationRepository,
        )

        driver = FakeDriver()
        entity_repo = Neo4jEntityRepository(driver=driver)
        repo = Neo4jRelationRepository(driver=driver)
        ts = datetime(2025, 2, 1, 9, 0, 0, tzinfo=UTC)

        # Entities in proj-a
        entity_repo.save(
            Entity(id="e1", entity_type="component", name="A", space="proj-a"),
            _make_provenance("e1", "entity"),
        )
        entity_repo.save(
            Entity(id="e2", entity_type="component", name="B", space="proj-a"),
            _make_provenance("e2", "entity"),
        )
        # Entities in proj-b (same id e1 in different space)
        entity_repo.save(
            Entity(id="e1", entity_type="component", name="A2", space="proj-b"),
            _make_provenance("e1", "entity"),
        )
        entity_repo.save(
            Entity(id="e3", entity_type="component", name="C", space="proj-b"),
            _make_provenance("e3", "entity"),
        )

        r_a = Relation(
            id="ra",
            source_entity_id="e1",
            target_entity_id="e2",
            relation_type="depends-on",
            statement="A depends on B",
            space="proj-a",
            validity_time=ts,
            invalidation_time=None,
            lifecycle_state="current",
            supersedes=None,
            superseded_by=None,
        )
        r_b = Relation(
            id="rb",
            source_entity_id="e1",
            target_entity_id="e3",
            relation_type="uses",
            statement="A2 uses C",
            space="proj-b",
            validity_time=ts,
            invalidation_time=None,
            lifecycle_state="current",
            supersedes=None,
            superseded_by=None,
        )

        repo.save(r_a, _make_provenance("ra", "relation"))
        repo.save(r_b, _make_provenance("rb", "relation"))

        results = repo.list_by_entity("proj-a", "e1")
        assert len(results) == 1
        assert results[0].id == "ra"


# --- Schema bootstrap tests ---


class TestEnsureAllConstraints:
    """Unit tests for ensure_all_constraints."""

    def test_ensure_all_constraints_is_callable(self) -> None:
        """ensure_all_constraints must be importable and callable."""
        from memorable.storage.neo4j.repository import ensure_all_constraints

        assert callable(ensure_all_constraints)

    def test_ensure_all_constraints_runs_without_error(self) -> None:
        """ensure_all_constraints runs against fake driver without error."""
        from memorable.storage.neo4j.repository import ensure_all_constraints

        driver = FakeDriver()
        ensure_all_constraints(driver)

    def test_ensure_all_constraints_is_idempotent(self) -> None:
        """Running ensure_all_constraints twice does not raise."""
        from memorable.storage.neo4j.repository import ensure_all_constraints

        driver = FakeDriver()
        ensure_all_constraints(driver)
        ensure_all_constraints(driver)
