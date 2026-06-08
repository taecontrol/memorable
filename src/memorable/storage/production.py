"""Production context factory for Memorable.

Creates a storage resource from RuntimeConfig, wires repository adapters into
ApplicationContext, and returns the closeable resource to entry points.
Entry points (CLI, MCP) own that resource lifecycle (close on exit).
"""

from __future__ import annotations

from typing import Protocol

from memorable.config import RuntimeConfig
from memorable.core.context import ApplicationContext
from memorable.storage.neo4j.connection import Neo4jDriver, connect
from memorable.storage.neo4j.repository import (
    Neo4jAboutRepository,
    Neo4jDecisionRepository,
    Neo4jEntityRepository,
    Neo4jForgetRepository,
    Neo4jMemorySpaceRepository,
    Neo4jObservationRepository,
    Neo4jRelationRepository,
    Neo4jTaskRepository,
)
from memorable.storage.neo4j.retrieval_index import Neo4jRetrievalIndex
from memorable.storage.sqlite.connection import SQLiteHandle
from memorable.storage.sqlite.connection import connect as connect_sqlite
from memorable.storage.sqlite.repository import (
    SQLiteAboutRepository,
    SQLiteDecisionRepository,
    SQLiteEntityRepository,
    SQLiteForgetRepository,
    SQLiteMemorySpaceRepository,
    SQLiteObservationRepository,
    SQLiteRelationRepository,
    SQLiteTaskRepository,
)


class CloseableResource(Protocol):
    def close(self) -> None: ...


def build_production_context(
    config: RuntimeConfig,
) -> tuple[ApplicationContext, CloseableResource]:
    """Create an ApplicationContext from resolved runtime storage config.

    The caller owns the returned resource lifecycle and must close it on exit.
    Neo4j remains the default path for this PRD slice; SQLite is selectable.
    """
    if config.storage.backend == "neo4j":
        return _build_neo4j_context(config)
    if config.storage.backend == "sqlite":
        return _build_sqlite_context(config)
    raise ValueError(f"Unsupported storage backend: {config.storage.backend}")


def _build_neo4j_context(
    config: RuntimeConfig,
) -> tuple[ApplicationContext, Neo4jDriver]:
    driver = connect(config)
    ctx = ApplicationContext(
        entity_repo=Neo4jEntityRepository(driver),
        decision_repo=Neo4jDecisionRepository(driver),
        task_repo=Neo4jTaskRepository(driver),
        observation_repo=Neo4jObservationRepository(driver),
        relation_repo=Neo4jRelationRepository(driver),
        about_repo=Neo4jAboutRepository(driver),
        forget_repo=Neo4jForgetRepository(driver),
        memory_space_repo=Neo4jMemorySpaceRepository(driver),
        retrieval_index=Neo4jRetrievalIndex(driver),
    )
    return ctx, driver


def _build_sqlite_context(
    config: RuntimeConfig,
) -> tuple[ApplicationContext, SQLiteHandle]:
    from memorable.storage.sqlite.retrieval_index import SqliteVecRetrievalIndex

    handle = connect_sqlite(config)
    ctx = ApplicationContext(
        entity_repo=SQLiteEntityRepository(handle),
        decision_repo=SQLiteDecisionRepository(handle),
        task_repo=SQLiteTaskRepository(handle),
        observation_repo=SQLiteObservationRepository(handle),
        relation_repo=SQLiteRelationRepository(handle),
        about_repo=SQLiteAboutRepository(handle),
        forget_repo=SQLiteForgetRepository(handle),
        memory_space_repo=SQLiteMemorySpaceRepository(handle),
        retrieval_index=SqliteVecRetrievalIndex(handle),
        atomic_write=handle.atomic_write,
        atomic_write_rolls_back_on_failure=True,
    )
    return ctx, handle
