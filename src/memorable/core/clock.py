"""Clock port for Creation Time stamping in Memorable Core."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    """Substitutable source of Creation Time for memory writes."""

    def now(self) -> datetime:
        """Return the current Creation Time."""
        ...


def _canonical_utc(creation_time: datetime) -> datetime:
    if creation_time.tzinfo is None or creation_time.utcoffset() is None:
        raise ValueError("Creation Time must be timezone-aware.")
    return creation_time.astimezone(UTC)


class SystemClock:
    """System-backed Clock for production Creation Time stamping."""

    def now(self) -> datetime:
        """Return the current Creation Time as timezone-aware UTC."""
        return datetime.now(UTC)


@dataclass(frozen=True)
class FixedClock:
    """Deterministic Clock for tests."""

    instant: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "instant", _canonical_utc(self.instant))

    def now(self) -> datetime:
        """Return the configured Creation Time."""
        return self.instant
