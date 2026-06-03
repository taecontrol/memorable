"""Production context factory for Memorable.

Creates a Neo4j driver from RuntimeConfig, wires all Neo4j repository
adapters into ApplicationContext, and verifies connectivity on creation.
Entry points (CLI, MCP) own the driver lifecycle (close on exit).
"""

from __future__ import annotations

from neo4j import Driver, GraphDatabase

from memorable.config import RuntimeConfig
from memorable.core.context import ApplicationContext
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


def build_production_context(
    config: RuntimeConfig,
) -> tuple[ApplicationContext, Driver]:
    """Create a Neo4j-backed ApplicationContext from resolved config.

    Creates a Neo4j driver, verifies connectivity (fail-fast), instantiates
    all four Neo4j repository adapters, and returns both the wired
    ApplicationContext and the driver.

    The caller owns the driver lifecycle and must close it on exit.

    Raises:
        ConnectionError: If Neo4j is unreachable, with an actionable message
            suggesting ``memorable db start`` or checking the config.
    """
    driver = GraphDatabase.driver(
        config.neo4j.uri,
        auth=(config.neo4j.user, config.neo4j.password),
        # Sparse graphs legitimately lack some labels/properties/relationships.
        # If a real query typo slips through because this hides UNRECOGNIZED,
        # revisit with a narrower filter or debug-level notification sink.
        notifications_disabled_classifications=["UNRECOGNIZED"],
    )

    try:
        driver.verify_connectivity()
    except Exception as exc:
        driver.close()
        raise ConnectionError(
            f"Cannot connect to Neo4j at {config.neo4j.uri}. "
            f"Is Neo4j running? Try 'memorable db start' or check your "
            f"runtime config in .memorable/runtime.yaml.\n"
            f"Original error: {exc}"
        ) from exc

    ctx = ApplicationContext(
        entity_repo=Neo4jEntityRepository(driver),
        decision_repo=Neo4jDecisionRepository(driver),
        task_repo=Neo4jTaskRepository(driver),
        observation_repo=Neo4jObservationRepository(driver),
        relation_repo=Neo4jRelationRepository(driver),
        about_repo=Neo4jAboutRepository(driver),
        forget_repo=Neo4jForgetRepository(driver),
        memory_space_repo=Neo4jMemorySpaceRepository(driver),
    )

    return ctx, driver
