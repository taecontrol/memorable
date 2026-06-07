"""SQLite connection policy for the Memorable storage adapter."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from memorable.config import RuntimeConfig
from memorable.storage.sqlite.schema import initialize_schema

BUSY_TIMEOUT_MS = 5000


@dataclass(frozen=True)
class SQLiteHandle:
    """Closeable SQLite resource returned to live entry points."""

    path: Path
    connection: sqlite3.Connection

    def close(self) -> None:
        self.connection.close()


def resolve_path(config: RuntimeConfig) -> Path:
    """Return the database path for the resolved runtime configuration."""
    configured_path = Path(config.sqlite.path).expanduser()
    if configured_path.is_absolute():
        return configured_path
    return config.base_path / configured_path


def connect(config: RuntimeConfig) -> SQLiteHandle:
    """Open and initialize a SQLite-backed MemorySpace resource."""
    path = resolve_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(
        path,
        timeout=BUSY_TIMEOUT_MS / 1000,
        # The MCP server builds the context once, then may dispatch sync tools
        # on worker threads while CLI processes open separate connections.
        check_same_thread=False,
    )
    connection.row_factory = sqlite3.Row
    try:
        _configure(connection)
        initialize_schema(connection)
    except Exception:
        connection.close()
        raise
    return SQLiteHandle(path=path, connection=connection)


def _configure(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
