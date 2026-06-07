from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _squash(text: str) -> str:
    return " ".join(text.split())


def test_readme_documents_neo4j_database_selector_for_owners() -> None:
    readme = _read("README.md")
    readme_words = _squash(readme)

    assert "| `neo4j.database` | `MEMORABLE_NEO4J_DATABASE` | `neo4j` |" in readme
    assert "`neo4j.database` selects the physical Neo4j database" in readme_words
    assert "A MemorySpace is Memorable's logical project boundary" in readme_words
    assert "stored as a `space` tag" in readme_words
    assert "Many MemorySpaces can coexist in one Neo4j database" in readme_words
    assert "Community Edition" in readme_words
    assert "cannot create additional physical databases" in readme_words
    assert "not a way to spin up a second local store" in readme_words


def test_runtime_config_adr_documents_neo4j_database_boundary() -> None:
    adr = _squash(_read("docs/adr/0010-three-layer-runtime-configuration.md"))

    assert "neo4j.database" in adr
    assert "default literal `neo4j`" in adr
    assert "MEMORABLE_NEO4J_DATABASE" in adr
    assert "non-secret environment override" in adr
    assert "MemorySpace remains the logical boundary" in adr
    assert "`space` tag and query filter" in adr
    assert "Neo4j Community Edition" in adr
    assert "does not create or provision databases" in adr
