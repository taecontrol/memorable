"""Shared Neo4j connection policy for live runtime callers.

This is the single driver-construction path for live commands (production
context creation, and — once routed — runtime diagnostics). It encapsulates:

- local endpoint policy: ambiguous `localhost` is resolved to IPv4 loopback for
  the live connection only, because some local setups resolve `localhost` to the
  IPv6 loopback first and a heavier Bolt read can then hang on a defunct
  connection. Explicit IPv4, explicit IPv6 literals, custom local ports,
  non-local hosts, and remote/cloud schemes are preserved exactly.
- fail-fast connection settings so an unreachable runtime returns an actionable
  error in seconds instead of stalling for minutes.
- database binding: callers receive a driver facade whose ``session()`` opens
  against the configured Neo4j database.

Neo4j/Bolt/driver vocabulary stays inside this storage-adapter boundary.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable
from urllib.parse import urlsplit, urlunsplit

from neo4j import Driver, GraphDatabase

from memorable.config import RuntimeConfig

IPV4_LOOPBACK = "127.0.0.1"

# Bounded fail-fast settings: an unreachable runtime should error in seconds, not
# stall for minutes. These cap connection establishment and managed-transaction
# retry windows for every live caller.
CONNECTION_TIMEOUT_SECONDS = 5.0
MAX_TRANSACTION_RETRY_TIME_SECONDS = 5.0

# Sparse graphs legitimately lack some labels/properties/relationships. Suppress
# only UNRECOGNIZED notifications so a real query typo is not silently hidden by
# a broader filter.
_NOTIFICATIONS_DISABLED_CLASSIFICATIONS = ["UNRECOGNIZED"]

# Schemes whose `localhost` host is a local compatibility case we resolve to
# IPv4. Remote/cloud schemes (neo4j+s, neo4j+ssc) are never rewritten.
_LOCAL_COMPATIBILITY_SCHEMES = {"bolt", "neo4j"}


@runtime_checkable
class Neo4jDriver(Protocol):
    """Minimal connected driver surface returned to live callers."""

    def session(self) -> Any: ...

    def close(self) -> None: ...


class _DatabaseBoundDriver:
    """Driver facade whose sessions always target one Neo4j database."""

    def __init__(self, driver: Driver, database: str) -> None:
        self._driver = driver
        self._database = database

    def session(self) -> Any:
        return self._driver.session(database=self._database)

    def close(self) -> None:
        self._driver.close()


def resolve_bolt_uri(uri: str) -> str:
    """Return the effective Bolt URI for a live connection.

    Rewrites a `localhost` host to IPv4 loopback for local `bolt`/`neo4j`
    schemes only. Everything else — explicit IPv4, explicit IPv6 literals,
    custom ports, non-local hosts, and remote/cloud schemes — is returned
    unchanged.
    """
    parts = urlsplit(uri)
    if parts.scheme not in _LOCAL_COMPATIBILITY_SCHEMES:
        return uri
    if parts.hostname != "localhost":
        return uri

    userinfo = ""
    if parts.username:
        userinfo = parts.username
        if parts.password:
            userinfo += f":{parts.password}"
        userinfo += "@"
    port = f":{parts.port}" if parts.port is not None else ""
    netloc = f"{userinfo}{IPV4_LOOPBACK}{port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def connect(config: RuntimeConfig) -> Neo4jDriver:
    """Return a connectivity-verified Neo4j driver for live callers.

    Resolves the configured URI through the local endpoint policy, constructs a
    driver with shared fail-fast settings and benign-notification suppression,
    verifies connectivity, probes the configured database with a lightweight
    read, then returns a facade that binds every session to that Neo4j database.
    On failure the driver is closed and a
    ``ConnectionError`` naming the *configured* URI and database is raised so
    the owner recognizes which runtime Memorable tried to reach.
    """
    effective_uri = resolve_bolt_uri(config.neo4j.uri)
    driver = GraphDatabase.driver(
        effective_uri,
        auth=(config.neo4j.user, config.neo4j.password),
        notifications_disabled_classifications=_NOTIFICATIONS_DISABLED_CLASSIFICATIONS,
        connection_timeout=CONNECTION_TIMEOUT_SECONDS,
        max_transaction_retry_time=MAX_TRANSACTION_RETRY_TIME_SECONDS,
    )

    try:
        driver.verify_connectivity()
        with driver.session(database=config.neo4j.database) as session:
            session.run("RETURN 1").consume()
    except Exception as exc:
        driver.close()
        raise ConnectionError(
            f"Cannot connect to Neo4j database '{config.neo4j.database}' "
            f"at {config.neo4j.uri}. "
            f"Is Neo4j running? Try 'memorable db start' or check your "
            f"runtime config in .memorable/runtime.yaml.\n"
            f"Original error: {exc}"
        ) from exc

    return _DatabaseBoundDriver(driver, config.neo4j.database)
