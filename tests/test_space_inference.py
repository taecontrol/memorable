"""Tests for space inference from MemoryProfile.

Space inference allows CLI commands to omit --space when
a .memorable/memory.yaml exists in the working directory.
"""

from __future__ import annotations

from pathlib import Path

import pytest


class TestResolveSpaceFromProfile:
    """resolve_space reads .memorable/memory.yaml and returns space.name."""

    def test_returns_space_name_from_memory_yaml(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """When memory.yaml exists, resolve_space returns the space name."""
        from memorable.cli import resolve_space

        memorable_dir = tmp_path / ".memorable"
        memorable_dir.mkdir()
        (memorable_dir / "memory.yaml").write_text(
            "version: 1\n"
            "space:\n"
            "  name: my-project\n"
            "  description: Test project\n"
            "entities:\n"
            "  - name: Component\n"
            "records:\n"
            "  - name: ArchitectureDecision\n"
            "    extends: Decision\n",
            encoding="utf-8",
        )

        monkeypatch.chdir(tmp_path)
        # Simulate args without --space
        space = resolve_space(space_arg=None)

        assert space == "my-project"

    def test_space_flag_overrides_inferred_space(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """When --space is provided, it wins even if memory.yaml exists."""
        from memorable.cli import resolve_space

        memorable_dir = tmp_path / ".memorable"
        memorable_dir.mkdir()
        (memorable_dir / "memory.yaml").write_text(
            "version: 1\n"
            "space:\n"
            "  name: from-yaml\n"
            "  description: From YAML\n"
            "entities:\n"
            "  - name: Component\n",
            encoding="utf-8",
        )

        monkeypatch.chdir(tmp_path)
        space = resolve_space(space_arg="from-flag")

        assert space == "from-flag"

    def test_error_when_no_flag_and_no_memory_yaml(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """When neither --space nor memory.yaml exists, raise SystemExit."""
        from memorable.cli import resolve_space

        monkeypatch.chdir(tmp_path)
        with pytest.raises(SystemExit):
            resolve_space(space_arg=None)

    def test_error_message_is_helpful(
        self,
        tmp_path: Path,
        monkeypatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """The error message explains how to fix the situation."""
        from memorable.cli import resolve_space

        monkeypatch.chdir(tmp_path)
        with pytest.raises(SystemExit):
            resolve_space(space_arg=None)

        err = capsys.readouterr().err
        assert "--space" in err
        assert "memory.yaml" in err
