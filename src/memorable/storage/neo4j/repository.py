"""Neo4j adapter for MemorySpace persistence.

All Neo4j-specific details (Cypher queries, constraints, node labels,
relationship types) are encapsulated here. The public interface uses
only domain language from Memorable Core.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from memorable.core.models import MemorySpace


@runtime_checkable
class Neo4jDriver(Protocol):
    """Minimal driver interface expected by the Neo4j adapter."""

    def session(self) -> Any: ...


class Neo4jMemorySpaceRepository:
    """Storage adapter that persists MemorySpaces in Neo4j.

    Implements the MemorySpaceRepository protocol defined in core.ports.
    """

    def __init__(self, driver: Neo4jDriver) -> None:
        self._driver = driver

    def create_space(self, name: str) -> MemorySpace:
        """Create and persist a new MemorySpace.

        Raises ValueError if a MemorySpace with the given name already exists.
        """
        space = MemorySpace(name=name)  # validates name

        with self._driver.session() as session:
            # Check existence first
            result = session.run(
                "MATCH (s:MemorySpace {name: $name}) RETURN s.name AS name",
                name=name,
            )
            if result.single() is not None:
                raise ValueError(f"MemorySpace '{name}' already exists")

            # Create the node
            session.run(
                "CREATE (s:MemorySpace {name: $name}) RETURN s.name AS name",
                name=name,
            )

        return space

    def get_space(self, name: str) -> MemorySpace | None:
        """Retrieve a MemorySpace by name, or None if it does not exist."""
        with self._driver.session() as session:
            result = session.run(
                "MATCH (s:MemorySpace {name: $name}) RETURN s.name AS name",
                name=name,
            )
            record = result.single()
            if record is None:
                return None
            return MemorySpace(name=record["name"])

    def exists(self, name: str) -> bool:
        """Check whether a MemorySpace with the given name exists."""
        return self.get_space(name) is not None

    def ensure_constraints(self) -> None:
        """Create Neo4j uniqueness constraints and indexes.

        This is an infrastructure concern — called during setup,
        not during normal domain operations.
        """
        with self._driver.session() as session:
            session.run(
                "CREATE CONSTRAINT memory_space_name_unique "
                "IF NOT EXISTS FOR (s:MemorySpace) "
                "REQUIRE s.name IS UNIQUE"
            )
