"""Data models for the retrieval subsystem.

These are NOT canonical memory -- they are derived representations
used for search and ranking.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True)
class EmbeddingRecord:
    """A vector representation derived from Indexable Text.

    Embeddings are NOT canonical memory. They are derived from
    Indexable Text for semantic retrieval purposes only.
    """

    source_id: str
    source_kind: str  # "Entity", "Decision", "Task", "Observation", "Relation"
    space: str
    indexable_text: str
    vector: list[float]
    provider_name: str
    model_name: str
    dimensions: int
    indexable_text_hash: str = ""
    indexable_text_version: str = "1"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


def _total(values: dict[str, int]) -> int:
    return sum(values.values())


def _format_nonzero_counts(values: dict[str, int]) -> str:
    parts = [f"{kind}={count}" for kind, count in values.items() if count]
    return ", ".join(parts) if parts else "none"


@dataclass(frozen=True)
class EmbeddingCoverageReport:
    """Compatibility and freshness report for a MemorySpace's Embeddings."""

    space: str
    provider_name: str
    model_name: str
    dimensions: int
    expected_by_kind: dict[str, int]
    active_by_kind: dict[str, int]
    missing_by_kind: dict[str, int]
    stale_by_kind: dict[str, int]
    unusable_by_kind: dict[str, int]
    incompatible_by_kind: dict[str, int]

    @property
    def expected_total(self) -> int:
        return _total(self.expected_by_kind)

    @property
    def active_total(self) -> int:
        return _total(self.active_by_kind)

    @property
    def missing_total(self) -> int:
        return _total(self.missing_by_kind)

    @property
    def stale_total(self) -> int:
        return _total(self.stale_by_kind)

    @property
    def unusable_total(self) -> int:
        return _total(self.unusable_by_kind)

    @property
    def incompatible_total(self) -> int:
        return _total(self.incompatible_by_kind)

    @property
    def ok(self) -> bool:
        return (
            self.missing_total == 0
            and self.stale_total == 0
            and self.unusable_total == 0
            and self.incompatible_total == 0
        )

    @property
    def search_ready(self) -> bool:
        """Return whether search can use complete current Embedding coverage."""
        return self.ok

    @property
    def actionable_hint(self) -> str:
        if self.ok:
            return ""

        problems: list[str] = []
        if self.missing_total:
            problems.append(f"missing {_format_nonzero_counts(self.missing_by_kind)}")
        if self.stale_total:
            problems.append(f"stale {_format_nonzero_counts(self.stale_by_kind)}")
        if self.unusable_total:
            problems.append(
                f"unusable {_format_nonzero_counts(self.unusable_by_kind)}"
            )
        if self.incompatible_total:
            problems.append(
                "incompatible stored Embeddings "
                f"{_format_nonzero_counts(self.incompatible_by_kind)}"
            )

        problem_text = "; ".join(problems)
        return (
            f"Embedding coverage for MemorySpace '{self.space}' is not current "
            f"for provider '{self.provider_name}', model '{self.model_name}', "
            f"dimensions {self.dimensions}: {problem_text}. Run `memorable "
            f"reindex --space {self.space}` to rebuild derived Embeddings for "
            "the active settings."
        )


@dataclass(frozen=True)
class ReindexResult:
    """Result of rebuilding derived Embeddings for a MemorySpace."""

    space: str
    indexed_by_kind: dict[str, int]

    @property
    def indexed_total(self) -> int:
        return sum(self.indexed_by_kind.values())


@dataclass(frozen=True)
class SearchCandidate:
    """An intermediate result from cosine similarity search."""

    source_id: str
    source_kind: str
    score: float


@dataclass(frozen=True)
class RetrievalResult:
    """A ranked retrieval result with provenance-aware explanation.

    Each result explains why it was returned, including lifecycle state
    and provenance summary.
    """

    source_id: str
    source_kind: str
    lifecycle_state: str
    score: float
    explanation: list[str]
    provenance_summary: dict[str, str]
