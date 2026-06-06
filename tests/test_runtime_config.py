"""Tests for three-layer runtime config loading.

Covers:
- Defaults when no config files exist
- Reading runtime.yaml as base config
- Deep-merging runtime.local.yaml over base
- Loading secrets from .env
- Falling back to environment variables when no .env exists
- Frozen dataclass invariant
- Source tracking for each resolved value
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.usefixtures("clean_memorable_environment")


class TestDefaultsOnly:
    """When no config files exist, load_runtime_config returns built-in defaults."""

    def test_returns_runtime_config_with_default_neo4j(self, tmp_path: Path) -> None:
        from memorable.config import RuntimeConfig, load_runtime_config

        config = load_runtime_config(base_path=tmp_path)

        assert isinstance(config, RuntimeConfig)
        assert config.neo4j.uri == "bolt://127.0.0.1:7687"
        assert config.neo4j.user == "neo4j"
        assert config.neo4j.password == "memorable"

    def test_returns_default_docker_settings(self, tmp_path: Path) -> None:
        from memorable.config import load_runtime_config

        config = load_runtime_config(base_path=tmp_path)

        assert config.docker.neo4j_version == "5.26"
        assert config.docker.http_port == 7474
        assert config.docker.bolt_port == 7687

    def test_returns_default_embedding_settings(self, tmp_path: Path) -> None:
        from memorable.config import load_runtime_config

        config = load_runtime_config(base_path=tmp_path)

        assert config.embeddings.provider == "fastembed"
        assert config.embeddings.model == "BAAI/bge-small-en-v1.5"
        assert config.embeddings.dimensions == 384
        assert config.embeddings.api_key is None

    def test_all_sources_are_builtin(self, tmp_path: Path) -> None:
        from memorable.config import load_runtime_config

        config = load_runtime_config(base_path=tmp_path)

        assert config.sources["neo4j.uri"] == "built-in"
        assert config.sources["neo4j.user"] == "built-in"
        assert config.sources["neo4j.password"] == "built-in"
        assert config.sources["docker.neo4j_version"] == "built-in"
        assert config.sources["embeddings.provider"] == "built-in"
        assert config.sources["embeddings.dimensions"] == "built-in"

    def test_runtime_config_is_frozen(self, tmp_path: Path) -> None:
        from memorable.config import load_runtime_config

        config = load_runtime_config(base_path=tmp_path)

        with pytest.raises(AttributeError):
            config.neo4j = None  # type: ignore[misc]


class TestRuntimeYaml:
    """When .memorable/runtime.yaml exists, it overrides built-in defaults."""

    def test_reads_neo4j_uri_from_yaml(self, tmp_path: Path) -> None:
        from memorable.config import load_runtime_config

        config_dir = tmp_path / ".memorable"
        config_dir.mkdir()
        (config_dir / "runtime.yaml").write_text("neo4j:\n  uri: bolt://custom:7687\n")

        config = load_runtime_config(base_path=tmp_path)

        assert config.neo4j.uri == "bolt://custom:7687"
        # Other neo4j fields remain default
        assert config.neo4j.user == "neo4j"
        assert config.neo4j.password == "memorable"

    def test_custom_local_port_override_is_preserved_and_local(
        self, tmp_path: Path
    ) -> None:
        from memorable.config import load_runtime_config
        from memorable.runtime.docker import is_remote_uri

        config_dir = tmp_path / ".memorable"
        config_dir.mkdir()
        (config_dir / "runtime.yaml").write_text(
            "neo4j:\n  uri: bolt://127.0.0.1:7688\n"
        )

        config = load_runtime_config(base_path=tmp_path)

        assert config.neo4j.uri == "bolt://127.0.0.1:7688"
        assert is_remote_uri(config.neo4j.uri) is False

    def test_source_tracks_runtime_yaml(self, tmp_path: Path) -> None:
        from memorable.config import load_runtime_config

        config_dir = tmp_path / ".memorable"
        config_dir.mkdir()
        (config_dir / "runtime.yaml").write_text("neo4j:\n  uri: bolt://custom:7687\n")

        config = load_runtime_config(base_path=tmp_path)

        assert config.sources["neo4j.uri"] == "runtime.yaml"
        assert config.sources["neo4j.user"] == "built-in"

    def test_reads_docker_settings_from_yaml(self, tmp_path: Path) -> None:
        from memorable.config import load_runtime_config

        config_dir = tmp_path / ".memorable"
        config_dir.mkdir()
        (config_dir / "runtime.yaml").write_text(
            "docker:\n  neo4j_version: '5.30'\n  http_port: 8474\n"
        )

        config = load_runtime_config(base_path=tmp_path)

        assert config.docker.neo4j_version == "5.30"
        assert config.docker.http_port == 8474
        assert config.docker.bolt_port == 7687  # default preserved

    def test_reads_embedding_settings_from_yaml(self, tmp_path: Path) -> None:
        from memorable.config import load_runtime_config

        config_dir = tmp_path / ".memorable"
        config_dir.mkdir()
        (config_dir / "runtime.yaml").write_text(
            "embeddings:\n"
            "  provider: openrouter\n"
            "  model: text-embedding-3-small\n"
            "  dimensions: 1536\n"
        )

        config = load_runtime_config(base_path=tmp_path)

        assert config.embeddings.provider == "openrouter"
        assert config.embeddings.model == "text-embedding-3-small"
        assert config.embeddings.dimensions == 1536
        assert config.sources["embeddings.provider"] == "runtime.yaml"
        assert config.sources["embeddings.model"] == "runtime.yaml"
        assert config.sources["embeddings.dimensions"] == "runtime.yaml"

    def test_dimensions_override_preserves_other_defaults(self, tmp_path: Path) -> None:
        from memorable.config import load_runtime_config

        config_dir = tmp_path / ".memorable"
        config_dir.mkdir()
        (config_dir / "runtime.yaml").write_text("embeddings:\n  dimensions: 768\n")

        config = load_runtime_config(base_path=tmp_path)

        assert config.embeddings.dimensions == 768
        assert config.embeddings.provider == "fastembed"  # default preserved
        assert config.embeddings.model == "BAAI/bge-small-en-v1.5"  # default preserved
        assert config.sources["embeddings.dimensions"] == "runtime.yaml"
        assert config.sources["embeddings.provider"] == "built-in"


class TestLocalOverrideMerging:
    """runtime.local.yaml deep-merges over runtime.yaml, overriding leaf values."""

    def test_local_overrides_single_field(self, tmp_path: Path) -> None:
        from memorable.config import load_runtime_config

        config_dir = tmp_path / ".memorable"
        config_dir.mkdir()
        (config_dir / "runtime.yaml").write_text(
            "neo4j:\n  uri: bolt://base:7687\n  user: base_user\n"
        )
        (config_dir / "runtime.local.yaml").write_text(
            "neo4j:\n  uri: bolt://local:7687\n"
        )

        config = load_runtime_config(base_path=tmp_path)

        assert config.neo4j.uri == "bolt://local:7687"
        assert config.neo4j.user == "base_user"  # preserved from runtime.yaml

    def test_local_source_tracking(self, tmp_path: Path) -> None:
        from memorable.config import load_runtime_config

        config_dir = tmp_path / ".memorable"
        config_dir.mkdir()
        (config_dir / "runtime.yaml").write_text(
            "neo4j:\n  uri: bolt://base:7687\n  user: base_user\n"
        )
        (config_dir / "runtime.local.yaml").write_text(
            "neo4j:\n  uri: bolt://local:7687\n"
        )

        config = load_runtime_config(base_path=tmp_path)

        assert config.sources["neo4j.uri"] == "runtime.local.yaml"
        assert config.sources["neo4j.user"] == "runtime.yaml"

    def test_deep_merge_preserves_sibling_sections(self, tmp_path: Path) -> None:
        from memorable.config import load_runtime_config

        config_dir = tmp_path / ".memorable"
        config_dir.mkdir()
        (config_dir / "runtime.yaml").write_text(
            "neo4j:\n  uri: bolt://base:7687\ndocker:\n  neo4j_version: '5.26'\n"
        )
        (config_dir / "runtime.local.yaml").write_text("docker:\n  bolt_port: 9999\n")

        config = load_runtime_config(base_path=tmp_path)

        assert config.neo4j.uri == "bolt://base:7687"
        assert config.docker.neo4j_version == "5.26"
        assert config.docker.bolt_port == 9999


class TestDotEnvSecrets:
    """Secrets are loaded from .memorable/.env, overriding YAML values."""

    def test_password_from_dotenv(self, tmp_path: Path) -> None:
        from memorable.config import load_runtime_config

        config_dir = tmp_path / ".memorable"
        config_dir.mkdir()
        (config_dir / ".env").write_text("MEMORABLE_NEO4J_PASSWORD=s3cret\n")

        config = load_runtime_config(base_path=tmp_path)

        assert config.neo4j.password == "s3cret"
        assert config.sources["neo4j.password"] == ".env"

    def test_dotenv_overrides_yaml(self, tmp_path: Path) -> None:
        from memorable.config import load_runtime_config

        config_dir = tmp_path / ".memorable"
        config_dir.mkdir()
        (config_dir / "runtime.yaml").write_text("neo4j:\n  password: yaml_pass\n")
        (config_dir / ".env").write_text("MEMORABLE_NEO4J_PASSWORD=env_pass\n")

        config = load_runtime_config(base_path=tmp_path)

        assert config.neo4j.password == "env_pass"
        assert config.sources["neo4j.password"] == ".env"

    def test_dotenv_skips_comments_and_blanks(self, tmp_path: Path) -> None:
        from memorable.config import load_runtime_config

        config_dir = tmp_path / ".memorable"
        config_dir.mkdir()
        (config_dir / ".env").write_text(
            "# This is a comment\n"
            "\n"
            "MEMORABLE_NEO4J_PASSWORD=parsed\n"
            "  # Another comment\n"
        )

        config = load_runtime_config(base_path=tmp_path)

        assert config.neo4j.password == "parsed"

    def test_dotenv_strips_quotes(self, tmp_path: Path) -> None:
        from memorable.config import load_runtime_config

        config_dir = tmp_path / ".memorable"
        config_dir.mkdir()
        (config_dir / ".env").write_text('MEMORABLE_NEO4J_PASSWORD="quoted_pass"\n')

        config = load_runtime_config(base_path=tmp_path)

        assert config.neo4j.password == "quoted_pass"

    def test_all_env_keys_mapped(self, tmp_path: Path) -> None:
        from memorable.config import load_runtime_config

        config_dir = tmp_path / ".memorable"
        config_dir.mkdir()
        (config_dir / ".env").write_text(
            "MEMORABLE_NEO4J_URI=bolt://env:9999\n"
            "MEMORABLE_NEO4J_USER=env_user\n"
            "MEMORABLE_NEO4J_PASSWORD=env_pass\n"
        )

        config = load_runtime_config(base_path=tmp_path)

        assert config.neo4j.uri == "bolt://env:9999"
        assert config.neo4j.user == "env_user"
        assert config.neo4j.password == "env_pass"
        assert config.sources["neo4j.uri"] == ".env"
        assert config.sources["neo4j.user"] == ".env"
        assert config.sources["neo4j.password"] == ".env"


class TestOpenRouterApiKeyFromDotEnv:
    """MEMORABLE_OPENROUTER_API_KEY loads into embeddings.api_key."""

    def test_api_key_loaded_from_dotenv(self, tmp_path: Path) -> None:
        from memorable.config import load_runtime_config

        config_dir = tmp_path / ".memorable"
        config_dir.mkdir()
        (config_dir / ".env").write_text("MEMORABLE_OPENROUTER_API_KEY=sk-or-test\n")

        config = load_runtime_config(base_path=tmp_path)

        assert config.embeddings.api_key == "sk-or-test"
        assert config.sources["embeddings.api_key"] == ".env"

    def test_api_key_from_environ_fallback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from memorable.config import load_runtime_config

        monkeypatch.setenv("MEMORABLE_OPENROUTER_API_KEY", "sk-or-env")

        config = load_runtime_config(base_path=tmp_path)

        assert config.embeddings.api_key == "sk-or-env"
        assert config.sources["embeddings.api_key"] == "environment"

    def test_api_key_none_when_not_set(self, tmp_path: Path) -> None:
        from memorable.config import load_runtime_config

        config = load_runtime_config(base_path=tmp_path)

        assert config.embeddings.api_key is None

    def test_api_key_source_is_builtin_when_not_set(self, tmp_path: Path) -> None:
        from memorable.config import load_runtime_config

        config = load_runtime_config(base_path=tmp_path)

        assert config.sources["embeddings.api_key"] == "built-in"


class TestEnvironmentFallback:
    """When no .env file exists, secrets fall back to os.environ."""

    def test_non_secret_environ_ignored_by_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from memorable.config import load_runtime_config

        monkeypatch.setenv("MEMORABLE_NEO4J_URI", "bolt://env:9999")
        monkeypatch.setenv("MEMORABLE_NEO4J_USER", "env_user")

        config = load_runtime_config(base_path=tmp_path)

        assert config.neo4j.uri == "bolt://127.0.0.1:7687"
        assert config.neo4j.user == "neo4j"
        assert config.sources["neo4j.uri"] == "built-in"
        assert config.sources["neo4j.user"] == "built-in"

    def test_non_secret_environ_can_be_opted_in_for_live_commands(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from memorable.config import load_runtime_config

        monkeypatch.setenv("MEMORABLE_NEO4J_URI", "bolt://env:9999")
        monkeypatch.setenv("MEMORABLE_NEO4J_USER", "env_user")

        config = load_runtime_config(
            base_path=tmp_path,
            include_environment_overrides=True,
        )

        assert config.neo4j.uri == "bolt://env:9999"
        assert config.neo4j.user == "env_user"
        assert config.sources["neo4j.uri"] == "environment"
        assert config.sources["neo4j.user"] == "environment"

    def test_reads_from_os_environ(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from memorable.config import load_runtime_config

        monkeypatch.setenv("MEMORABLE_NEO4J_PASSWORD", "from_env")

        config = load_runtime_config(base_path=tmp_path)

        assert config.neo4j.password == "from_env"
        assert config.sources["neo4j.password"] == "environment"

    def test_dotenv_takes_precedence_over_environ(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from memorable.config import load_runtime_config

        config_dir = tmp_path / ".memorable"
        config_dir.mkdir()
        (config_dir / ".env").write_text("MEMORABLE_NEO4J_PASSWORD=from_file\n")
        monkeypatch.setenv("MEMORABLE_NEO4J_PASSWORD", "from_env")

        config = load_runtime_config(base_path=tmp_path)

        assert config.neo4j.password == "from_file"
        assert config.sources["neo4j.password"] == ".env"

    def test_environ_not_used_when_dotenv_exists_without_key(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If .env file exists but doesn't have the key, don't fall back to environ."""
        from memorable.config import load_runtime_config

        config_dir = tmp_path / ".memorable"
        config_dir.mkdir()
        (config_dir / ".env").write_text("# empty file\n")
        monkeypatch.setenv("MEMORABLE_NEO4J_PASSWORD", "from_env")

        config = load_runtime_config(base_path=tmp_path)

        # .env file exists, so environ is not consulted
        assert config.neo4j.password == "memorable"  # built-in default
        assert config.sources["neo4j.password"] == "built-in"


class TestConnectionSettingsStayOutOfCore:
    """Neo4j connection settings are storage/runtime infrastructure, not core."""

    def test_neo4j_settings_is_not_a_core_domain_model(self) -> None:
        """Connection settings must not leak into core domain models.

        Neo4j connection settings live in the runtime-config vocabulary
        (``memorable.config.Neo4jSettings``), never in core domain models, so
        infrastructure configuration cannot drift into the core domain.
        """
        import memorable.core.models as core_models

        assert not hasattr(core_models, "Neo4jSettings")
