"""Tests for MemoryProfile loading, validation, and MemorySpace initialization."""

from __future__ import annotations

import textwrap

import pytest

VALID_PROFILE_YAML = textwrap.dedent("""\
    version: 1

    space:
      name: memorable
      description: Agent memory system design

    write_policy:
      default: auto
      sensitive: suggest

    entities:
      - name: Project
      - name: Component

    records:
      - name: ArchitectureDecision
        extends: Decision
      - name: OpenQuestion
        extends: MemoryRecord
""")


def test_load_valid_profile_from_yaml() -> None:
    """A valid YAML string produces a MemoryProfile with expected fields."""
    from memorable.core.profile import load_profile_from_yaml

    profile = load_profile_from_yaml(VALID_PROFILE_YAML)

    assert profile.version == 1
    assert profile.space.name == "memorable"
    assert profile.space.description == "Agent memory system design"
    assert profile.write_policy.default == "auto"
    assert profile.write_policy.sensitive == "suggest"
    assert len(profile.entities) == 2
    assert profile.entities[0].name == "Project"
    assert len(profile.records) == 2
    assert profile.records[0].name == "ArchitectureDecision"
    assert profile.records[0].extends == "Decision"


def test_missing_version_raises_validation_error() -> None:
    """A profile without a version field produces an actionable error."""
    from memorable.core.profile import ProfileValidationError, load_profile_from_yaml

    with pytest.raises(ProfileValidationError, match="version"):
        load_profile_from_yaml("space:\n  name: test\n")


def test_unsupported_version_raises_validation_error() -> None:
    """A profile with an unsupported version produces an actionable error."""
    from memorable.core.profile import ProfileValidationError, load_profile_from_yaml

    yaml_text = "version: 99\nspace:\n  name: test\n"
    with pytest.raises(ProfileValidationError, match="version"):
        load_profile_from_yaml(yaml_text)


def test_missing_space_name_raises_validation_error() -> None:
    """A profile without a space name produces an actionable error."""
    from memorable.core.profile import ProfileValidationError, load_profile_from_yaml

    yaml_text = "version: 1\nspace:\n  description: no name\n"
    with pytest.raises(ProfileValidationError, match="space.name"):
        load_profile_from_yaml(yaml_text)


def test_empty_entity_name_raises_validation_error() -> None:
    """An entity with an empty name produces an actionable error."""
    from memorable.core.profile import ProfileValidationError, load_profile_from_yaml

    yaml_text = "version: 1\nspace:\n  name: test\nentities:\n  - name: ''\n"
    with pytest.raises(ProfileValidationError, match="non-empty 'name'"):
        load_profile_from_yaml(yaml_text)


def test_record_with_invalid_extends_raises_validation_error() -> None:
    """A record extending an unrecognized kernel type produces an actionable error."""
    from memorable.core.profile import ProfileValidationError, load_profile_from_yaml

    yaml_text = (
        "version: 1\nspace:\n  name: test\n"
        "records:\n  - name: Bad\n    extends: NonExistentType\n"
    )
    with pytest.raises(ProfileValidationError, match="not a recognized kernel type"):
        load_profile_from_yaml(yaml_text)


def test_validation_errors_contain_no_storage_vocabulary() -> None:
    """Error messages must not leak storage terms like node, edge, index."""
    from memorable.core.profile import ProfileValidationError, load_profile_from_yaml

    storage_terms = {"node", "edge", "index", "vertex", "graph", "database", "table"}

    bad_yamls = [
        "version: 99\nspace:\n  name: x\n",
        "version: 1\nspace:\n  description: x\n",
        "version: 1\nspace:\n  name: x\nrecords:\n  - name: X\n    extends: Bogus\n",
    ]

    for yaml_text in bad_yamls:
        with pytest.raises(ProfileValidationError) as exc_info:
            load_profile_from_yaml(yaml_text)
        message_lower = str(exc_info.value).lower()
        for term in storage_terms:
            assert term not in message_lower, (
                f"Storage vocabulary '{term}' found in error: {exc_info.value}"
            )


class TestInitService:
    """Tests for the InitService that initializes a MemorySpace."""

    def _make_repo(self):
        from memorable.core.repositories import make_memory_space_repository

        return make_memory_space_repository()

    def test_init_creates_memory_space_from_profile(self) -> None:
        """InitService creates a MemorySpace using the profile's space name."""
        from memorable.core.application import InitService

        repo = self._make_repo()
        service = InitService(repository=repo)

        result = service.initialize(VALID_PROFILE_YAML)

        assert result.space.name == "memorable"
        assert result.profile.version == 1
        assert repo.exists("memorable")

    def test_init_returns_existing_space_if_already_initialized(self) -> None:
        """InitService returns the existing space if it already exists."""
        from memorable.core.application import InitService

        repo = self._make_repo()
        repo.create_space("memorable")
        service = InitService(repository=repo)

        result = service.initialize(VALID_PROFILE_YAML)

        assert result.space.name == "memorable"
        assert result.already_existed is True

    def test_init_propagates_validation_errors(self) -> None:
        """InitService raises ProfileValidationError for invalid profiles."""
        from memorable.core.application import InitService
        from memorable.core.profile import ProfileValidationError

        repo = self._make_repo()
        service = InitService(repository=repo)

        with pytest.raises(ProfileValidationError):
            service.initialize("version: 99\nspace:\n  name: x\n")


class TestCLIInit:
    """Tests for the `memorable init` CLI command."""

    def test_init_command_succeeds_with_valid_profile(self, tmp_path) -> None:
        """memorable init reads .memorable/memory.yaml and reports success."""
        from memorable.cli import main

        profile_dir = tmp_path / ".memorable"
        profile_dir.mkdir()
        (profile_dir / "memory.yaml").write_text(VALID_PROFILE_YAML)

        exit_code = main(["init", "--path", str(tmp_path)])
        assert exit_code == 0

    def test_init_command_fails_with_invalid_profile(self, tmp_path, capsys) -> None:
        """memorable init reports validation errors to stderr."""
        from memorable.cli import main

        profile_dir = tmp_path / ".memorable"
        profile_dir.mkdir()
        (profile_dir / "memory.yaml").write_text("version: 99\nspace:\n  name: x\n")

        exit_code = main(["init", "--path", str(tmp_path)])
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "version" in captured.err.lower()

    def test_init_command_fails_when_no_profile_exists(self, tmp_path, capsys) -> None:
        """memorable init reports missing profile file."""
        from memorable.cli import main

        exit_code = main(["init", "--path", str(tmp_path)])
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "memory.yaml" in captured.err


class TestMCPInit:
    """Tests for MCP tool that initializes/inspects a MemorySpace."""

    def test_mcp_init_space_returns_space_info(self, tmp_path) -> None:
        """MCP init_space_tool initializes a space using the same service."""
        from memorable.core.context import default_context
        from memorable.mcp.server import init_space_tool

        profile_dir = tmp_path / ".memorable"
        profile_dir.mkdir()
        (profile_dir / "memory.yaml").write_text(VALID_PROFILE_YAML)

        default_context.reset()
        try:
            result = init_space_tool(str(tmp_path))

            assert result["space"] == "memorable"
            assert result["status"] == "initialized"
            assert result["profile_version"] == 1
        finally:
            default_context.reset()

    def test_mcp_init_space_returns_error_for_invalid_profile(self, tmp_path) -> None:
        """MCP init_space_tool returns error info for invalid profiles."""
        from memorable.mcp.server import init_space_tool

        profile_dir = tmp_path / ".memorable"
        profile_dir.mkdir()
        (profile_dir / "memory.yaml").write_text("version: 99\nspace:\n  name: x\n")

        result = init_space_tool(str(tmp_path))

        assert "error" in result
        assert "version" in result["error"].lower()

    def test_mcp_inspect_space_returns_profile_summary(self, tmp_path) -> None:
        """MCP inspect_space_tool returns profile info without initializing."""
        from memorable.mcp.server import inspect_space_tool

        profile_dir = tmp_path / ".memorable"
        profile_dir.mkdir()
        (profile_dir / "memory.yaml").write_text(VALID_PROFILE_YAML)

        result = inspect_space_tool(str(tmp_path))

        assert result["space_name"] == "memorable"
        assert result["entity_count"] == 2
        assert result["record_count"] == 2
        assert result["write_policy_default"] == "auto"
