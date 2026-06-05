"""Tests for the 'memorable db status' CLI subcommand.

Covers:
- Outputs resolved config as JSON
- Masks password in output
- Shows correct source for each field
- Accepts --path argument
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from memorable.cli import main

pytestmark = pytest.mark.usefixtures("clean_memorable_environment")


class TestDbStatusOutput:
    """memorable db status outputs resolved config with sources."""

    def test_outputs_valid_json(self, tmp_path: Path, capsys) -> None:
        result = main(["db", "status", "--path", str(tmp_path)])

        assert result == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert "neo4j" in output
        assert "docker" in output
        assert "embeddings" in output

    def test_password_is_masked(self, tmp_path: Path, capsys) -> None:
        main(["db", "status", "--path", str(tmp_path)])

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["neo4j"]["password"]["value"] == "***"

    def test_shows_value_and_source_for_each_field(
        self, tmp_path: Path, capsys
    ) -> None:
        main(["db", "status", "--path", str(tmp_path)])

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        neo4j_uri = output["neo4j"]["uri"]
        assert "value" in neo4j_uri
        assert "source" in neo4j_uri
        assert neo4j_uri["value"] == "bolt://127.0.0.1:7687"
        assert neo4j_uri["source"] == "built-in"

    def test_reflects_yaml_config(self, tmp_path: Path, capsys) -> None:
        config_dir = tmp_path / ".memorable"
        config_dir.mkdir()
        (config_dir / "runtime.yaml").write_text("neo4j:\n  uri: bolt://prod:7687\n")

        main(["db", "status", "--path", str(tmp_path)])

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["neo4j"]["uri"]["value"] == "bolt://prod:7687"
        assert output["neo4j"]["uri"]["source"] == "runtime.yaml"

    def test_uses_cwd_when_no_path_given(
        self, tmp_path: Path, capsys, monkeypatch
    ) -> None:
        monkeypatch.chdir(tmp_path)

        result = main(["db", "status"])

        assert result == 0
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert output["neo4j"]["uri"]["source"] == "built-in"

    def test_embeddings_shows_provider_model_and_dimensions(
        self, tmp_path: Path, capsys
    ) -> None:
        main(["db", "status", "--path", str(tmp_path)])

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        embeddings = output["embeddings"]

        assert embeddings["provider"] == {
            "value": "fastembed",
            "source": "built-in",
        }
        assert embeddings["model"] == {
            "value": "BAAI/bge-small-en-v1.5",
            "source": "built-in",
        }
        assert embeddings["dimensions"] == {
            "value": "384",
            "source": "built-in",
        }

    def test_embeddings_reflects_yaml_config(self, tmp_path: Path, capsys) -> None:
        config_dir = tmp_path / ".memorable"
        config_dir.mkdir()
        (config_dir / "runtime.yaml").write_text(
            "embeddings:\n  provider: fake\n  model: test-model\n  dimensions: 128\n"
        )

        main(["db", "status", "--path", str(tmp_path)])

        captured = capsys.readouterr()
        output = json.loads(captured.out)
        embeddings = output["embeddings"]

        assert embeddings["provider"] == {
            "value": "fake",
            "source": "runtime.yaml",
        }
        assert embeddings["model"] == {
            "value": "test-model",
            "source": "runtime.yaml",
        }
        assert embeddings["dimensions"] == {
            "value": "128",
            "source": "runtime.yaml",
        }
