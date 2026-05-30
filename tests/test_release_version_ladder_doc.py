from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION_LADDER_DOC = ROOT / "docs" / "release-version-ladder.md"
README = ROOT / "README.md"


def test_version_ladder_documents_release_order_and_patch_rules() -> None:
    doc = VERSION_LADDER_DOC.read_text(encoding="utf-8")

    assert "0.0.x" in doc
    assert "pyproject.toml" in doc
    assert "git tag" in doc
    assert "tag must match" in doc
    assert "workflow publishes" in doc
    assert "output shape" in doc


def test_version_ladder_is_linked_from_readme() -> None:
    readme = README.read_text(encoding="utf-8")

    assert "docs/release-version-ladder.md" in readme
