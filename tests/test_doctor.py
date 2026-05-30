from __future__ import annotations

import json

from memorable.config import RuntimeConfig

EXPECTED_SCHEMA_CONSTRAINTS = [
    {
        "name": "memory_space_name_unique",
        "type": "UNIQUENESS",
        "labelsOrTypes": ["MemorySpace"],
        "properties": ["name"],
    },
    {
        "name": "entity_space_id_unique",
        "type": "UNIQUENESS",
        "labelsOrTypes": ["Entity"],
        "properties": ["space", "id"],
    },
    {
        "name": "decision_space_id_unique",
        "type": "UNIQUENESS",
        "labelsOrTypes": ["Decision"],
        "properties": ["space", "id"],
    },
    {
        "name": "task_space_id_unique",
        "type": "UNIQUENESS",
        "labelsOrTypes": ["Task"],
        "properties": ["space", "id"],
    },
    {
        "name": "observation_space_id_unique",
        "type": "UNIQUENESS",
        "labelsOrTypes": ["Observation"],
        "properties": ["space", "id"],
    },
    {
        "name": "relation_space_id_unique",
        "type": "UNIQUENESS",
        "labelsOrTypes": ["Relation"],
        "properties": ["space", "id"],
    },
]


def test_doctor_reports_neo4j_connectivity_pass() -> None:
    from memorable.runtime.doctor import run_diagnostics

    results = run_diagnostics(
        RuntimeConfig(),
        ping_neo4j=lambda _config: None,
        list_schema_constraints=lambda _config: [],
    )

    assert {result["check"]: result for result in results}[
        "neo4j_connectivity"
    ] == {"check": "neo4j_connectivity", "ok": True, "hint": ""}


def test_doctor_reports_schema_constraints_pass() -> None:
    from memorable.runtime.doctor import run_diagnostics

    results = run_diagnostics(
        RuntimeConfig(),
        ping_neo4j=lambda _config: None,
        list_schema_constraints=lambda _config: EXPECTED_SCHEMA_CONSTRAINTS,
    )

    assert {result["check"]: result for result in results}[
        "schema_constraints"
    ] == {"check": "schema_constraints", "ok": True, "hint": ""}


def test_doctor_reports_schema_constraints_pass_with_generated_names() -> None:
    from memorable.runtime.doctor import run_diagnostics

    generated_name_constraints = [
        constraint | {"name": f"constraint_{index}"}
        for index, constraint in enumerate(EXPECTED_SCHEMA_CONSTRAINTS)
    ]

    results = run_diagnostics(
        RuntimeConfig(),
        ping_neo4j=lambda _config: None,
        list_schema_constraints=lambda _config: generated_name_constraints,
    )

    assert {result["check"]: result for result in results}[
        "schema_constraints"
    ] == {"check": "schema_constraints", "ok": True, "hint": ""}


def test_doctor_reports_schema_constraints_failure_with_hint() -> None:
    from memorable.runtime.doctor import run_diagnostics

    results = run_diagnostics(
        RuntimeConfig(),
        ping_neo4j=lambda _config: None,
        list_schema_constraints=lambda _config: [
            constraint
            for constraint in EXPECTED_SCHEMA_CONSTRAINTS
            if constraint["name"] != "task_space_id_unique"
        ],
    )

    assert {result["check"]: result for result in results}[
        "schema_constraints"
    ] == {
        "check": "schema_constraints",
        "ok": False,
        "hint": "Run 'memorable init' to bootstrap schema constraints.",
    }


def test_doctor_reports_schema_constraints_failure_when_name_has_wrong_shape() -> None:
    from memorable.runtime.doctor import run_diagnostics

    malformed_constraints = [
        constraint | {"properties": ["id"]}
        if constraint["name"] == "entity_space_id_unique"
        else constraint
        for constraint in EXPECTED_SCHEMA_CONSTRAINTS
    ]

    results = run_diagnostics(
        RuntimeConfig(),
        ping_neo4j=lambda _config: None,
        list_schema_constraints=lambda _config: malformed_constraints,
    )

    assert {result["check"]: result for result in results}[
        "schema_constraints"
    ] == {
        "check": "schema_constraints",
        "ok": False,
        "hint": "Run 'memorable init' to bootstrap schema constraints.",
    }


def test_doctor_reports_neo4j_connectivity_failure_with_hint() -> None:
    from memorable.runtime.doctor import run_diagnostics

    expected_hint = (
        "Start Neo4j with 'memorable db start' or check .memorable/runtime.yaml."
    )

    def fail(_config: RuntimeConfig) -> None:
        raise ConnectionError("unreachable")

    results = run_diagnostics(
        RuntimeConfig(), ping_neo4j=fail, list_schema_constraints=lambda _config: []
    )

    assert {result["check"]: result for result in results}[
        "neo4j_connectivity"
    ] == {
        "check": "neo4j_connectivity",
        "ok": False,
        "hint": expected_hint,
    }


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
