from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class DiagnosticStatus:
    product: str
    memory_space_scope: str
    service: str
    core_language: tuple[str, ...]

    def as_payload(self) -> dict[str, object]:
        payload = asdict(self)
        payload["core_language"] = list(self.core_language)
        return payload


class DiagnosticService:
    """Application service shared by human and agent-facing adapters."""

    def status(self) -> dict[str, object]:
        return DiagnosticStatus(
            product="Memorable",
            memory_space_scope="project",
            service="diagnostics",
            core_language=(
                "MemorySpace",
                "MemoryProfile",
                "MemoryRecord",
                "Source",
                "Provenance",
                "Temporal Semantics",
            ),
        ).as_payload()

