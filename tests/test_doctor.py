from __future__ import annotations

import json

from memorable.config import RuntimeConfig


def test_doctor_reports_neo4j_connectivity_pass() -> None:
    from memorable.runtime.doctor import run_diagnostics

    results = run_diagnostics(RuntimeConfig(), ping_neo4j=lambda _config: None)

    assert results == [{"check": "neo4j_connectivity", "ok": True, "hint": ""}]


def test_doctor_reports_neo4j_connectivity_failure_with_hint() -> None:
    from memorable.runtime.doctor import run_diagnostics

    expected_hint = (
        "Start Neo4j with 'memorable db start' or check .memorable/runtime.yaml."
    )

    def fail(_config: RuntimeConfig) -> None:
        raise ConnectionError("unreachable")

    results = run_diagnostics(RuntimeConfig(), ping_neo4j=fail)

    assert results == [
        {
            "check": "neo4j_connectivity",
            "ok": False,
            "hint": expected_hint,
        }
    ]


def test_doctor_aggregate_all_pass_logic() -> None:
    from memorable.runtime.doctor import all_checks_passed

    assert all_checks_passed([{"check": "neo4j_connectivity", "ok": True, "hint": ""}])
    assert not all_checks_passed(
        [{"check": "neo4j_connectivity", "ok": False, "hint": "fix it"}]
    )


def test_doctor_cli_json_outputs_structured_results(monkeypatch, capsys) -> None:
    from memorable.cli import main

    monkeypatch.setattr(
        "memorable.cli.run_diagnostics",
        lambda _config: [
            {"check": "neo4j_connectivity", "ok": True, "hint": ""},
        ],
    )
    monkeypatch.setattr(
        "memorable.cli.load_runtime_config", lambda **_kwargs: RuntimeConfig()
    )

    rc = main(["doctor", "--json"])

    assert rc == 0
    assert json.loads(capsys.readouterr().out) == [
        {"check": "neo4j_connectivity", "ok": True, "hint": ""},
    ]


def test_doctor_cli_human_output_includes_failure_hint(monkeypatch, capsys) -> None:
    from memorable.cli import main

    monkeypatch.setattr(
        "memorable.cli.run_diagnostics",
        lambda _config: [
            {"check": "neo4j_connectivity", "ok": False, "hint": "start Neo4j"},
        ],
    )
    monkeypatch.setattr(
        "memorable.cli.load_runtime_config", lambda **_kwargs: RuntimeConfig()
    )

    rc = main(["doctor"])

    assert rc == 1
    out = capsys.readouterr().out
    assert "FAIL neo4j_connectivity" in out
    assert "Hint: start Neo4j" in out
