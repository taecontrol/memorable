"""SQLite-backed RetrievalIndex adapter using sqlite-vec."""

from __future__ import annotations

import sqlite3
import struct
from datetime import UTC, datetime
from typing import Any

from memorable.retrieval.models import EmbeddingRecord, SearchCandidate
from memorable.storage.sqlite.connection import SQLiteHandle

_RECORD_TABLE = "memorable_embedding_records"
_VECTOR_TABLE = "memorable_embedding_vectors"
_META_TABLE = "memorable_embedding_vector_index"
_META_ROW = "active"


def _sqlite_vec_capability_error(cause: Exception) -> RuntimeError:
    return RuntimeError(
        "sqlite-vec cannot load for the SQLite backend on this interpreter. "
        "Use a uv-managed, Homebrew, conda-forge, or Windows >= 3.11 Python "
        "interpreter, or select the Neo4j backend. No numpy/brute-force "
        f"production fallback is used. Original error: {cause}"
    )


def _to_iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("stored datetimes must be timezone-aware")
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _from_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def probe_sqlite_vec_loadability(connection: sqlite3.Connection) -> Any:
    """Load sqlite-vec or raise an actionable SQLite-backend capability error."""
    try:
        import sqlite_vec
    except Exception as exc:  # pragma: no cover - exercised when dependency absent
        raise _sqlite_vec_capability_error(exc) from exc

    enable = getattr(connection, "enable_load_extension", None)
    if enable is None:
        cause = RuntimeError("enable_load_extension is unavailable")
        raise _sqlite_vec_capability_error(cause) from cause

    try:
        enable(True)
        sqlite_vec.load(connection)
    except Exception as exc:
        raise _sqlite_vec_capability_error(exc) from exc
    finally:
        try:
            enable(False)
        except Exception:
            pass
    return sqlite_vec


def _decode_vector(blob: bytes | memoryview) -> list[float]:
    raw = blob.tobytes() if isinstance(blob, memoryview) else blob
    if len(raw) % 4 != 0:
        raise ValueError("stored Embedding vector is not a float32 blob")
    return [value for (value,) in struct.iter_unpack("<f", raw)]


class SqliteVecRetrievalIndex:
    """Persistent derived Embedding index for the SQLite backend."""

    def __init__(self, handle: SQLiteHandle) -> None:
        self._handle = handle
        self._connection = handle.connection
        self._sqlite_vec = probe_sqlite_vec_loadability(self._connection)
        self._initialize_record_store()

    def _initialize_record_store(self) -> None:
        with self._handle.write():
            self._connection.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {_RECORD_TABLE} (
                    space TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    source_kind TEXT NOT NULL,
                    provider_name TEXT NOT NULL,
                    model_name TEXT NOT NULL,
                    dimensions INTEGER NOT NULL,
                    indexable_text TEXT NOT NULL,
                    indexable_text_hash TEXT NOT NULL,
                    indexable_text_version TEXT NOT NULL,
                    vector BLOB NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (
                        space,
                        source_id,
                        source_kind,
                        provider_name,
                        model_name,
                        dimensions
                    )
                )
                """
            )
            self._connection.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {_META_TABLE} (
                    name TEXT PRIMARY KEY,
                    dimensions INTEGER NOT NULL
                )
                """
            )

    def recreate_index(self, dimensions: int) -> None:
        """Recreate the sqlite-vec table and reload compatible Embeddings."""
        self._validate_dimensions(dimensions)
        with self._handle.write():
            self._create_vector_table(dimensions)
            self._copy_records_to_vector_table(dimensions)

    def store(self, record: EmbeddingRecord) -> None:
        """Add or replace a derived Embedding for a source item."""
        self._validate_record(record)
        self._ensure_vector_table(record.dimensions)
        vector_blob = self._sqlite_vec.serialize_float32(record.vector)
        with self._handle.write():
            self._delete_one_from_vector_table(
                space=record.space,
                source_id=record.source_id,
                source_kind=record.source_kind,
                provider_name=record.provider_name,
                model_name=record.model_name,
                dimensions=record.dimensions,
            )
            self._connection.execute(
                f"""
                INSERT OR REPLACE INTO {_RECORD_TABLE} (
                    space,
                    source_id,
                    source_kind,
                    provider_name,
                    model_name,
                    dimensions,
                    indexable_text,
                    indexable_text_hash,
                    indexable_text_version,
                    vector,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.space,
                    record.source_id,
                    record.source_kind,
                    record.provider_name,
                    record.model_name,
                    record.dimensions,
                    record.indexable_text,
                    record.indexable_text_hash,
                    record.indexable_text_version,
                    vector_blob,
                    _to_iso(record.created_at),
                    _to_iso(record.updated_at),
                ),
            )
            self._insert_into_vector_table(record, vector_blob)

    def clear_space(self, space: str) -> None:
        """Remove all derived Embeddings for a MemorySpace."""
        with self._handle.write():
            self._connection.execute(
                f"DELETE FROM {_RECORD_TABLE} WHERE space = ?",
                (space,),
            )
            if self._vector_table_exists():
                self._connection.execute(
                    f"DELETE FROM {_VECTOR_TABLE} WHERE space = ?",
                    (space,),
                )

    def delete(self, *, space: str, source_id: str, source_kind: str) -> None:
        """Remove derived Embeddings for one source item."""
        with self._handle.write():
            self._connection.execute(
                f"""
                DELETE FROM {_RECORD_TABLE}
                WHERE space = ? AND source_id = ? AND source_kind = ?
                """,
                (space, source_id, source_kind),
            )
            if self._vector_table_exists():
                self._connection.execute(
                    f"""
                    DELETE FROM {_VECTOR_TABLE}
                    WHERE space = ? AND source_id = ? AND source_kind = ?
                    """,
                    (space, source_id, source_kind),
                )

    def records(self, *, space: str | None = None) -> list[EmbeddingRecord]:
        """Return stored Embeddings, optionally scoped to one MemorySpace."""
        if space is None:
            rows = self._connection.execute(
                f"""
                SELECT *
                FROM {_RECORD_TABLE}
                ORDER BY source_kind ASC, source_id ASC,
                         provider_name ASC, model_name ASC, dimensions ASC
                """
            ).fetchall()
        else:
            rows = self._connection.execute(
                f"""
                SELECT *
                FROM {_RECORD_TABLE}
                WHERE space = ?
                ORDER BY source_kind ASC, source_id ASC,
                         provider_name ASC, model_name ASC, dimensions ASC
                """,
                (space,),
            ).fetchall()
        return [self._record_from_row(row) for row in rows]

    def search(
        self,
        space: str,
        query_vector: list[float],
        top_k: int = 10,
        *,
        provider_name: str | None = None,
        model_name: str | None = None,
        dimensions: int | None = None,
    ) -> list[SearchCandidate]:
        """Search compatible Embeddings using sqlite-vec cosine distance."""
        if top_k <= 0:
            return []
        effective_dimensions = (
            dimensions if dimensions is not None else len(query_vector)
        )
        if len(query_vector) != effective_dimensions:
            return []
        if not self._vector_table_exists():
            return []
        if self._current_dimensions() != effective_dimensions:
            return []

        query_blob = self._sqlite_vec.serialize_float32(query_vector)
        filters = [
            "embedding MATCH ?",
            "k = ?",
            "space = ?",
            "dimensions = ?",
        ]
        values: list[object] = [query_blob, top_k, space, effective_dimensions]
        if provider_name is not None:
            filters.append("provider_name = ?")
            values.append(provider_name)
        if model_name is not None:
            filters.append("model_name = ?")
            values.append(model_name)

        where = " AND ".join(filters)
        rows = self._connection.execute(
            f"""
            SELECT source_id, source_kind, distance
            FROM {_VECTOR_TABLE}
            WHERE {where}
            ORDER BY distance
            """,
            tuple(values),
        ).fetchall()
        return [
            SearchCandidate(
                source_id=row["source_id"],
                source_kind=row["source_kind"],
                score=1.0 - float(row["distance"]),
            )
            for row in rows
        ]

    def _record_from_row(self, row: sqlite3.Row) -> EmbeddingRecord:
        return EmbeddingRecord(
            source_id=row["source_id"],
            source_kind=row["source_kind"],
            space=row["space"],
            indexable_text=row["indexable_text"],
            vector=_decode_vector(row["vector"]),
            provider_name=row["provider_name"],
            model_name=row["model_name"],
            dimensions=row["dimensions"],
            indexable_text_hash=row["indexable_text_hash"],
            indexable_text_version=row["indexable_text_version"],
            created_at=_from_iso(row["created_at"]),
            updated_at=_from_iso(row["updated_at"]),
        )

    def _ensure_vector_table(self, dimensions: int) -> None:
        current_dimensions = self._current_dimensions()
        if current_dimensions is None or not self._vector_table_exists():
            with self._handle.write():
                self._create_vector_table(dimensions)
            return
        if current_dimensions != dimensions:
            raise ValueError(
                "SQLite Embedding index was created for "
                f"{current_dimensions} dimensions, but this Embedding has "
                f"{dimensions} dimensions. Run `memorable reindex` to recreate "
                "the derived Embedding index for the active settings."
            )

    def _create_vector_table(self, dimensions: int) -> None:
        self._connection.execute(f"DROP TABLE IF EXISTS {_VECTOR_TABLE}")
        self._connection.execute(
            f"""
            CREATE VIRTUAL TABLE {_VECTOR_TABLE} USING vec0(
                embedding float[{dimensions}] distance_metric=cosine,
                space text,
                source_id text,
                source_kind text,
                indexable_text_hash text,
                indexable_text_version text,
                provider_name text,
                model_name text,
                dimensions integer
            )
            """
        )
        self._connection.execute(
            f"""
            INSERT OR REPLACE INTO {_META_TABLE} (name, dimensions)
            VALUES (?, ?)
            """,
            (_META_ROW, dimensions),
        )

    def _copy_records_to_vector_table(self, dimensions: int) -> None:
        rows = self._connection.execute(
            f"""
            SELECT *
            FROM {_RECORD_TABLE}
            WHERE dimensions = ?
            ORDER BY space ASC, source_kind ASC, source_id ASC
            """,
            (dimensions,),
        ).fetchall()
        for row in rows:
            self._connection.execute(
                f"""
                INSERT INTO {_VECTOR_TABLE} (
                    embedding,
                    space,
                    source_id,
                    source_kind,
                    indexable_text_hash,
                    indexable_text_version,
                    provider_name,
                    model_name,
                    dimensions
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["vector"],
                    row["space"],
                    row["source_id"],
                    row["source_kind"],
                    row["indexable_text_hash"],
                    row["indexable_text_version"],
                    row["provider_name"],
                    row["model_name"],
                    row["dimensions"],
                ),
            )

    def _insert_into_vector_table(
        self, record: EmbeddingRecord, vector_blob: bytes
    ) -> None:
        self._connection.execute(
            f"""
            INSERT INTO {_VECTOR_TABLE} (
                embedding,
                space,
                source_id,
                source_kind,
                indexable_text_hash,
                indexable_text_version,
                provider_name,
                model_name,
                dimensions
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                vector_blob,
                record.space,
                record.source_id,
                record.source_kind,
                record.indexable_text_hash,
                record.indexable_text_version,
                record.provider_name,
                record.model_name,
                record.dimensions,
            ),
        )

    def _delete_one_from_vector_table(
        self,
        *,
        space: str,
        source_id: str,
        source_kind: str,
        provider_name: str,
        model_name: str,
        dimensions: int,
    ) -> None:
        if not self._vector_table_exists():
            return
        self._connection.execute(
            f"""
            DELETE FROM {_VECTOR_TABLE}
            WHERE space = ?
              AND source_id = ?
              AND source_kind = ?
              AND provider_name = ?
              AND model_name = ?
              AND dimensions = ?
            """,
            (space, source_id, source_kind, provider_name, model_name, dimensions),
        )

    def _vector_table_exists(self) -> bool:
        row = self._connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = ?
            """,
            (_VECTOR_TABLE,),
        ).fetchone()
        return row is not None

    def _current_dimensions(self) -> int | None:
        row = self._connection.execute(
            f"SELECT dimensions FROM {_META_TABLE} WHERE name = ?",
            (_META_ROW,),
        ).fetchone()
        if row is None:
            return None
        return int(row["dimensions"])

    def _validate_record(self, record: EmbeddingRecord) -> None:
        self._validate_dimensions(record.dimensions)
        if len(record.vector) != record.dimensions:
            raise ValueError(
                "Embedding vector length must match its stored dimensions "
                f"({len(record.vector)} != {record.dimensions})"
            )

    def _validate_dimensions(self, dimensions: int) -> None:
        if dimensions <= 0:
            raise ValueError("Embedding dimensions must be positive")
