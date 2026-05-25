"""Tests for Neo4j adapters.

Unit tests use a fake driver to verify adapter logic without Neo4j.
Integration tests (marked with @pytest.mark.integration) need a running Neo4j.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from memorable.core.models import Decision, Entity, Provenance, Task

# --- Fake driver for unit tests ---


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
        if "Provenance" in query and "MATCH" in query:
            space = str(params.get("space", ""))
            record_id = str(params.get("id", ""))
            provs = self._store.get("Provenance", {})
            if "Entity" in query:
                prov = provs.get(("entity", space, record_id))
            elif "Decision" in query:
                prov = provs.get(("decision", space, record_id))
            elif "Task" in query:
                prov = provs.get(("task", space, record_id))
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
            entities[key] = {
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
        if "Entity" in query and "MATCH" in query:
            space = str(params.get("space", ""))
            entity_id = str(params.get("id", ""))
            if not entity_id:
                entities = self._store.get("Entity", {})
                results = [e for (s, _), e in entities.items() if s == space]
                return FakeResult(results)
            entities = self._store.get("Entity", {})
            entity = entities.get((space, entity_id))
            if entity:
                return FakeResult([entity])
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

        # --- Decision mark_superseded (MATCH + SET) ---
        if "Decision" in query and "SET" in query:
            space = str(params.get("space", ""))
            decision_id = str(params.get("id", ""))
            decisions = self._store.get("Decision", {})
            key = (space, decision_id)
            if key in decisions:
                decisions[key]["superseded_by"] = params.get("superseded_by")
                decisions[key]["invalidation_time"] = params.get("invalidation_time")
                decisions[key]["lifecycle_state"] = params.get(
                    "lifecycle_state", "superseded"
                )
            return FakeResult()

        # --- Decision MATCH (single or list) ---
        if "Decision" in query and "MATCH" in query:
            space = str(params.get("space", ""))
            decision_id = str(params.get("id", ""))
            if not decision_id:
                decisions = self._store.get("Decision", {})
                results = [d for (s, _), d in decisions.items() if s == space]
                return FakeResult(results)
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
            task_id = str(params.get("id", ""))
            if not task_id:
                tasks = self._store.get("Task", {})
                results = [t for (s, _), t in tasks.items() if s == space]
                return FakeResult(results)
            tasks = self._store.get("Task", {})
            task = tasks.get((space, task_id))
            if task:
                return FakeResult([task])
            return FakeResult()

        return FakeResult()


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


# --- Task adapter tests ---


class TestNeo4jTaskRepository:
    """Unit tests for Neo4jTaskRepository."""

    def test_implements_task_repository_protocol(self) -> None:
        """Neo4jTaskRepository must have all TaskRepository methods."""
        from memorable.storage.neo4j.repository import Neo4jTaskRepository

        assert hasattr(Neo4jTaskRepository, "save")
        assert hasattr(Neo4jTaskRepository, "get")
        assert hasattr(Neo4jTaskRepository, "get_provenance")
        assert hasattr(Neo4jTaskRepository, "list_by_space")
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

    def test_get_provenance_returns_none_for_missing(self) -> None:
        """get_provenance returns None when task has no provenance."""
        from memorable.storage.neo4j.repository import Neo4jTaskRepository

        repo = Neo4jTaskRepository(driver=FakeDriver())
        assert repo.get_provenance(space="proj-a", task_id="nonexistent") is None


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
