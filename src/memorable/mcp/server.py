from __future__ import annotations

from typing import Protocol

from memorable.core.application import DiagnosticService


class StatusService(Protocol):
    def status(self) -> dict[str, object]:
        """Return a Memorable Core diagnostic payload."""


def build_status_payload(service: StatusService | None = None) -> dict[str, object]:
    diagnostic_service = service or DiagnosticService()
    return diagnostic_service.status()


def status_tool() -> dict[str, object]:
    return build_status_payload()

