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

        CREATE TABLE IF NOT EXISTS memory_records (
            space TEXT NOT NULL,
            id TEXT NOT NULL,
            record_kind TEXT NOT NULL,
            PRIMARY KEY (space, id)
        );

        CREATE TABLE IF NOT EXISTS decisions (
            space TEXT NOT NULL,
            id TEXT NOT NULL,
            statement TEXT NOT NULL,
            validity_time TEXT NOT NULL,
            invalidation_time TEXT,
            lifecycle_state TEXT NOT NULL,
            supersedes TEXT,
            superseded_by TEXT,
            record_type TEXT,
            PRIMARY KEY (space, id)
        );

        CREATE TABLE IF NOT EXISTS observations (
            space TEXT NOT NULL,
            id TEXT NOT NULL,
            statement TEXT NOT NULL,
            validity_time TEXT NOT NULL,
            invalidation_time TEXT,
            lifecycle_state TEXT NOT NULL,
            supersedes TEXT,
            superseded_by TEXT,
            record_type TEXT,
            PRIMARY KEY (space, id)
        );

        CREATE TABLE IF NOT EXISTS tasks (
            space TEXT NOT NULL,
            id TEXT NOT NULL,
            title TEXT NOT NULL,
            lifecycle_state TEXT NOT NULL,
            validity_time TEXT NOT NULL,
            completion_time TEXT,
            completion_event_id TEXT,
            record_type TEXT,
            PRIMARY KEY (space, id)
        );

        CREATE TABLE IF NOT EXISTS relations (
            space TEXT NOT NULL,
            id TEXT NOT NULL,
            source_entity_id TEXT NOT NULL,
            target_entity_id TEXT NOT NULL,
            relation_type TEXT NOT NULL,
            statement TEXT NOT NULL,
            validity_time TEXT NOT NULL,
            invalidation_time TEXT,
            lifecycle_state TEXT NOT NULL,
            supersedes TEXT,
            superseded_by TEXT,
            PRIMARY KEY (space, id),
            FOREIGN KEY (space, id)
                REFERENCES memory_records (space, id),
            FOREIGN KEY (space, source_entity_id)
                REFERENCES entities (space, id),
            FOREIGN KEY (space, target_entity_id)
                REFERENCES entities (space, id)
        );

        CREATE TABLE IF NOT EXISTS about_links (
            space TEXT NOT NULL,
            record_id TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            PRIMARY KEY (space, record_id, entity_id),
            FOREIGN KEY (space, record_id)
                REFERENCES memory_records (space, id),
            FOREIGN KEY (space, entity_id)
                REFERENCES entities (space, id)
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
