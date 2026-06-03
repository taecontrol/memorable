from __future__ import annotations

import textwrap
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest

AT = datetime(2026, 6, 3, 9, 0, tzinfo=UTC)

PROFILE_YAML = textwrap.dedent("""\
    version: 1
    space:
      name: memorable
    entities:
      - name: Project
    relations:
      - name: depends-on
    records: []
""")

neo4j_available = False
try:
    from neo4j import GraphDatabase

    from memorable.storage.neo4j.config import Neo4jConfig

    _config = Neo4jConfig.from_env()
    _driver = GraphDatabase.driver(_config.uri, auth=(_config.user, _config.password))
    _driver.verify_connectivity()
    _driver.close()
    neo4j_available = True
except Exception:
    neo4j_available = False


def _unique_space() -> str:
    return f"test-forget-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def neo4j_forget_context() -> Iterator[object]:
    if not neo4j_available:
        pytest.skip("Neo4j is not available")

    from neo4j import GraphDatabase

    from memorable.core.context import ApplicationContext
    from memorable.storage.neo4j.config import Neo4jConfig
    from memorable.storage.neo4j.repository import (
        Neo4jAboutRepository,
        Neo4jDecisionRepository,
        Neo4jEntityRepository,
        Neo4jForgetRepository,
        Neo4jObservationRepository,
        Neo4jRelationRepository,
        Neo4jTaskRepository,
    )

    config = Neo4jConfig.from_env()
    driver = GraphDatabase.driver(config.uri, auth=(config.user, config.password))
    ctx = ApplicationContext(
        entity_repo=Neo4jEntityRepository(driver),
        decision_repo=Neo4jDecisionRepository(driver),
        observation_repo=Neo4jObservationRepository(driver),
        task_repo=Neo4jTaskRepository(driver),
        about_repo=Neo4jAboutRepository(driver),
        relation_repo=Neo4jRelationRepository(driver),
        forget_repo=Neo4jForgetRepository(driver),
    )
    yield ctx
    with driver.session() as session:
        session.run(
            "MATCH (p:Provenance)-[:PROVENANCE_OF]->(n) "
            "WHERE n.space STARTS WITH 'test-forget-' DETACH DELETE p"
        )
        session.run(
            "MATCH (n) WHERE n.space STARTS WITH 'test-forget-' DETACH DELETE n"
        )
    driver.close()


def _context_with_profile():
    from memorable.core.application import (
        AboutLinker,
        RememberEntityService,
    )
    from memorable.core.context import ApplicationContext
    from memorable.core.profile import load_profile_from_yaml

    profile = load_profile_from_yaml(PROFILE_YAML)
    ctx = ApplicationContext()
    entity_service = RememberEntityService(repository=ctx.entity_repo, profile=profile)
    about_linker = AboutLinker(entity_repo=ctx.entity_repo, about_repo=ctx.about_repo)
    return ctx, profile, entity_service, about_linker


def _remember_entity(entity_service, *, space: str, entity_id: str) -> None:
    entity_service.remember(
        space=space,
        entity_id=entity_id,
        entity_type="Project",
        name=entity_id,
        source_id="source:test",
        at=AT,
    )


def _remember_record(
    ctx,
    profile,
    about_linker,
    *,
    space: str,
    record_kind: str,
    record_id: str,
    about: list[str] | None = None,
) -> None:
    if record_kind == "decision":
        from memorable.core.application import RememberDecisionService

        RememberDecisionService(
            repository=ctx.decision_repo,
            profile=profile,
            about_linker=about_linker,
        ).remember(
            space=space,
            decision_id=record_id,
            statement=f"Scratch {record_kind}.",
            source_id="source:test",
            at=AT,
            about=about,
        )
    elif record_kind == "observation":
        from memorable.core.application import RememberObservationService

        RememberObservationService(
            repository=ctx.observation_repo,
            profile=profile,
            about_linker=about_linker,
        ).remember(
            space=space,
            observation_id=record_id,
            statement=f"Scratch {record_kind}.",
            source_id="source:test",
            at=AT,
            about=about,
        )
    elif record_kind == "task":
        from memorable.core.application import RememberTaskService

        RememberTaskService(
            repository=ctx.task_repo,
            profile=profile,
            about_linker=about_linker,
        ).remember(
            space=space,
            task_id=record_id,
            title=f"Scratch {record_kind}.",
            source_id="source:test",
            at=AT,
            about=about,
        )
    else:
        raise AssertionError(f"unhandled record kind: {record_kind}")


def _remember_relation(
    ctx,
    profile,
    *,
    space: str,
    relation_id: str,
    source_entity_id: str,
    target_entity_id: str,
) -> None:
    from memorable.core.application import RememberRelationService

    RememberRelationService(
        relation_repo=ctx.relation_repo,
        entity_repo=ctx.entity_repo,
        profile=profile,
    ).remember(
        space=space,
        relation_id=relation_id,
        source_entity_id=source_entity_id,
        target_entity_id=target_entity_id,
        relation_type="depends-on",
        statement=f"{source_entity_id} depends on {target_entity_id}.",
        source_id="source:test",
        at=AT,
    )


def _get_record(ctx, *, space: str, record_kind: str, record_id: str):
    if record_kind == "decision":
        return ctx.decision_repo.get(space, record_id)
    if record_kind == "observation":
        return ctx.observation_repo.get(space, record_id)
    if record_kind == "task":
        return ctx.task_repo.get(space=space, task_id=record_id)
    raise AssertionError(f"unhandled record kind: {record_kind}")


def _get_provenance(ctx, *, space: str, record_kind: str, record_id: str):
    if record_kind == "decision":
        return ctx.decision_repo.get_provenance(space, record_id)
    if record_kind == "observation":
        return ctx.observation_repo.get_provenance(space, record_id)
    if record_kind == "task":
        return ctx.task_repo.get_provenance(space=space, task_id=record_id)
    raise AssertionError(f"unhandled record kind: {record_kind}")


def test_forget_repository_port_methods() -> None:
    from memorable.core.ports import ForgetRepository

    methods = {name for name in vars(ForgetRepository) if not name.startswith("_")}
    assert methods == {
        "entity_exists",
        "forget_entity",
        "forget_record",
        "get_forget_target",
    }


@pytest.mark.parametrize(
    ("record_kind", "record_id"),
    [
        ("decision", "decision:scratch"),
        ("observation", "observation:scratch"),
        ("task", "task:scratch"),
    ],
)
def test_forget_record_removes_record_provenance_and_about_but_not_entity(
    record_kind: str,
    record_id: str,
) -> None:
    from memorable.core.application import ForgetService

    ctx, profile, entity_service, about_linker = _context_with_profile()
    _remember_entity(
        entity_service,
        space="memorable",
        entity_id="entity:scratch",
    )
    _remember_record(
        ctx,
        profile,
        about_linker,
        space="memorable",
        record_kind=record_kind,
        record_id=record_id,
        about=["entity:scratch"],
    )

    result = ForgetService(repository=ctx.forget_repo).forget_record(
        space="memorable",
        record_id=record_id,
        record_kind=record_kind,
    )

    assert result.record_id == record_id
    assert result.record_kind == record_kind
    assert (
        _get_record(
            ctx,
            space="memorable",
            record_kind=record_kind,
            record_id=record_id,
        )
        is None
    )
    assert (
        _get_provenance(
            ctx,
            space="memorable",
            record_kind=record_kind,
            record_id=record_id,
        )
        is None
    )
    assert ctx.about_repo.entities_for_record("memorable", record_id) == []
    assert ctx.entity_repo.get("memorable", "entity:scratch") is not None


def test_forget_missing_id_fails_loud() -> None:
    from memorable.core.application import ForgetService
    from memorable.core.errors import NothingToForgetError

    ctx, _profile, _entity_service, _about_linker = _context_with_profile()

    with pytest.raises(NothingToForgetError, match="Nothing to forget"):
        ForgetService(repository=ctx.forget_repo).forget_record(
            space="memorable",
            record_id="decision:missing",
            record_kind="decision",
        )


def test_forget_is_scoped_to_one_memory_space() -> None:
    from memorable.core.application import ForgetService

    ctx, profile, _entity_service, about_linker = _context_with_profile()
    for space in ("space-a", "space-b"):
        _remember_record(
            ctx,
            profile,
            about_linker,
            space=space,
            record_kind="decision",
            record_id="decision:same-id",
        )

    ForgetService(repository=ctx.forget_repo).forget_record(
        space="space-a",
        record_id="decision:same-id",
        record_kind="decision",
    )

    assert ctx.decision_repo.get("space-a", "decision:same-id") is None
    assert ctx.decision_repo.get_provenance("space-a", "decision:same-id") is None
    assert ctx.decision_repo.get("space-b", "decision:same-id") is not None
    assert ctx.decision_repo.get_provenance("space-b", "decision:same-id") is not None


def test_forget_allows_record_id_to_be_remembered_again() -> None:
    from memorable.core.application import ForgetService

    ctx, profile, _entity_service, about_linker = _context_with_profile()
    _remember_record(
        ctx,
        profile,
        about_linker,
        space="memorable",
        record_kind="decision",
        record_id="decision:retry",
    )

    ForgetService(repository=ctx.forget_repo).forget_record(
        space="memorable",
        record_id="decision:retry",
        record_kind="decision",
    )
    _remember_record(
        ctx,
        profile,
        about_linker,
        space="memorable",
        record_kind="decision",
        record_id="decision:retry",
    )

    assert ctx.decision_repo.get("memorable", "decision:retry") is not None


def test_forget_refuses_record_in_supersession_chain() -> None:
    from memorable.core.application import ForgetService, RememberDecisionService
    from memorable.core.errors import CannotForgetRecordInSupersessionChainError

    ctx, profile, _entity_service, about_linker = _context_with_profile()
    service = RememberDecisionService(
        repository=ctx.decision_repo,
        profile=profile,
        about_linker=about_linker,
    )
    service.remember(
        space="memorable",
        decision_id="decision:v1",
        statement="Use scratch plan.",
        source_id="source:test",
        at=AT,
    )
    service.remember(
        space="memorable",
        decision_id="decision:v2",
        statement="Use updated scratch plan.",
        source_id="source:test",
        at=AT,
        supersedes="decision:v1",
    )

    with pytest.raises(
        CannotForgetRecordInSupersessionChainError,
        match="supersession chain",
    ):
        ForgetService(repository=ctx.forget_repo).forget_record(
            space="memorable",
            record_id="decision:v1",
            record_kind="decision",
        )

    assert ctx.decision_repo.get("memorable", "decision:v1") is not None
    assert ctx.decision_repo.get("memorable", "decision:v2") is not None


def test_forget_entity_cascades_relations_and_about_edges_only() -> None:
    from memorable.core.application import ForgetService

    ctx, profile, entity_service, about_linker = _context_with_profile()
    for entity_id in (
        "entity:scratch",
        "entity:related",
        "entity:unrelated-a",
        "entity:unrelated-b",
    ):
        _remember_entity(entity_service, space="memorable", entity_id=entity_id)
    _remember_relation(
        ctx,
        profile,
        space="memorable",
        relation_id="relation:scratch",
        source_entity_id="entity:scratch",
        target_entity_id="entity:related",
    )
    _remember_relation(
        ctx,
        profile,
        space="memorable",
        relation_id="relation:unrelated",
        source_entity_id="entity:unrelated-a",
        target_entity_id="entity:unrelated-b",
    )
    _remember_record(
        ctx,
        profile,
        about_linker,
        space="memorable",
        record_kind="decision",
        record_id="decision:about-scratch",
        about=["entity:scratch"],
    )
    _remember_record(
        ctx,
        profile,
        about_linker,
        space="memorable",
        record_kind="observation",
        record_id="observation:unrelated",
        about=["entity:unrelated-a"],
    )

    result = ForgetService(repository=ctx.forget_repo).forget_entity(
        space="memorable",
        entity_id="entity:scratch",
    )

    assert result.record_id == "entity:scratch"
    assert result.record_kind == "entity"
    assert ctx.entity_repo.get("memorable", "entity:scratch") is None
    assert ctx.entity_repo.get_provenance("memorable", "entity:scratch") is None
    assert ctx.relation_repo.get("memorable", "relation:scratch") is None
    assert ctx.relation_repo.get_provenance("memorable", "relation:scratch") is None
    assert ctx.about_repo.records_for_entity("memorable", "entity:scratch") == []
    assert ctx.decision_repo.get("memorable", "decision:about-scratch") is not None
    assert ctx.entity_repo.get("memorable", "entity:related") is not None
    assert ctx.entity_repo.get("memorable", "entity:unrelated-a") is not None
    assert ctx.relation_repo.get("memorable", "relation:unrelated") is not None
    assert (
        ctx.relation_repo.get_provenance("memorable", "relation:unrelated") is not None
    )
    assert ctx.about_repo.records_for_entity("memorable", "entity:unrelated-a") == [
        "observation:unrelated"
    ]


def test_forget_missing_entity_id_fails_loud() -> None:
    from memorable.core.application import ForgetService
    from memorable.core.errors import NothingToForgetError

    ctx, _profile, _entity_service, _about_linker = _context_with_profile()

    with pytest.raises(NothingToForgetError, match="Nothing to forget"):
        ForgetService(repository=ctx.forget_repo).forget_entity(
            space="memorable",
            entity_id="entity:missing",
        )


def test_forget_entity_is_scoped_to_one_memory_space() -> None:
    from memorable.core.application import ForgetService

    ctx, profile, entity_service, about_linker = _context_with_profile()
    for space in ("space-a", "space-b"):
        _remember_entity(entity_service, space=space, entity_id="entity:same-id")
        _remember_entity(entity_service, space=space, entity_id="entity:related")
        _remember_relation(
            ctx,
            profile,
            space=space,
            relation_id="relation:same-id",
            source_entity_id="entity:same-id",
            target_entity_id="entity:related",
        )
        _remember_record(
            ctx,
            profile,
            about_linker,
            space=space,
            record_kind="decision",
            record_id="decision:same-id",
            about=["entity:same-id"],
        )

    ForgetService(repository=ctx.forget_repo).forget_entity(
        space="space-a",
        entity_id="entity:same-id",
    )

    assert ctx.entity_repo.get("space-a", "entity:same-id") is None
    assert ctx.entity_repo.get_provenance("space-a", "entity:same-id") is None
    assert ctx.relation_repo.get("space-a", "relation:same-id") is None
    assert ctx.about_repo.records_for_entity("space-a", "entity:same-id") == []
    assert ctx.entity_repo.get("space-b", "entity:same-id") is not None
    assert ctx.entity_repo.get_provenance("space-b", "entity:same-id") is not None
    assert ctx.relation_repo.get("space-b", "relation:same-id") is not None
    assert ctx.about_repo.records_for_entity("space-b", "entity:same-id") == [
        "decision:same-id"
    ]


@pytest.mark.parametrize(
    ("record_kind", "record_id", "remember_args"),
    [
        (
            "decision",
            "decision:cli-scratch",
            ["decision", "--statement", "Scratch CLI decision."],
        ),
        (
            "observation",
            "observation:cli-scratch",
            ["observation", "--statement", "Scratch CLI observation."],
        ),
        (
            "task",
            "task:cli-scratch",
            ["task", "--title", "Scratch CLI task."],
        ),
    ],
)
def test_cli_forget_record_by_id(
    cli_in_memory_context,
    capsys,
    record_kind: str,
    record_id: str,
    remember_args: list[str],
) -> None:
    from memorable.cli import main

    ctx = cli_in_memory_context
    rc = main(
        [
            "remember",
            remember_args[0],
            "--space",
            "memorable",
            "--id",
            record_id,
            *remember_args[1:],
            "--source",
            "source:test",
            "--at",
            "2026-06-03T09:00:00Z",
        ]
    )
    assert rc == 0
    capsys.readouterr()

    rc = main(
        [
            "forget",
            "--space",
            "memorable",
            "--record-type",
            record_kind,
            "--id",
            record_id,
        ]
    )

    assert rc == 0
    assert (
        _get_record(
            ctx,
            space="memorable",
            record_kind=record_kind,
            record_id=record_id,
        )
        is None
    )
    output = capsys.readouterr().out
    assert record_id in output


def test_cli_forget_entity_by_id(cli_in_memory_context, capsys) -> None:
    from memorable.cli import main

    ctx = cli_in_memory_context
    rc = main(
        [
            "remember",
            "entity",
            "--space",
            "memorable",
            "--id",
            "entity:cli-scratch",
            "--type",
            "Project",
            "--name",
            "CLI scratch",
            "--source",
            "source:test",
            "--at",
            "2026-06-03T09:00:00Z",
        ]
    )
    assert rc == 0
    capsys.readouterr()

    rc = main(
        [
            "forget",
            "--space",
            "memorable",
            "--record-type",
            "entity",
            "--id",
            "entity:cli-scratch",
        ]
    )

    assert rc == 0
    assert ctx.entity_repo.get("memorable", "entity:cli-scratch") is None
    assert ctx.entity_repo.get_provenance("memorable", "entity:cli-scratch") is None
    output = capsys.readouterr().out
    assert "entity:cli-scratch" in output


@pytest.mark.integration
@pytest.mark.parametrize(
    ("record_kind", "record_id"),
    [
        ("decision", "decision:neo4j-scratch"),
        ("observation", "observation:neo4j-scratch"),
        ("task", "task:neo4j-scratch"),
    ],
)
def test_neo4j_forget_record_removes_record_provenance_and_about_but_not_entity(
    neo4j_forget_context,
    record_kind: str,
    record_id: str,
) -> None:
    from memorable.core.application import (
        AboutLinker,
        ForgetService,
        RememberEntityService,
    )
    from memorable.core.profile import load_profile_from_yaml

    ctx = neo4j_forget_context
    profile = load_profile_from_yaml(PROFILE_YAML)
    entity_service = RememberEntityService(repository=ctx.entity_repo, profile=profile)
    about_linker = AboutLinker(entity_repo=ctx.entity_repo, about_repo=ctx.about_repo)
    space = _unique_space()
    _remember_entity(entity_service, space=space, entity_id="entity:neo4j-scratch")
    _remember_record(
        ctx,
        profile,
        about_linker,
        space=space,
        record_kind=record_kind,
        record_id=record_id,
        about=["entity:neo4j-scratch"],
    )

    ForgetService(repository=ctx.forget_repo).forget_record(
        space=space,
        record_id=record_id,
        record_kind=record_kind,
    )

    assert (
        _get_record(
            ctx,
            space=space,
            record_kind=record_kind,
            record_id=record_id,
        )
        is None
    )
    assert (
        _get_provenance(
            ctx,
            space=space,
            record_kind=record_kind,
            record_id=record_id,
        )
        is None
    )
    assert ctx.about_repo.entities_for_record(space, record_id) == []
    assert ctx.entity_repo.get(space, "entity:neo4j-scratch") is not None


@pytest.mark.integration
def test_neo4j_forget_missing_id_fails_loud(neo4j_forget_context) -> None:
    from memorable.core.application import ForgetService
    from memorable.core.errors import NothingToForgetError

    with pytest.raises(NothingToForgetError, match="Nothing to forget"):
        ForgetService(repository=neo4j_forget_context.forget_repo).forget_record(
            space=_unique_space(),
            record_id="decision:missing",
            record_kind="decision",
        )


@pytest.mark.integration
def test_neo4j_forget_is_scoped_to_one_memory_space(neo4j_forget_context) -> None:
    from memorable.core.application import AboutLinker, ForgetService
    from memorable.core.profile import load_profile_from_yaml

    ctx = neo4j_forget_context
    profile = load_profile_from_yaml(PROFILE_YAML)
    about_linker = AboutLinker(entity_repo=ctx.entity_repo, about_repo=ctx.about_repo)
    space_a = _unique_space()
    space_b = _unique_space()
    for space in (space_a, space_b):
        _remember_record(
            ctx,
            profile,
            about_linker,
            space=space,
            record_kind="decision",
            record_id="decision:same-id",
        )

    ForgetService(repository=ctx.forget_repo).forget_record(
        space=space_a,
        record_id="decision:same-id",
        record_kind="decision",
    )

    assert ctx.decision_repo.get(space_a, "decision:same-id") is None
    assert ctx.decision_repo.get_provenance(space_a, "decision:same-id") is None
    assert ctx.decision_repo.get(space_b, "decision:same-id") is not None
    assert ctx.decision_repo.get_provenance(space_b, "decision:same-id") is not None


@pytest.mark.integration
def test_neo4j_forget_entity_cascades_relations_and_about_edges_only(
    neo4j_forget_context,
) -> None:
    from memorable.core.application import (
        AboutLinker,
        ForgetService,
        RememberEntityService,
    )
    from memorable.core.profile import load_profile_from_yaml

    ctx = neo4j_forget_context
    profile = load_profile_from_yaml(PROFILE_YAML)
    entity_service = RememberEntityService(repository=ctx.entity_repo, profile=profile)
    about_linker = AboutLinker(entity_repo=ctx.entity_repo, about_repo=ctx.about_repo)
    space = _unique_space()
    for entity_id in (
        "entity:scratch",
        "entity:related",
        "entity:unrelated-a",
        "entity:unrelated-b",
    ):
        _remember_entity(entity_service, space=space, entity_id=entity_id)
    _remember_relation(
        ctx,
        profile,
        space=space,
        relation_id="relation:scratch",
        source_entity_id="entity:scratch",
        target_entity_id="entity:related",
    )
    _remember_relation(
        ctx,
        profile,
        space=space,
        relation_id="relation:unrelated",
        source_entity_id="entity:unrelated-a",
        target_entity_id="entity:unrelated-b",
    )
    _remember_record(
        ctx,
        profile,
        about_linker,
        space=space,
        record_kind="decision",
        record_id="decision:about-scratch",
        about=["entity:scratch"],
    )
    _remember_record(
        ctx,
        profile,
        about_linker,
        space=space,
        record_kind="observation",
        record_id="observation:unrelated",
        about=["entity:unrelated-a"],
    )

    ForgetService(repository=ctx.forget_repo).forget_entity(
        space=space,
        entity_id="entity:scratch",
    )

    assert ctx.entity_repo.get(space, "entity:scratch") is None
    assert ctx.entity_repo.get_provenance(space, "entity:scratch") is None
    assert ctx.relation_repo.get(space, "relation:scratch") is None
    assert ctx.relation_repo.get_provenance(space, "relation:scratch") is None
    assert ctx.about_repo.records_for_entity(space, "entity:scratch") == []
    assert ctx.decision_repo.get(space, "decision:about-scratch") is not None
    assert ctx.entity_repo.get(space, "entity:related") is not None
    assert ctx.entity_repo.get(space, "entity:unrelated-a") is not None
    assert ctx.relation_repo.get(space, "relation:unrelated") is not None
    assert ctx.relation_repo.get_provenance(space, "relation:unrelated") is not None
    assert ctx.about_repo.records_for_entity(space, "entity:unrelated-a") == [
        "observation:unrelated"
    ]


@pytest.mark.integration
def test_neo4j_forget_missing_entity_id_fails_loud(neo4j_forget_context) -> None:
    from memorable.core.application import ForgetService
    from memorable.core.errors import NothingToForgetError

    with pytest.raises(NothingToForgetError, match="Nothing to forget"):
        ForgetService(repository=neo4j_forget_context.forget_repo).forget_entity(
            space=_unique_space(),
            entity_id="entity:missing",
        )


@pytest.mark.integration
def test_neo4j_forget_entity_is_scoped_to_one_memory_space(
    neo4j_forget_context,
) -> None:
    from memorable.core.application import (
        AboutLinker,
        ForgetService,
        RememberEntityService,
    )
    from memorable.core.profile import load_profile_from_yaml

    ctx = neo4j_forget_context
    profile = load_profile_from_yaml(PROFILE_YAML)
    entity_service = RememberEntityService(repository=ctx.entity_repo, profile=profile)
    about_linker = AboutLinker(entity_repo=ctx.entity_repo, about_repo=ctx.about_repo)
    space_a = _unique_space()
    space_b = _unique_space()
    for space in (space_a, space_b):
        _remember_entity(entity_service, space=space, entity_id="entity:same-id")
        _remember_entity(entity_service, space=space, entity_id="entity:related")
        _remember_relation(
            ctx,
            profile,
            space=space,
            relation_id="relation:same-id",
            source_entity_id="entity:same-id",
            target_entity_id="entity:related",
        )
        _remember_record(
            ctx,
            profile,
            about_linker,
            space=space,
            record_kind="decision",
            record_id="decision:same-id",
            about=["entity:same-id"],
        )

    ForgetService(repository=ctx.forget_repo).forget_entity(
        space=space_a,
        entity_id="entity:same-id",
    )

    assert ctx.entity_repo.get(space_a, "entity:same-id") is None
    assert ctx.entity_repo.get_provenance(space_a, "entity:same-id") is None
    assert ctx.relation_repo.get(space_a, "relation:same-id") is None
    assert ctx.about_repo.records_for_entity(space_a, "entity:same-id") == []
    assert ctx.entity_repo.get(space_b, "entity:same-id") is not None
    assert ctx.entity_repo.get_provenance(space_b, "entity:same-id") is not None
    assert ctx.relation_repo.get(space_b, "relation:same-id") is not None
    assert ctx.about_repo.records_for_entity(space_b, "entity:same-id") == [
        "decision:same-id"
    ]
