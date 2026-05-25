"""Temporal parsing and ID conventions for Memorable Core."""

from __future__ import annotations

from datetime import UTC, datetime


def parse_iso_timestamp(value: str) -> datetime:
    """Parse an ISO 8601 timestamp string, handling the Z suffix for Python 3.9.

    Returns a timezone-aware datetime (defaults to UTC when no tzinfo is present).
    """
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def make_episode_id(source_id: str, at: datetime) -> str:
    """Build a deterministic Episode ID from a Source ID and timestamp.

    Convention: ``episode:{source_suffix}:{iso_timestamp}``
    where *source_suffix* is the part of the Source ID after the first colon.
    """
    source_suffix = source_id.split(":", 1)[-1]
    return f"episode:{source_suffix}:{at.isoformat()}"
