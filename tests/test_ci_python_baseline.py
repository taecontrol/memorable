from __future__ import annotations

import re
from pathlib import Path

CI_WORKFLOW = (
    Path(__file__).resolve().parent.parent / ".github" / "workflows" / "ci.yml"
)


def test_ci_installs_python_314_for_every_job() -> None:
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")

    installs = re.findall(r"uv python install ([^\s]+)", workflow)

    assert installs == ["3.14", "3.14", "3.14"]


def test_ci_does_not_install_python_39() -> None:
    workflow = CI_WORKFLOW.read_text(encoding="utf-8")

    assert "uv python install 3.9" not in workflow
