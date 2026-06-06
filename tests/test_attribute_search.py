"""Attribute search behavior for Entity retrieval."""

from __future__ import annotations

import textwrap
from datetime import UTC, date, datetime

SOURCE_ID = "source:attribute-search"


def _build_attribute_search_service():
    from memorable.core.application import RememberEntityService
    from memorable.core.profile import load_profile_from_yaml
    from memorable.core.repositories import (
        InMemoryDecisionRepository,
        InMemoryEntityRepository,
        InMemoryObservationRepository,
        InMemoryTaskRepository,
    )
    from memorable.retrieval.embeddings import FakeEmbeddingProvider
    from memorable.retrieval.service import HybridRetrievalService

    profile = load_profile_from_yaml(
        textwrap.dedent(
            """\
            version: 1
            space:
              name: memorable
            entities:
              - name: Reference
                attributes:
                  - name: medium
                    type: string
                  - name: rating
                    type: number
                  - name: published_on
                    type: date
                  - name: aliases
                    type: list[string]
            """
        )
    )
    entity_repo = InMemoryEntityRepository()
    entity_service = RememberEntityService(repository=entity_repo, profile=profile)
    entity_service.remember(
        space="memorable",
        entity_id="entity:video-reference",
        entity_type="Reference",
        name="Memorable demo video",
        source_id=SOURCE_ID,
        at=datetime(2026, 6, 6, 10, 0, tzinfo=UTC),
        attributes={
            "medium": "video",
            "rating": "5",
            "published_on": "2026-06-06",
            "aliases": ["demo", "walkthrough"],
        },
    )
    entity_service.remember(
        space="memorable",
        entity_id="entity:article-reference",
        entity_type="Reference",
        name="Memorable article reference",
        source_id=SOURCE_ID,
        at=datetime(2026, 6, 6, 10, 5, tzinfo=UTC),
        attributes={
            "medium": "article",
            "rating": "4",
            "published_on": "2026-06-07",
            "aliases": ["writeup"],
        },
    )

    service = HybridRetrievalService(
        entity_repo=entity_repo,
        decision_repo=InMemoryDecisionRepository(),
        task_repo=InMemoryTaskRepository(),
        observation_repo=InMemoryObservationRepository(),
        embedding_provider=FakeEmbeddingProvider(dimensions=32),
        profile=profile,
    )
    service.reindex("memorable")
    return service


def test_retrieval_result_surfaces_entity_attributes() -> None:
    """Search results expose typed Attributes for matching Entities."""
    service = _build_attribute_search_service()

    results = service.search(space="memorable", query="Memorable demo video")

    reference = next(
        result for result in results if result.source_id == "entity:video-reference"
    )
    assert reference.attributes == {
        "medium": "video",
        "rating": 5,
        "published_on": date(2026, 6, 6),
        "aliases": ["demo", "walkthrough"],
    }


def test_search_filters_entities_by_declared_attribute_value() -> None:
    """An Attribute filter narrows search to Entities with equal values."""
    service = _build_attribute_search_service()

    results = service.search(
        space="memorable",
        query="Memorable reference",
        attribute_filter={"medium": "video"},
    )

    assert [result.source_id for result in results] == ["entity:video-reference"]
    assert results[0].attributes["medium"] == "video"


def test_search_attribute_filter_validates_and_coerces_full_type_set() -> None:
    """Search Attribute filters use the declared schema for each v1 type."""
    service = _build_attribute_search_service()

    number_results = service.search(
        space="memorable",
        query="Memorable reference",
        attribute_filter={"rating": "5"},
    )
    date_results = service.search(
        space="memorable",
        query="Memorable reference",
        attribute_filter={"published_on": "2026-06-06"},
    )
    list_results = service.search(
        space="memorable",
        query="Memorable reference",
        attribute_filter={"aliases": ["demo", "walkthrough"]},
    )

    assert [result.source_id for result in number_results] == [
        "entity:video-reference"
    ]
    assert [result.source_id for result in date_results] == [
        "entity:video-reference"
    ]
    assert [result.source_id for result in list_results] == [
        "entity:video-reference"
    ]


def test_cli_search_attr_filter_surfaces_attributes(
    tmp_path,
    monkeypatch,
    capsys,
    cli_in_memory_context,
) -> None:
    """CLI search filters by Attribute and prints Entity Attributes."""
    import json
    from unittest.mock import patch

    from memorable.cli import main
    from memorable.retrieval.embeddings import FakeEmbeddingProvider

    memorable_dir = tmp_path / ".memorable"
    memorable_dir.mkdir()
    (memorable_dir / "memory.yaml").write_text(
        "version: 1\n"
        "space:\n"
        "  name: memorable\n"
        "entities:\n"
        "  - name: Reference\n"
        "    attributes:\n"
        "      - name: medium\n"
        "        type: string\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    with patch(
        "memorable.retrieval.embeddings.build_embedding_provider",
        return_value=FakeEmbeddingProvider(dimensions=384),
    ):
        assert (
            main(
                [
                    "remember",
                    "entity",
                    "--space",
                    "memorable",
                    "--id",
                    "entity:video-reference",
                    "--type",
                    "Reference",
                    "--name",
                    "Memorable demo video",
                    "--source",
                    SOURCE_ID,
                    "--at",
                    "2026-06-06T10:00:00Z",
                    "--attr",
                    "medium=video",
                ]
            )
            == 0
        )
        assert (
            main(
                [
                    "remember",
                    "entity",
                    "--space",
                    "memorable",
                    "--id",
                    "entity:article-reference",
                    "--type",
                    "Reference",
                    "--name",
                    "Memorable article reference",
                    "--source",
                    SOURCE_ID,
                    "--at",
                    "2026-06-06T10:05:00Z",
                    "--attr",
                    "medium=article",
                ]
            )
            == 0
        )
        assert main(["reindex", "--space", "memorable"]) == 0
        capsys.readouterr()

        exit_code = main(
            [
                "search",
                "--space",
                "memorable",
                "--query",
                "Memorable reference",
                "--attr",
                "medium=video",
            ]
        )

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert [result["source_id"] for result in output["results"]] == [
        "entity:video-reference"
    ]
    assert output["results"][0]["attributes"] == {"medium": "video"}


def test_mcp_search_attributes_filter_surfaces_attributes(
    tmp_path,
    monkeypatch,
) -> None:
    """MCP search filters by Attribute and returns Entity Attributes."""
    from unittest.mock import patch

    from memorable.core.context import default_context
    from memorable.mcp.server import (
        reindex_space_tool,
        remember_entity_tool,
        search_memory_tool,
        set_mcp_context,
    )
    from memorable.retrieval.embeddings import FakeEmbeddingProvider

    memorable_dir = tmp_path / ".memorable"
    memorable_dir.mkdir()
    (memorable_dir / "memory.yaml").write_text(
        "version: 1\n"
        "space:\n"
        "  name: memorable\n"
        "entities:\n"
        "  - name: Reference\n"
        "    attributes:\n"
        "      - name: medium\n"
        "        type: string\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    default_context.reset()
    set_mcp_context(default_context)

    with patch(
        "memorable.retrieval.embeddings.build_embedding_provider",
        return_value=FakeEmbeddingProvider(dimensions=384),
    ):
        remember_entity_tool(
            space="memorable",
            entity_id="entity:video-reference",
            entity_type="Reference",
            name="Memorable demo video",
            source=SOURCE_ID,
            at="2026-06-06T10:00:00Z",
            attributes={"medium": "video"},
        )
        remember_entity_tool(
            space="memorable",
            entity_id="entity:article-reference",
            entity_type="Reference",
            name="Memorable article reference",
            source=SOURCE_ID,
            at="2026-06-06T10:05:00Z",
            attributes={"medium": "article"},
        )
        reindex_space_tool(space="memorable")

        result = search_memory_tool(
            space="memorable",
            query="Memorable reference",
            attributes={"medium": "video"},
        )

    assert "error" not in result
    assert [record["source_id"] for record in result["results"]] == [
        "entity:video-reference"
    ]
    assert result["results"][0]["attributes"] == {"medium": "video"}


def test_search_attribute_filter_fails_loud_on_conflicting_declarations() -> None:
    """A conflicting Attribute declaration is not guessed during search."""
    import pytest

    from memorable.core.attributes import AttributeValidationError
    from memorable.core.profile import load_profile_from_yaml
    from memorable.core.repositories import (
        InMemoryDecisionRepository,
        InMemoryEntityRepository,
        InMemoryObservationRepository,
        InMemoryTaskRepository,
    )
    from memorable.retrieval.embeddings import FakeEmbeddingProvider
    from memorable.retrieval.service import HybridRetrievalService

    profile = load_profile_from_yaml(
        textwrap.dedent(
            """\
            version: 1
            space:
              name: memorable
            entities:
              - name: Reference
                attributes:
                  - name: rating
                    type: number
              - name: RatingScale
                attributes:
                  - name: rating
                    type: string
            """
        )
    )
    service = HybridRetrievalService(
        entity_repo=InMemoryEntityRepository(),
        decision_repo=InMemoryDecisionRepository(),
        task_repo=InMemoryTaskRepository(),
        observation_repo=InMemoryObservationRepository(),
        embedding_provider=FakeEmbeddingProvider(dimensions=32),
        profile=profile,
    )

    with pytest.raises(AttributeValidationError) as exc_info:
        service.search(
            space="memorable",
            query="rating",
            attribute_filter={"rating": "5"},
        )

    message = str(exc_info.value)
    assert "Attribute filter 'rating'" in message
    assert "conflicting types" in message
    assert "no Entity type scope" in message
