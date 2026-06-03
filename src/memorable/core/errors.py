from __future__ import annotations


class DuplicateRecordError(ValueError):
    """Raised when remembering a MemoryRecord would reuse an id in a space."""

    def __init__(self, *, record_kind: str, space: str, record_id: str) -> None:
        self.record_kind = record_kind
        self.space = space
        self.record_id = record_id
        record_label = record_kind.capitalize()
        super().__init__(
            f"{record_label} record id '{record_id}' already exists in "
            f"MemorySpace '{space}'. Use correct to update the existing "
            "record, or choose a new record id to remember a distinct "
            f"{record_label}."
        )


class NothingToForgetError(ValueError):
    """Raised when Forget targets no memory in a MemorySpace."""

    def __init__(self, *, space: str, record_id: str) -> None:
        self.space = space
        self.record_id = record_id
        super().__init__(
            f"Nothing to forget in MemorySpace '{space}' with id '{record_id}'."
        )


class CannotForgetRecordInSupersessionChainError(ValueError):
    """Raised when Forget would erase a record woven into preserved history."""

    def __init__(
        self,
        *,
        record_kind: str,
        space: str,
        record_id: str,
        supersedes: str | None,
        superseded_by: str | None,
    ) -> None:
        self.record_kind = record_kind
        self.space = space
        self.record_id = record_id
        self.supersedes = supersedes
        self.superseded_by = superseded_by

        chain_parts = []
        if supersedes is not None:
            chain_parts.append(f"supersedes '{supersedes}'")
        if superseded_by is not None:
            chain_parts.append(f"is superseded by '{superseded_by}'")
        chain = "; ".join(chain_parts)
        super().__init__(
            f"Cannot forget {record_kind} '{record_id}' in MemorySpace '{space}' "
            f"because it participates in a supersession chain ({chain}). "
            "Resolve the chain first or forget each chain member deliberately."
        )
