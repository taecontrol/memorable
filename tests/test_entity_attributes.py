"""Tests for typed durable Attributes on Entity types."""

from __future__ import annotations


def test_string_attributes_validate_and_omitted_are_allowed() -> None:
    """Declared string Attributes validate; omitted Attributes stay optional."""
    from memorable.core.attributes import (
        AttributeDeclaration,
        validate_attribute_values,
    )

    declared_attributes = (
        AttributeDeclaration(name="url", type="string"),
        AttributeDeclaration(name="medium", type="string"),
    )

    assert validate_attribute_values(
        declared_attributes,
        {"url": "https://example.test", "medium": "video"},
    ) == {"url": "https://example.test", "medium": "video"}
    assert validate_attribute_values(declared_attributes, None) == {}


def test_undeclared_attribute_name_fails_loud_with_declared_attributes() -> None:
    """Provided Attribute names must be declared on the Entity type."""
    import pytest

    from memorable.core.attributes import (
        AttributeDeclaration,
        AttributeValidationError,
        validate_attribute_values,
    )

    declared_attributes = (AttributeDeclaration(name="url", type="string"),)

    with pytest.raises(AttributeValidationError) as exc_info:
        validate_attribute_values(declared_attributes, {"medium": "video"})

    message = str(exc_info.value)
    assert "Attribute 'medium' is not declared" in message
    assert "url" in message


def test_string_attribute_rejects_non_string_value() -> None:
    """A string Attribute only accepts string values in this slice."""
    import pytest

    from memorable.core.attributes import (
        AttributeDeclaration,
        AttributeValidationError,
        validate_attribute_values,
    )

    declared_attributes = (AttributeDeclaration(name="url", type="string"),)

    with pytest.raises(AttributeValidationError) as exc_info:
        validate_attribute_values(declared_attributes, {"url": 123})

    message = str(exc_info.value)
    assert "Attribute 'url'" in message
    assert "string" in message


def test_validator_rejects_unsupported_attribute_type() -> None:
    """The validator fails loud for types outside the v1 type set."""
    import pytest

    from memorable.core.attributes import (
        AttributeDeclaration,
        AttributeValidationError,
        validate_attribute_values,
    )

    declared_attributes = (AttributeDeclaration(name="active", type="boolean"),)

    with pytest.raises(AttributeValidationError) as exc_info:
        validate_attribute_values(declared_attributes, {"active": "true"})

    message = str(exc_info.value)
    assert "active" in message
    assert "boolean" in message
    assert "string" in message
    assert "number" in message
    assert "date" in message
    assert "list[string]" in message


def test_number_attribute_coerces_strings_and_accepts_native_numbers() -> None:
    """A number Attribute stores int and float values, including string input."""
    from memorable.core.attributes import (
        AttributeDeclaration,
        validate_attribute_values,
    )

    declared_attributes = (
        AttributeDeclaration(name="rating", type="number"),
        AttributeDeclaration(name="score", type="number"),
        AttributeDeclaration(name="confidence", type="number"),
    )

    assert validate_attribute_values(
        declared_attributes,
        {"rating": "5", "score": "4.5", "confidence": 0.75},
    ) == {"rating": 5, "score": 4.5, "confidence": 0.75}


def test_number_attribute_rejects_malformed_values() -> None:
    """A number Attribute rejects malformed and non-finite values."""
    import pytest

    from memorable.core.attributes import (
        AttributeDeclaration,
        AttributeValidationError,
        validate_attribute_values,
    )

    declared_attributes = (AttributeDeclaration(name="rating", type="number"),)

    for value in ("five", True, "NaN"):
        with pytest.raises(AttributeValidationError) as exc_info:
            validate_attribute_values(declared_attributes, {"rating": value})

        message = str(exc_info.value)
        assert "Attribute 'rating'" in message
        assert "number" in message


def test_date_attribute_coerces_iso_strings_and_accepts_native_dates() -> None:
    """A date Attribute stores a date value from ISO string or native date input."""
    from datetime import date

    from memorable.core.attributes import (
        AttributeDeclaration,
        validate_attribute_values,
    )

    declared_attributes = (
        AttributeDeclaration(name="published_on", type="date"),
        AttributeDeclaration(name="archived_on", type="date"),
    )

    assert validate_attribute_values(
        declared_attributes,
        {"published_on": "2026-06-06", "archived_on": date(2026, 7, 1)},
    ) == {
        "published_on": date(2026, 6, 6),
        "archived_on": date(2026, 7, 1),
    }


def test_date_attribute_rejects_malformed_values() -> None:
    """A date Attribute rejects non-ISO and non-date values."""
    import pytest

    from memorable.core.attributes import (
        AttributeDeclaration,
        AttributeValidationError,
        validate_attribute_values,
    )

    declared_attributes = (AttributeDeclaration(name="published_on", type="date"),)

    for value in ("06/06/2026", 20260606):
        with pytest.raises(AttributeValidationError) as exc_info:
            validate_attribute_values(declared_attributes, {"published_on": value})

        message = str(exc_info.value)
        assert "Attribute 'published_on'" in message
        assert "ISO date" in message


def test_list_string_attribute_accepts_empty_and_multi_element_lists() -> None:
    """A list[string] Attribute stores empty and multi-element string lists."""
    from memorable.core.attributes import (
        AttributeDeclaration,
        validate_attribute_values,
    )

    declared_attributes = (
        AttributeDeclaration(name="aliases", type="list[string]"),
        AttributeDeclaration(name="tags", type="list[string]"),
    )

    assert validate_attribute_values(
        declared_attributes,
        {"aliases": [], "tags": ["video", "training"]},
    ) == {"aliases": [], "tags": ["video", "training"]}


def test_list_string_attribute_rejects_non_list_or_non_string_members() -> None:
    """A list[string] Attribute rejects non-lists and non-string members."""
    import pytest

    from memorable.core.attributes import (
        AttributeDeclaration,
        AttributeValidationError,
        validate_attribute_values,
    )

    declared_attributes = (AttributeDeclaration(name="aliases", type="list[string]"),)

    for value in ("Memorable", ["Memorable", 5]):
        with pytest.raises(AttributeValidationError) as exc_info:
            validate_attribute_values(declared_attributes, {"aliases": value})

        message = str(exc_info.value)
        assert "Attribute 'aliases'" in message
        assert "list[string]" in message


def test_profile_parses_string_attributes_and_summary_surfaces_them() -> None:
    """A MemoryProfile Entity type can declare string Attributes for inspect."""
    import textwrap

    from memorable.core.profile import load_profile_from_yaml, profile_summary

    profile = load_profile_from_yaml(
        textwrap.dedent(
            """\
            version: 1
            space:
              name: memorable
            entities:
              - name: Reference
                description: A remembered external reference
                attributes:
                  - name: url
                    type: string
                  - name: medium
                    type: string
            """
        )
    )

    assert [
        (attribute.name, attribute.type) for attribute in profile.entities[0].attributes
    ] == [
        ("url", "string"),
        ("medium", "string"),
    ]
    assert profile_summary(profile)["entities"] == [
        {
            "name": "Reference",
            "description": "A remembered external reference",
            "attributes": [
                {"name": "url", "type": "string"},
                {"name": "medium", "type": "string"},
            ],
        }
    ]


def test_profile_parses_full_v1_attribute_type_set() -> None:
    """A MemoryProfile Entity type can declare every v1 Attribute type."""
    import textwrap

    from memorable.core.profile import load_profile_from_yaml, profile_summary

    profile = load_profile_from_yaml(
        textwrap.dedent(
            """\
            version: 1
            space:
              name: memorable
            entities:
              - name: Reference
                attributes:
                  - name: url
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

    assert [
        (attribute.name, attribute.type) for attribute in profile.entities[0].attributes
    ] == [
        ("url", "string"),
        ("rating", "number"),
        ("published_on", "date"),
        ("aliases", "list[string]"),
    ]
    assert profile_summary(profile)["entities"][0]["attributes"] == [
        {"name": "url", "type": "string"},
        {"name": "rating", "type": "number"},
        {"name": "published_on", "type": "date"},
        {"name": "aliases", "type": "list[string]"},
    ]


def test_profile_rejects_unknown_attribute_type() -> None:
    """MemoryProfile v1 fails loud for unsupported Attribute types."""
    import textwrap

    import pytest

    from memorable.core.profile import ProfileValidationError, load_profile_from_yaml

    yaml_text = textwrap.dedent(
        """\
        version: 1
        space:
          name: memorable
        entities:
          - name: Reference
            attributes:
              - name: active
                type: boolean
        """
    )

    with pytest.raises(ProfileValidationError) as exc_info:
        load_profile_from_yaml(yaml_text)

    message = str(exc_info.value)
    assert "Attribute 'active'" in message
    assert "boolean" in message
    assert "string" in message
    assert "number" in message
    assert "date" in message
    assert "list[string]" in message


def test_profile_rejects_unknown_key_under_attribute_declaration() -> None:
    """Attribute declarations fail loud on unsupported keys."""
    import textwrap

    import pytest

    from memorable.core.profile import ProfileValidationError, load_profile_from_yaml

    yaml_text = textwrap.dedent(
        """\
        version: 1
        space:
          name: memorable
        entities:
          - name: Reference
            attributes:
              - name: url
                type: string
                required: true
        """
    )

    with pytest.raises(ProfileValidationError) as exc_info:
        load_profile_from_yaml(yaml_text)

    message = str(exc_info.value)
    assert "Attribute declaration" in message
    assert "required" in message
    assert "unrecognized key" in message


def test_profile_rejects_attribute_declaration_without_name() -> None:
    """An Attribute declaration must name the Attribute."""
    import textwrap

    import pytest

    from memorable.core.profile import ProfileValidationError, load_profile_from_yaml

    yaml_text = textwrap.dedent(
        """\
        version: 1
        space:
          name: memorable
        entities:
          - name: Reference
            attributes:
              - type: string
        """
    )

    with pytest.raises(ProfileValidationError) as exc_info:
        load_profile_from_yaml(yaml_text)

    message = str(exc_info.value)
    assert "Attribute declaration" in message
    assert "name" in message


def test_entity_carries_immutable_attributes_mapping() -> None:
    """An Entity can carry durable Attributes without exposing mutation."""
    import pytest

    from memorable.core.models import Entity

    entity = Entity(
        id="entity:reference",
        entity_type="Reference",
        name="Example reference",
        space="memorable",
        attributes={"url": "https://example.test"},
    )

    assert entity.attributes == {"url": "https://example.test"}
    with pytest.raises(TypeError):
        entity.attributes["url"] = "https://other.test"

    plain = Entity(
        id="entity:plain",
        entity_type="Reference",
        name="Plain reference",
        space="memorable",
    )
    assert plain.attributes == {}


def test_service_stores_and_returns_declared_string_attributes() -> None:
    """RememberEntityService validates declared Attributes before persistence."""
    import textwrap
    from datetime import UTC, datetime

    from memorable.core.application import RememberEntityService
    from memorable.core.profile import load_profile_from_yaml
    from memorable.core.repositories import InMemoryEntityRepository

    profile = load_profile_from_yaml(
        textwrap.dedent(
            """\
            version: 1
            space:
              name: memorable
            entities:
              - name: Reference
                attributes:
                  - name: url
                    type: string
            """
        )
    )
    repo = InMemoryEntityRepository()
    service = RememberEntityService(repository=repo, profile=profile)

    result = service.remember(
        space="memorable",
        entity_id="entity:reference",
        entity_type="Reference",
        name="Example reference",
        source_id="source:test",
        at=datetime(2026, 6, 6, 10, 0, tzinfo=UTC),
        attributes={"url": "https://example.test"},
    )

    assert result.entity.attributes == {"url": "https://example.test"}
    stored = repo.get(space="memorable", entity_id="entity:reference")
    assert stored is not None
    assert stored.attributes == {"url": "https://example.test"}


def test_service_stores_and_returns_full_v1_attribute_types() -> None:
    """RememberEntityService returns typed Attribute values after validation."""
    import textwrap
    from datetime import UTC, date, datetime

    from memorable.core.application import RememberEntityService
    from memorable.core.profile import load_profile_from_yaml
    from memorable.core.repositories import InMemoryEntityRepository

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
                  - name: published_on
                    type: date
                  - name: aliases
                    type: list[string]
            """
        )
    )
    repo = InMemoryEntityRepository()
    service = RememberEntityService(repository=repo, profile=profile)

    result = service.remember(
        space="memorable",
        entity_id="entity:reference",
        entity_type="Reference",
        name="Example reference",
        source_id="source:test",
        at=datetime(2026, 6, 6, 10, 0, tzinfo=UTC),
        attributes={
            "rating": "5",
            "published_on": "2026-06-06",
            "aliases": ["Memorable", "GraphRAG"],
        },
    )

    assert result.entity.attributes == {
        "rating": 5,
        "published_on": date(2026, 6, 6),
        "aliases": ["Memorable", "GraphRAG"],
    }
    stored = repo.get(space="memorable", entity_id="entity:reference")
    assert stored is not None
    assert stored.attributes == {
        "rating": 5,
        "published_on": date(2026, 6, 6),
        "aliases": ["Memorable", "GraphRAG"],
    }


def test_remember_entity_service_rejects_undeclared_attribute() -> None:
    """Service writes fail loud when provided Attributes are undeclared."""
    import textwrap
    from datetime import UTC, datetime

    import pytest

    from memorable.core.application import RememberEntityService
    from memorable.core.attributes import AttributeValidationError
    from memorable.core.profile import load_profile_from_yaml
    from memorable.core.repositories import InMemoryEntityRepository

    profile = load_profile_from_yaml(
        textwrap.dedent(
            """\
            version: 1
            space:
              name: memorable
            entities:
              - name: Reference
                attributes:
                  - name: url
                    type: string
            """
        )
    )
    service = RememberEntityService(
        repository=InMemoryEntityRepository(),
        profile=profile,
    )

    with pytest.raises(AttributeValidationError) as exc_info:
        service.remember(
            space="memorable",
            entity_id="entity:reference",
            entity_type="Reference",
            name="Example reference",
            source_id="source:test",
            at=datetime(2026, 6, 6, 10, 0, tzinfo=UTC),
            attributes={"medium": "video"},
        )

    message = str(exc_info.value)
    assert "Attribute 'medium' is not declared" in message
    assert "url" in message


def test_omitted_attributes_preserve_existing_attributes_on_upsert() -> None:
    """Re-remembering an Entity without Attributes is not a wipe."""
    import textwrap
    from datetime import UTC, datetime

    from memorable.core.application import RememberEntityService
    from memorable.core.profile import load_profile_from_yaml
    from memorable.core.repositories import InMemoryEntityRepository

    profile = load_profile_from_yaml(
        textwrap.dedent(
            """\
            version: 1
            space:
              name: memorable
            entities:
              - name: Reference
                attributes:
                  - name: url
                    type: string
                  - name: medium
                    type: string
            """
        )
    )
    repo = InMemoryEntityRepository()
    service = RememberEntityService(repository=repo, profile=profile)
    at = datetime(2026, 6, 6, 10, 0, tzinfo=UTC)

    service.remember(
        space="memorable",
        entity_id="entity:reference",
        entity_type="Reference",
        name="Example reference",
        source_id="source:test",
        at=at,
        attributes={"url": "https://example.test", "medium": "video"},
    )
    result = service.remember(
        space="memorable",
        entity_id="entity:reference",
        entity_type="Reference",
        name="Example reference renamed",
        source_id="source:test",
        at=at,
    )

    assert result.entity.attributes == {
        "url": "https://example.test",
        "medium": "video",
    }
    stored = repo.get(space="memorable", entity_id="entity:reference")
    assert stored is not None
    assert stored.attributes == {
        "url": "https://example.test",
        "medium": "video",
    }


def test_provided_attributes_replace_existing_attributes_on_upsert() -> None:
    """An explicit Attribute set replaces the stored Attribute set."""
    import textwrap
    from datetime import UTC, datetime

    from memorable.core.application import RememberEntityService
    from memorable.core.profile import load_profile_from_yaml
    from memorable.core.repositories import InMemoryEntityRepository

    profile = load_profile_from_yaml(
        textwrap.dedent(
            """\
            version: 1
            space:
              name: memorable
            entities:
              - name: Reference
                attributes:
                  - name: url
                    type: string
                  - name: medium
                    type: string
            """
        )
    )
    repo = InMemoryEntityRepository()
    service = RememberEntityService(repository=repo, profile=profile)
    at = datetime(2026, 6, 6, 10, 0, tzinfo=UTC)

    service.remember(
        space="memorable",
        entity_id="entity:reference",
        entity_type="Reference",
        name="Example reference",
        source_id="source:test",
        at=at,
        attributes={"url": "https://example.test", "medium": "video"},
    )
    result = service.remember(
        space="memorable",
        entity_id="entity:reference",
        entity_type="Reference",
        name="Example reference",
        source_id="source:test",
        at=at,
        attributes={"medium": "article"},
    )

    assert result.entity.attributes == {"medium": "article"}
    stored = repo.get(space="memorable", entity_id="entity:reference")
    assert stored is not None
    assert stored.attributes == {"medium": "article"}


def test_cli_remember_entity_attr_flag_writes_and_echoes_attributes(
    tmp_path,
    monkeypatch,
    capsys,
    cli_in_memory_context,
) -> None:
    """CLI remember entity accepts repeatable --attr name=value for Attributes."""
    import json

    from memorable.cli import main

    memorable_dir = tmp_path / ".memorable"
    memorable_dir.mkdir()
    (memorable_dir / "memory.yaml").write_text(
        "version: 1\n"
        "space:\n"
        "  name: memorable\n"
        "entities:\n"
        "  - name: Reference\n"
        "    attributes:\n"
        "      - name: url\n"
        "        type: string\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    exit_code = main(
        [
            "remember",
            "entity",
            "--id",
            "entity:reference",
            "--type",
            "Reference",
            "--name",
            "Example reference",
            "--source",
            "source:test",
            "--at",
            "2026-06-06T10:00:00Z",
            "--attr",
            "url=https://example.test",
        ]
    )

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["attributes"] == {"url": "https://example.test"}
    stored = cli_in_memory_context.entity_repo.get(
        space="memorable",
        entity_id="entity:reference",
    )
    assert stored is not None
    assert stored.attributes == {"url": "https://example.test"}


def test_cli_remember_entity_attr_flag_parses_full_v1_types(
    tmp_path,
    monkeypatch,
    capsys,
    cli_in_memory_context,
) -> None:
    """CLI remember entity parses number, date, and list[string] Attributes."""
    import json
    from datetime import date

    from memorable.cli import main

    memorable_dir = tmp_path / ".memorable"
    memorable_dir.mkdir()
    (memorable_dir / "memory.yaml").write_text(
        "version: 1\n"
        "space:\n"
        "  name: memorable\n"
        "entities:\n"
        "  - name: Reference\n"
        "    attributes:\n"
        "      - name: rating\n"
        "        type: number\n"
        "      - name: published_on\n"
        "        type: date\n"
        "      - name: aliases\n"
        "        type: list[string]\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    exit_code = main(
        [
            "remember",
            "entity",
            "--id",
            "entity:reference",
            "--type",
            "Reference",
            "--name",
            "Example reference",
            "--source",
            "source:test",
            "--at",
            "2026-06-06T10:00:00Z",
            "--attr",
            "rating=5",
            "--attr",
            "published_on=2026-06-06",
            "--attr",
            "aliases=Memorable",
            "--attr",
            "aliases=GraphRAG",
        ]
    )

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["attributes"] == {
        "rating": 5,
        "published_on": "2026-06-06",
        "aliases": ["Memorable", "GraphRAG"],
    }
    stored = cli_in_memory_context.entity_repo.get(
        space="memorable",
        entity_id="entity:reference",
    )
    assert stored is not None
    assert stored.attributes == {
        "rating": 5,
        "published_on": date(2026, 6, 6),
        "aliases": ["Memorable", "GraphRAG"],
    }


def test_mcp_remember_entity_attributes_param_accepts_full_v1_types(
    tmp_path,
    monkeypatch,
) -> None:
    """MCP remember Entity accepts native JSON Attribute values and ISO dates."""
    from datetime import date

    from memorable.core.context import default_context
    from memorable.mcp.server import remember_entity_tool, set_mcp_context

    memorable_dir = tmp_path / ".memorable"
    memorable_dir.mkdir()
    (memorable_dir / "memory.yaml").write_text(
        "version: 1\n"
        "space:\n"
        "  name: memorable\n"
        "entities:\n"
        "  - name: Reference\n"
        "    attributes:\n"
        "      - name: rating\n"
        "        type: number\n"
        "      - name: published_on\n"
        "        type: date\n"
        "      - name: aliases\n"
        "        type: list[string]\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    default_context.reset()
    set_mcp_context(default_context)

    result = remember_entity_tool(
        space="memorable",
        entity_id="entity:reference",
        entity_type="Reference",
        name="Example reference",
        source="source:test",
        at="2026-06-06T10:00:00Z",
        attributes={
            "rating": 4.5,
            "published_on": "2026-06-06",
            "aliases": [],
        },
    )

    assert "error" not in result
    assert result["attributes"] == {
        "rating": 4.5,
        "published_on": "2026-06-06",
        "aliases": [],
    }
    stored = default_context.entity_repo.get(
        space="memorable",
        entity_id="entity:reference",
    )
    assert stored is not None
    assert stored.attributes == {
        "rating": 4.5,
        "published_on": date(2026, 6, 6),
        "aliases": [],
    }


def test_mcp_remember_entity_attributes_param_writes_and_echoes_attributes(
    tmp_path,
    monkeypatch,
) -> None:
    """MCP remember Entity accepts an attributes mapping."""
    from memorable.core.context import default_context
    from memorable.mcp.server import remember_entity_tool, set_mcp_context

    memorable_dir = tmp_path / ".memorable"
    memorable_dir.mkdir()
    (memorable_dir / "memory.yaml").write_text(
        "version: 1\n"
        "space:\n"
        "  name: memorable\n"
        "entities:\n"
        "  - name: Reference\n"
        "    attributes:\n"
        "      - name: url\n"
        "        type: string\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    default_context.reset()
    set_mcp_context(default_context)

    result = remember_entity_tool(
        space="memorable",
        entity_id="entity:reference",
        entity_type="Reference",
        name="Example reference",
        source="source:test",
        at="2026-06-06T10:00:00Z",
        attributes={"url": "https://example.test"},
    )

    assert "error" not in result
    assert result["attributes"] == {"url": "https://example.test"}
    stored = default_context.entity_repo.get(
        space="memorable",
        entity_id="entity:reference",
    )
    assert stored is not None
    assert stored.attributes == {"url": "https://example.test"}
