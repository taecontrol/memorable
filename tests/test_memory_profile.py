"""Tests for MemoryProfile loading, validation, and MemorySpace initialization."""

from __future__ import annotations

import textwrap

import pytest

VALID_PROFILE_YAML = textwrap.dedent("""\
    version: 1

    space:
      name: memorable
      description: Agent memory system design

    entities:
      - name: Project
      - name: Component

    records:
      - name: ArchitectureDecision
        extends: Decision
      - name: OpenQuestion
        extends: Observation
""")

PROFILE_WITH_STRAY_WRITE_POLICY_YAML = textwrap.dedent("""\
    version: 1

    space:
      name: memorable
      description: Agent memory system design

    write_policy:
      default: auto
      sensitive: suggest

    entities:
      - name: Project
""")


def test_load_valid_profile_from_yaml() -> None:
    """A valid YAML string produces a MemoryProfile with expected fields."""
    from memorable.core.profile import load_profile_from_yaml

    profile = load_profile_from_yaml(VALID_PROFILE_YAML)

    assert profile.version == 1
    assert profile.space.name == "memorable"
    assert profile.space.description == "Agent memory system design"
    assert not hasattr(profile, "write_policy")
    assert len(profile.entities) == 2
    assert profile.entities[0].name == "Project"
    assert len(profile.records) == 2
    assert profile.records[0].name == "ArchitectureDecision"
    assert profile.records[0].extends == "Decision"


def test_profile_with_stray_write_policy_raises_validation_error() -> None:
    """A hand-written write_policy block is rejected as removed v1 config."""
    from memorable.core.profile import ProfileValidationError, load_profile_from_yaml

    with pytest.raises(ProfileValidationError) as exc_info:
        load_profile_from_yaml(PROFILE_WITH_STRAY_WRITE_POLICY_YAML)

    assert "ADR-0014" in str(exc_info.value)
    assert "removed" in str(exc_info.value)


def test_profile_with_unknown_top_level_key_raises_validation_error() -> None:
    """A profile with an unsupported top-level key is rejected."""
    from memorable.core.profile import ProfileValidationError, load_profile_from_yaml

    yaml_text = textwrap.dedent("""\
        version: 1
        space:
          name: memorable
        imaginary: true
    """)

    with pytest.raises(ProfileValidationError) as exc_info:
        load_profile_from_yaml(yaml_text)

    assert "unrecognized key" in str(exc_info.value)


@pytest.mark.parametrize("key", ["metrics", "workflows", "common_queries"])
def test_profile_with_target_design_key_raises_validation_error(key: str) -> None:
    """Target-design profile keys are rejected until MemoryProfile parses them."""
    from memorable.core.profile import ProfileValidationError, load_profile_from_yaml

    yaml_text = textwrap.dedent(f"""\
        version: 1
        space:
          name: memorable
        {key}: []
    """)

    with pytest.raises(ProfileValidationError) as exc_info:
        load_profile_from_yaml(yaml_text)

    message = str(exc_info.value)
    assert key in message
    assert "target-design" in message


def test_profile_with_unknown_space_key_raises_validation_error() -> None:
    """A profile with an unsupported space key is rejected."""
    from memorable.core.profile import ProfileValidationError, load_profile_from_yaml

    yaml_text = textwrap.dedent("""\
        version: 1
        space:
          name: memorable
          owner: human
    """)

    with pytest.raises(ProfileValidationError) as exc_info:
        load_profile_from_yaml(yaml_text)

    assert "unrecognized key" in str(exc_info.value)


@pytest.mark.parametrize(
    ("section", "extra"),
    [
        ("entities", "aliases: []"),
        ("relations", "inverse: blocks"),
        ("records", "retention: durable"),
    ],
)
def test_profile_with_unknown_declaration_key_raises_validation_error(
    section: str, extra: str
) -> None:
    """Entity, relation, and record declarations reject unsupported keys."""
    from memorable.core.profile import ProfileValidationError, load_profile_from_yaml

    entry_lines = ["  - name: ProjectArtifact"]
    if section == "records":
        entry_lines.append("    extends: Decision")
    entry_lines.append(f"    {extra}")
    yaml_text = textwrap.dedent(f"""\
        version: 1
        space:
          name: memorable
        {section}:
    """) + "\n".join(entry_lines)

    with pytest.raises(ProfileValidationError) as exc_info:
        load_profile_from_yaml(yaml_text)

    assert "unrecognized key" in str(exc_info.value)


def test_profile_with_supported_description_keys_loads() -> None:
    """Descriptions are accepted everywhere the v1 profile schema allows them."""
    from memorable.core.profile import load_profile_from_yaml

    yaml_text = textwrap.dedent("""\
        version: 1
        space:
          name: memorable
          description: Agent memory system design
        entities:
          - name: Project
            description: A remembered project
        relations:
          - name: depends_on
            description: Dependency between entities
        records:
          - name: ArchitectureDecision
            extends: Decision
            description: Chosen architecture direction
    """)

    profile = load_profile_from_yaml(yaml_text)

    assert profile.space.name == "memorable"
    assert profile.entities[0].name == "Project"
    assert profile.relations[0].name == "depends_on"
    assert profile.records[0].name == "ArchitectureDecision"


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
    with pytest.raises(ProfileValidationError):
        load_profile_from_yaml(yaml_text)


def test_record_without_extends_raises_validation_error() -> None:
    """A record declaration must name the Writable Record Type it extends."""
    from memorable.core.profile import ProfileValidationError, load_profile_from_yaml

    yaml_text = "version: 1\nspace:\n  name: test\nrecords:\n  - name: MissingBase\n"

    with pytest.raises(ProfileValidationError):
        load_profile_from_yaml(yaml_text)


@pytest.mark.parametrize("extends", ["Decision", "Observation", "Task"])
def test_record_extending_writable_record_type_loads(extends: str) -> None:
    """A record may extend any Writable Record Type."""
    from memorable.core.profile import load_profile_from_yaml

    yaml_text = textwrap.dedent(f"""\
        version: 1
        space:
          name: test
        records:
          - name: Custom{extends}
            extends: {extends}
    """)

    profile = load_profile_from_yaml(yaml_text)

    assert profile.records[0].extends == extends


@pytest.mark.parametrize(
    "extends",
    ["Measurement", "Event", "Evidence", "DerivedMemory", "Relation", "MemoryRecord"],
)
def test_record_extending_non_writable_type_raises_validation_error(
    extends: str,
) -> None:
    """A record may not extend a kernel term without a record write path."""
    from memorable.core.profile import ProfileValidationError, load_profile_from_yaml

    yaml_text = textwrap.dedent(f"""\
        version: 1
        space:
          name: test
        records:
          - name: DeadSchemaRecord
            extends: {extends}
    """)

    with pytest.raises(ProfileValidationError) as exc_info:
        load_profile_from_yaml(yaml_text)

    message = str(exc_info.value)
    assert "Decision" in message
    assert "Observation" in message
    assert "Task" in message


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
        from memorable.core.repositories import InMemoryMemorySpaceRepository

        return InMemoryMemorySpaceRepository()

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
    """Tests for the `memorable init` CLI command.

    These tests mock the production context factory since no real Neo4j
    is available in unit tests.
    """

    def test_init_command_succeeds_with_valid_profile(self, tmp_path) -> None:
        """memorable init reads .memorable/memory.yaml and reports success."""
        from unittest.mock import MagicMock, patch

        from memorable.cli import main
        from memorable.config import RuntimeConfig
        from memorable.core.context import ApplicationContext

        profile_dir = tmp_path / ".memorable"
        profile_dir.mkdir()
        (profile_dir / "memory.yaml").write_text(VALID_PROFILE_YAML)

        ctx = ApplicationContext()
        mock_driver = MagicMock()

        with (
            patch(
                "memorable.cli.build_production_context",
                return_value=(ctx, mock_driver),
            ),
            patch("memorable.cli.ensure_all_constraints"),
            patch("memorable.cli.load_runtime_config", return_value=RuntimeConfig()),
        ):
            exit_code = main(["init", "--path", str(tmp_path)])
        assert exit_code == 0

    def test_init_command_fails_with_invalid_profile(self, tmp_path, capsys) -> None:
        """memorable init reports validation errors to stderr."""
        from unittest.mock import MagicMock, patch

        from memorable.cli import main
        from memorable.config import RuntimeConfig
        from memorable.core.context import ApplicationContext

        profile_dir = tmp_path / ".memorable"
        profile_dir.mkdir()
        (profile_dir / "memory.yaml").write_text("version: 99\nspace:\n  name: x\n")

        ctx = ApplicationContext()
        mock_driver = MagicMock()

        with (
            patch(
                "memorable.cli.build_production_context",
                return_value=(ctx, mock_driver),
            ),
            patch("memorable.cli.ensure_all_constraints"),
            patch("memorable.cli.load_runtime_config", return_value=RuntimeConfig()),
        ):
            exit_code = main(["init", "--path", str(tmp_path)])
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "version" in captured.err.lower()

    def test_init_command_scaffolds_missing_profile_and_initializes(
        self, tmp_path, capsys
    ) -> None:
        """memorable init creates a Minimal MemoryProfile when none exists."""
        import json
        from unittest.mock import MagicMock, patch

        from memorable.cli import main
        from memorable.config import RuntimeConfig
        from memorable.core.context import ApplicationContext
        from memorable.core.profile import load_profile_from_yaml

        project_dir = tmp_path / "training-log"
        project_dir.mkdir()
        profile_path = project_dir / ".memorable" / "memory.yaml"
        ctx = ApplicationContext()
        mock_driver = MagicMock()

        with (
            patch(
                "memorable.cli.build_production_context",
                return_value=(ctx, mock_driver),
            ),
            patch("memorable.cli.ensure_all_constraints"),
            patch("memorable.cli.load_runtime_config", return_value=RuntimeConfig()),
        ):
            exit_code = main(["init", "--path", str(project_dir)])

        assert exit_code == 0
        profile = load_profile_from_yaml(profile_path.read_text(encoding="utf-8"))
        assert profile.space.name == "training-log"
        assert profile.entities == ()
        assert profile.relations == ()
        assert profile.records == ()
        captured = capsys.readouterr()
        assert json.loads(captured.out)["space"] == "training-log"

    def test_init_command_scaffold_flags_override_space_and_description(
        self, tmp_path
    ) -> None:
        """Human setup flags control the scaffolded MemorySpace declaration."""
        from unittest.mock import MagicMock, patch

        from memorable.cli import main
        from memorable.config import RuntimeConfig
        from memorable.core.context import ApplicationContext
        from memorable.core.profile import load_profile_from_yaml

        target_dir = tmp_path / "derived-name"
        target_dir.mkdir()
        profile_path = target_dir / ".memorable" / "memory.yaml"
        ctx = ApplicationContext()
        mock_driver = MagicMock()

        with (
            patch(
                "memorable.cli.build_production_context",
                return_value=(ctx, mock_driver),
            ),
            patch("memorable.cli.ensure_all_constraints"),
            patch("memorable.cli.load_runtime_config", return_value=RuntimeConfig()),
        ):
            exit_code = main(
                [
                    "init",
                    "--path",
                    str(target_dir),
                    "--space",
                    "custom-space",
                    "--description",
                    "Training notes",
                ]
            )

        assert exit_code == 0
        profile = load_profile_from_yaml(profile_path.read_text(encoding="utf-8"))
        assert profile.space.name == "custom-space"
        assert profile.space.description == "Training notes"

    def test_init_command_existing_profile_is_not_overwritten(self, tmp_path) -> None:
        """Re-running init preserves a hand-written MemoryProfile file."""
        from unittest.mock import MagicMock, patch

        from memorable.cli import main
        from memorable.config import RuntimeConfig
        from memorable.core.context import ApplicationContext

        profile_dir = tmp_path / ".memorable"
        profile_dir.mkdir()
        profile_path = profile_dir / "memory.yaml"
        profile_path.write_text(VALID_PROFILE_YAML, encoding="utf-8")
        original_yaml = profile_path.read_text(encoding="utf-8")
        ctx = ApplicationContext()
        mock_driver = MagicMock()

        with (
            patch(
                "memorable.cli.build_production_context",
                return_value=(ctx, mock_driver),
            ),
            patch("memorable.cli.ensure_all_constraints"),
            patch("memorable.cli.load_runtime_config", return_value=RuntimeConfig()),
        ):
            exit_code = main(
                [
                    "init",
                    "--path",
                    str(tmp_path),
                    "--space",
                    "ignored-for-existing-profile",
                    "--description",
                    "Ignored for existing profile",
                ]
            )

        assert exit_code == 0
        assert profile_path.read_text(encoding="utf-8") == original_yaml


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
        assert "write_policy_default" not in result
        assert "write_policy_sensitive" not in result
