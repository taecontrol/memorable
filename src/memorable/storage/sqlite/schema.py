"""SQLite schema bootstrap for the Memorable storage adapter."""

from __future__ import annotations

import sqlite3


def initialize_schema(connection: sqlite3.Connection) -> None:
    """Create the storage shape required by the implemented SQLite ports."""
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS memory_spaces (
            name TEXT PRIMARY KEY
        );

        CREATE TABLE IF NOT EXISTS entities (
            space TEXT NOT NULL,
            id TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            name TEXT NOT NULL,
            attributes_json TEXT NOT NULL,
            PRIMARY KEY (space, id)
        );

        CREATE TABLE IF NOT EXISTS provenance (
            space TEXT NOT NULL,
            record_id TEXT NOT NULL,
            record_kind TEXT NOT NULL,
            source_id TEXT NOT NULL,
            episode_id TEXT NOT NULL,
            writer TEXT NOT NULL,
            reason TEXT NOT NULL,
            creation_time TEXT NOT NULL,
            validity_time TEXT NOT NULL,
            PRIMARY KEY (space, record_id, record_kind)
        );
        """
    )
