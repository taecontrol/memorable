from __future__ import annotations

from memorable.core.application import build_status_payload


def status_tool() -> dict[str, object]:
    return build_status_payload()
