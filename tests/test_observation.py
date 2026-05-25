"""Tests for Observation record type with remember and supersession support.

Covers slice #44 acceptance criteria:
- Observation frozen dataclass with validation (empty id/statement rejected)
- ObservationRepository protocol and InMemoryObservationRepository
- RememberObservationService with profile validation (extends: Observation)
- Supersession wiring when supersedes is provided
- Generic temporal services work with ObservationRepository
- MCP tool and CLI command
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

# --- Fixture data ---

FIXTURE_TIMESTAMP_V1 = datetime(2026, 5, 25, 9, 0, 0, tzinfo=UTC)
FIXTURE_TIMESTAMP_V2 = datetime(2026, 5, 25, 9, 10, 0, tzinfo=UTC)

STATEMENT_V1 = "The team prefers async communication over synchronous meetings."
STATEMENT_V2 = (
    "The team prefers async communication but holds weekly sync standups."
)

V1_ID = "observation:team-comm:v1"
V2_ID = "observation:team-comm:v2"
SOURCE_ID = "source:agent-session"


# =====================================================================
# Domain model tests
# =====================================================================


class TestObservationModel:
    """Observation is a remembered assertion with temporal validity."""

    def test_observation_has_required_fields(self) -> None:
        from memorable.core.models import Observation

        obs = Observation(
            id=V1_ID,
            statement=STATEMENT_V1,
            space="memorable",
            validity_time=FIXTURE_TIMESTAMP_V1,
            invalidation_time=None,
            lifecycle_state="current",
            supersedes=None,
            superseded_by=None,
        )
        assert obs.id == V1_ID
        assert obs.statement == STATEMENT_V1
        assert obs.space == "memorable"
        assert obs.validity_time == FIXTURE_TIMESTAMP_V1
        assert obs.invalidation_time is None
        assert obs.lifecycle_state == "current"
        assert obs.supersedes is None
        assert obs.superseded_by is None

    def test_observation_is_frozen(self) -> None:
        from memorable.core.models import Observation

        obs = Observation(
            id="observation:x",
            statement="X",
            space="s",
            validity_time=FIXTURE_TIMESTAMP_V1,
            invalidation_time=None,
            lifecycle_state="current",
            supersedes=None,
            superseded_by=None,
        )
        with pytest.raises(AttributeError):
            obs.statement = "Y"  # type: ignore[misc]

    def test_observation_requires_non_empty_id(self) -> None:
        from memorable.core.models import Observation

        with pytest.raises(ValueError, match="id"):
            Observation(
                id="",
                statement="X",
                space="s",
                validity_time=FIXTURE_TIMESTAMP_V1,
                invalidation_time=None,
                lifecycle_state="current",
                supersedes=None,
                superseded_by=None,
            )

    def test_observation_requires_non_empty_statement(self) -> None:
        from memorable.core.models import Observation

        with pytest.raises(ValueError, match="statement"):
            Observation(
                id="observation:x",
                statement="",
                space="s",
                validity_time=FIXTURE_TIMESTAMP_V1,
                invalidation_time=None,
                lifecycle_state="current",
                supersedes=None,
                superseded_by=None,
            )
