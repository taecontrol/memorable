from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def pythonpath_env() -> dict[str, str]:
    env = os.environ.copy()
    src_path = str(PROJECT_ROOT / "src")
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        src_path if not existing else f"{src_path}{os.pathsep}{existing}"
    )
    return env


def assert_core_language(payload: dict[str, object]) -> None:
    assert payload["product"] == "Memorable"
    assert payload["memory_space_scope"] == "project"
    assert payload["service"] == "diagnostics"

    text = json.dumps(payload).lower()
    assert "node" not in text
    assert "edge" not in text


def test_package_import_exposes_version() -> None:
    import memorable

    assert memorable.__version__ == "0.0.1"


def test_cli_status_smoke_uses_core_language() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "memorable.cli", "status"],
        cwd=PROJECT_ROOT,
        env=pythonpath_env(),
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert_core_language(json.loads(result.stdout))


def test_mcp_status_smoke_uses_core_language() -> None:
    from memorable.mcp.server import status_tool

    assert_core_language(status_tool())


def test_cli_and_mcp_status_share_application_service() -> None:
    from memorable.core.application import build_status_payload

    class RecordingDiagnosticService:
        def __init__(self) -> None:
            self.calls = 0

        def status(self) -> dict[str, object]:
            self.calls += 1
            return {
                "product": "Memorable",
                "memory_space_scope": "project",
                "service": "diagnostics",
            }

    service = RecordingDiagnosticService()

    expected = {
        "product": "Memorable",
        "memory_space_scope": "project",
        "service": "diagnostics",
    }
    assert build_status_payload(service) == expected
    assert build_status_payload(service) == expected
    assert service.calls == 2
