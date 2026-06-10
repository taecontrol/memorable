from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _squash(text: str) -> str:
    return " ".join(text.split())


def test_readme_install_docs_explain_supported_sqlite_vec_interpreters() -> None:
    readme = _read("README.md")
    install = readme.split("## Install", 1)[1].split("## Quickstart", 1)[0]
    install_words = _squash(install)

    assert "uvx --from memorable-kg memorable --help" in install
    assert "uv tool install memorable-kg" in install
    assert "recommended install path" in install_words
    assert "uv-managed CPython" in install_words
    assert "python-build-standalone" in install_words
    assert "loadable SQLite extensions" in install_words
    assert "python.org-macOS" in install_words
    assert "macOS-system" in install_words
    assert "default-pyenv" in install_words
    assert (
        "sqlite-vec cannot load for the SQLite backend on this interpreter" in install
    )
    assert (
        "Use a uv-managed, Homebrew, conda-forge, or Windows >= 3.11 Python "
        "interpreter, or select the Neo4j backend" in install_words
    )
    assert "No numpy/brute-force production fallback is used" in install
    assert "switch interpreter" in install_words
    assert "select the Neo4j backend" in install_words
    assert "sqlite-vec is replaceable, not load-bearing" in install_words
    assert "Embeddings are derived" in install_words
    assert "memorable reindex" in install_words
    assert "no canonical memory is at risk" in install_words
    assert (
        "documented replacement design is a numpy/BLOB brute-force adapter"
        in install_words
    )
    assert "future adapter / swap path" in install_words
    assert "same `RetrievalIndex` port" in install_words
    assert "not a current shipped implementation" in install_words
    assert "backs the in-memory test index" not in install_words


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


def test_readme_documents_sqlite_storage_default_for_owners() -> None:
    readme = _read("README.md")
    readme_words = _squash(readme)

    assert "| `storage.backend` | `MEMORABLE_STORAGE_BACKEND` | `sqlite` |" in readme
    assert (
        "| `sqlite.path` | `MEMORABLE_SQLITE_PATH` | `.memorable/memory.db` |" in readme
    )
    assert "SQLite is the embedded default storage backend" in readme_words
    assert "select Neo4j explicitly" in readme_words


def test_readme_quickstart_uses_default_sqlite_without_database_server() -> None:
    readme = _read("README.md")
    readme_words = _squash(readme)
    quickstart = readme.split("## Quickstart", 1)[1].split("## Configuration", 1)[0]
    quickstart_words = _squash(quickstart)
    neo4j_section = readme.split("## Neo4j", 1)[1].split("## CLI reference", 1)[0]

    assert "backed by embedded SQLite by default" in readme_words
    assert "No database server or Docker step is required" in quickstart_words
    assert "memorable db start" not in quickstart
    assert "memorable db start" in neo4j_section
    assert "storage:\n  backend: neo4j" in neo4j_section


def test_gitignore_excludes_default_sqlite_database_artifacts() -> None:
    gitignore = _read(".gitignore")

    assert ".memorable/*.db" in gitignore
    assert ".memorable/*.db-*" in gitignore


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
