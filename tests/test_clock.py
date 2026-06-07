from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta, timezone

import pytest


def test_fixed_clock_returns_configured_creation_time_in_utc() -> None:
    from memorable.core.clock import FixedClock

    instant = datetime(
        2026,
        6,
        7,
        12,
        34,
        56,
        123456,
        tzinfo=timezone(timedelta(hours=2)),
    )

    assert FixedClock(instant).now() == datetime(
        2026,
        6,
        7,
        10,
        34,
        56,
        123456,
        tzinfo=UTC,
    )


def test_fixed_clock_rejects_naive_creation_time() -> None:
    from memorable.core.clock import FixedClock

    with pytest.raises(ValueError, match="Creation Time"):
        FixedClock(datetime(2026, 6, 7, 10, 34, 56, 123456))


def test_system_clock_returns_canonical_utc_creation_time() -> None:
    from memorable.core.clock import SystemClock

    creation_time = SystemClock().now()

    assert creation_time.tzinfo is not None
    assert creation_time.utcoffset() == timedelta(0)
    assert re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}\+00:00",
        creation_time.isoformat(timespec="microseconds"),
    )
