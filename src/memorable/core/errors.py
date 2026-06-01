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
