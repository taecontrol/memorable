from __future__ import annotations

import json
from pathlib import Path

from memorable.config import EmbeddingSettings, RuntimeConfig
from memorable.runtime.doctor import DiagnosticProbes

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
        "name": "record_space_id_unique",
        "type": "UNIQUENESS",
        "labelsOrTypes": ["Record"],
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
EXPECTED_VECTOR_INDEXES = [
    {
        "name": "memorable_embeddings_vector",
        "type": "VECTOR",
        "labelsOrTypes": ["Embedding"],
        "properties": ["vector"],
    }
]

NEO4J_CONNECTIVITY_HINT = (
    "Start Neo4j with 'memorable db start' or check .memorable/runtime.yaml."
)
SCHEMA_CONSTRAINTS_HINT = "Run 'memorable init' to bootstrap schema constraints."
VECTOR_INDEX_HINT = "Run 'memorable init' to bootstrap the vector index."


class _EmbeddingProvider:
    def __init__(self, vector: list[float] | None = None) -> None:
        self._vector = vector if vector is not None else [0.0] * 384

    def embed(self, _text: str) -> list[float]:
        return self._vector


def _probes(
    *,
    ping_neo4j=lambda _config: None,
    list_schema_constraints=lambda _config: EXPECTED_SCHEMA_CONSTRAINTS,
    list_vector_indexes=lambda _config: EXPECTED_VECTOR_INDEXES,
    build_embedding_provider=lambda _settings, api_key=None: _EmbeddingProvider(),
    profile_path: Path | None = None,
    load_profile_from_yaml=lambda _yaml_text: object(),
) -> DiagnosticProbes:
    """Build a DiagnosticProbes seam with passing defaults, overriding as needed."""
    return DiagnosticProbes(
        ping_neo4j=ping_neo4j,
        list_schema_constraints=list_schema_constraints,
        list_vector_indexes=list_vector_indexes,
        build_embedding_provider=build_embedding_provider,
        profile_path=profile_path,
        load_profile_from_yaml=load_profile_from_yaml,
    )


def _by_check(results: list) -> dict:
    return {result["check"]: result for result in results}


def test_doctor_reports_neo4j_connectivity_pass() -> None:
    from memorable.runtime.doctor import run_diagnostics

    results = run_diagnostics(
        RuntimeConfig(),
        probes=_probes(list_schema_constraints=lambda _config: []),
    )

    assert _by_check(results)["neo4j_connectivity"] == {
        "check": "neo4j_connectivity",
        "ok": True,
        "hint": "",
    }


def test_doctor_reports_schema_constraints_pass() -> None:
    from memorable.runtime.doctor import run_diagnostics

    results = run_diagnostics(RuntimeConfig(), probes=_probes())

    assert _by_check(results)["schema_constraints"] == {
        "check": "schema_constraints",
        "ok": True,
        "hint": "",
    }


def test_doctor_reports_schema_constraints_pass_with_generated_names() -> None:
    from memorable.runtime.doctor import run_diagnostics

    generated_name_constraints = [
        constraint | {"name": f"constraint_{index}"}
        for index, constraint in enumerate(EXPECTED_SCHEMA_CONSTRAINTS)
    ]

    results = run_diagnostics(
        RuntimeConfig(),
        probes=_probes(
            list_schema_constraints=lambda _config: generated_name_constraints
        ),
    )

    assert _by_check(results)["schema_constraints"] == {
        "check": "schema_constraints",
        "ok": True,
        "hint": "",
    }


def test_doctor_reports_schema_constraints_failure_with_hint() -> None:
    from memorable.runtime.doctor import run_diagnostics

    results = run_diagnostics(
        RuntimeConfig(),
        probes=_probes(
            list_schema_constraints=lambda _config: [
                constraint
                for constraint in EXPECTED_SCHEMA_CONSTRAINTS
                if constraint["name"] != "task_space_id_unique"
            ],
        ),
    )

    assert _by_check(results)["schema_constraints"] == {
        "check": "schema_constraints",
        "ok": False,
        "hint": SCHEMA_CONSTRAINTS_HINT,
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
        probes=_probes(list_schema_constraints=lambda _config: malformed_constraints),
    )

    assert _by_check(results)["schema_constraints"] == {
        "check": "schema_constraints",
        "ok": False,
        "hint": SCHEMA_CONSTRAINTS_HINT,
    }


def test_doctor_reports_neo4j_connectivity_failure_with_hint() -> None:
    from memorable.runtime.doctor import run_diagnostics

    def fail(_config: RuntimeConfig) -> None:
        raise ConnectionError("unreachable")

    results = run_diagnostics(RuntimeConfig(), probes=_probes(ping_neo4j=fail))

    assert _by_check(results)["neo4j_connectivity"] == {
        "check": "neo4j_connectivity",
        "ok": False,
        "hint": NEO4J_CONNECTIVITY_HINT,
    }


def test_doctor_connectivity_failure_short_circuits_schema_and_vector() -> None:
    """When Neo4j is unreachable, schema/vector checks must not run the SHOW
    queries and must report the connectivity hint, NOT the 'memorable init' hint.
    """
    from memorable.runtime.doctor import run_diagnostics

    def fail(_config: RuntimeConfig) -> None:
        raise ConnectionError("unreachable")

    def must_not_run(_config: RuntimeConfig):
        raise AssertionError("SHOW query ran despite connectivity failure")

    results = run_diagnostics(
        RuntimeConfig(),
        probes=_probes(
            ping_neo4j=fail,
            list_schema_constraints=must_not_run,
            list_vector_indexes=must_not_run,
        ),
    )

    by_check = _by_check(results)
    assert by_check["schema_constraints"] == {
        "check": "schema_constraints",
        "ok": False,
        "hint": NEO4J_CONNECTIVITY_HINT,
    }
    assert by_check["vector_index"] == {
        "check": "vector_index",
        "ok": False,
        "hint": NEO4J_CONNECTIVITY_HINT,
    }


def test_doctor_schema_show_query_error_is_not_init_hint() -> None:
    """If connectivity passes but the SHOW CONSTRAINTS query raises, that is a
    query error, NOT proof the schema is absent: report the connectivity hint.
    """
    from memorable.runtime.doctor import run_diagnostics

    def raises(_config: RuntimeConfig):
        raise RuntimeError("SHOW CONSTRAINTS failed")

    results = run_diagnostics(
        RuntimeConfig(),
        probes=_probes(list_schema_constraints=raises),
    )

    assert _by_check(results)["schema_constraints"] == {
        "check": "schema_constraints",
        "ok": False,
        "hint": NEO4J_CONNECTIVITY_HINT,
    }


def test_doctor_vector_show_query_error_is_not_init_hint() -> None:
    """If connectivity passes but the SHOW INDEXES query raises, report the
    connectivity hint rather than 'run memorable init'.
    """
    from memorable.runtime.doctor import run_diagnostics

    def raises(_config: RuntimeConfig):
        raise RuntimeError("SHOW INDEXES failed")

    results = run_diagnostics(
        RuntimeConfig(),
        probes=_probes(list_vector_indexes=raises),
    )

    assert _by_check(results)["vector_index"] == {
        "check": "vector_index",
        "ok": False,
        "hint": NEO4J_CONNECTIVITY_HINT,
    }


def test_doctor_connected_with_empty_schema_yields_init_hint() -> None:
    """Connected + SHOW returns empty proves the constraint is genuinely absent:
    only then do we emit the 'memorable init' hint.
    """
    from memorable.runtime.doctor import run_diagnostics

    results = run_diagnostics(
        RuntimeConfig(),
        probes=_probes(
            list_schema_constraints=lambda _config: [],
            list_vector_indexes=lambda _config: [],
        ),
    )

    by_check = _by_check(results)
    assert by_check["schema_constraints"] == {
        "check": "schema_constraints",
        "ok": False,
        "hint": SCHEMA_CONSTRAINTS_HINT,
    }
    assert by_check["vector_index"] == {
        "check": "vector_index",
        "ok": False,
        "hint": VECTOR_INDEX_HINT,
    }


def test_doctor_reports_vector_index_pass() -> None:
    from memorable.runtime.doctor import run_diagnostics

    results = run_diagnostics(RuntimeConfig(), probes=_probes())

    assert _by_check(results)["vector_index"] == {
        "check": "vector_index",
        "ok": True,
        "hint": "",
    }


def test_doctor_reports_vector_index_failure_with_hint() -> None:
    from memorable.runtime.doctor import run_diagnostics

    results = run_diagnostics(
        RuntimeConfig(),
        probes=_probes(list_vector_indexes=lambda _config: []),
    )

    assert _by_check(results)["vector_index"] == {
        "check": "vector_index",
        "ok": False,
        "hint": VECTOR_INDEX_HINT,
    }


def test_doctor_reports_vector_index_failure_for_unrelated_vector_index() -> None:
    from memorable.runtime.doctor import run_diagnostics

    results = run_diagnostics(
        RuntimeConfig(),
        probes=_probes(
            list_vector_indexes=lambda _config: [
                {
                    "name": "other_vector_index",
                    "type": "VECTOR",
                    "labelsOrTypes": ["Other"],
                    "properties": ["embedding"],
                }
            ],
        ),
    )

    assert _by_check(results)["vector_index"] == {
        "check": "vector_index",
        "ok": False,
        "hint": VECTOR_INDEX_HINT,
    }


def test_doctor_reports_embedding_provider_embed_pass() -> None:
    from memorable.runtime.doctor import run_diagnostics

    results = run_diagnostics(RuntimeConfig(), probes=_probes())

    assert _by_check(results)["embedding_provider_embeds"] == {
        "check": "embedding_provider_embeds",
        "ok": True,
        "hint": "fastembed first use may download the local model (~67MB).",
    }


def test_doctor_reports_embedding_provider_build_failure_with_hint() -> None:
    from memorable.runtime.doctor import run_diagnostics

    def fail(_settings: object, api_key: str | None = None) -> object:
        raise RuntimeError("bad embedding settings")

    results = run_diagnostics(
        RuntimeConfig(),
        probes=_probes(build_embedding_provider=fail),
    )

    result = _by_check(results)["embedding_provider_embeds"]
    assert result["check"] == "embedding_provider_embeds"
    assert result["ok"] is False
    assert "fastembed" in result["hint"]
    assert "BAAI/bge-small-en-v1.5" in result["hint"]
    assert (
        "Check embeddings.provider, model, dimensions, and API key."
        in result["hint"]
    )
    assert "bad embedding settings" in result["hint"]


def test_doctor_reports_embedding_provider_embed_failure_with_hint() -> None:
    from memorable.runtime.doctor import run_diagnostics

    class FailingEmbeddingProvider:
        def embed(self, _text: str) -> list[float]:
            raise RuntimeError("No embedding data received")

    config = RuntimeConfig(
        embeddings=EmbeddingSettings(
            provider="openrouter",
            model="google/gemini-embedding-2-preview",
            dimensions=768,
            api_key="test-key",
        )
    )

    results = run_diagnostics(
        config,
        probes=_probes(
            build_embedding_provider=lambda _settings, api_key=None: (
                FailingEmbeddingProvider()
            )
        ),
    )

    result = _by_check(results)["embedding_provider_embeds"]
    assert result["check"] == "embedding_provider_embeds"
    assert result["ok"] is False
    assert "openrouter" in result["hint"]
    assert "google/gemini-embedding-2-preview" in result["hint"]
    assert (
        "Check embeddings.provider, model, dimensions, and API key."
        in result["hint"]
    )
    assert "No embedding data received" in result["hint"]


def test_doctor_reports_embedding_provider_empty_vector_failure() -> None:
    from memorable.runtime.doctor import run_diagnostics

    results = run_diagnostics(
        RuntimeConfig(),
        probes=_probes(
            build_embedding_provider=lambda _settings, api_key=None: _EmbeddingProvider(
                []
            )
        ),
    )

    result = _by_check(results)["embedding_provider_embeds"]
    assert result["check"] == "embedding_provider_embeds"
    assert result["ok"] is False
    assert "provider returned no Embedding" in result["hint"]


def test_doctor_reports_embedding_provider_wrong_dimension_failure() -> None:
    from memorable.runtime.doctor import run_diagnostics

    config = RuntimeConfig(
        embeddings=EmbeddingSettings(provider="fake", model="hash-based", dimensions=3)
    )

    results = run_diagnostics(
        config,
        probes=_probes(
            build_embedding_provider=lambda _settings, api_key=None: _EmbeddingProvider(
                [0.0, 1.0]
            )
        ),
    )

    result = _by_check(results)["embedding_provider_embeds"]
    assert result["check"] == "embedding_provider_embeds"
    assert result["ok"] is False
    assert "provider returned 2 dimensions; runtime configured 3" in result["hint"]


def test_doctor_reports_memory_profile_parse_pass(tmp_path: Path) -> None:
    from memorable.runtime.doctor import run_diagnostics

    profile_path = tmp_path / ".memorable" / "memory.yaml"
    profile_path.parent.mkdir()
    profile_path.write_text("valid profile", encoding="utf-8")

    results = run_diagnostics(
        RuntimeConfig(),
        probes=_probes(profile_path=profile_path),
    )

    assert _by_check(results)["memory_profile_parses"] == {
        "check": "memory_profile_parses",
        "ok": True,
        "hint": "",
    }


def test_doctor_reports_memory_profile_parse_failure_with_hint(
    tmp_path: Path,
) -> None:
    from memorable.runtime.doctor import run_diagnostics

    profile_path = tmp_path / ".memorable" / "memory.yaml"
    profile_path.parent.mkdir()
    profile_path.write_text("invalid profile", encoding="utf-8")

    def fail(_yaml_text: str) -> object:
        raise ValueError("bad profile")

    results = run_diagnostics(
        RuntimeConfig(),
        probes=_probes(profile_path=profile_path, load_profile_from_yaml=fail),
    )

    assert _by_check(results)["memory_profile_parses"] == {
        "check": "memory_profile_parses",
        "ok": False,
        "hint": "Fix .memorable/memory.yaml so it is valid MemoryProfile YAML.",
    }


def test_doctor_skips_memory_profile_parse_when_profile_is_absent(
    tmp_path: Path,
) -> None:
    from memorable.runtime.doctor import all_checks_passed, run_diagnostics

    def must_not_run(_yaml_text: str) -> object:
        raise AssertionError("profile parser should not run when profile is absent")

    results = run_diagnostics(
        RuntimeConfig(),
        probes=_probes(
            profile_path=tmp_path / ".memorable" / "memory.yaml",
            load_profile_from_yaml=must_not_run,
        ),
    )

    assert "memory_profile_parses" not in {result["check"] for result in results}
    assert all_checks_passed(results)


def test_diagnostic_probes_defaults_are_the_real_module_callables() -> None:
    """The default DiagnosticProbes wires the real runtime probes, so the
    public happy-path call run_diagnostics(config) touches the live runtime.
    """
    from memorable.runtime import doctor

    probes = doctor.DiagnosticProbes()

    assert probes.ping_neo4j is doctor.ping_neo4j
    assert probes.list_schema_constraints is doctor.list_schema_constraints
    assert probes.list_vector_indexes is doctor.list_vector_indexes
    assert probes.build_embedding_provider is doctor.build_embedding_provider
    assert probes.load_profile_from_yaml is doctor.load_profile_from_yaml
    assert probes.profile_path is None


def test_run_diagnostics_constructs_default_probes_when_omitted(monkeypatch) -> None:
    """When probes is omitted, run_diagnostics builds a default DiagnosticProbes
    and drives the checks through it — proven without network by replacing the
    DiagnosticProbes symbol with a no-op factory and asserting it was used.
    """
    from memorable.runtime import doctor

    constructed: list[bool] = []

    def make_noop_probes() -> DiagnosticProbes:
        constructed.append(True)
        return _probes(
            list_schema_constraints=lambda _config: EXPECTED_SCHEMA_CONSTRAINTS,
            list_vector_indexes=lambda _config: EXPECTED_VECTOR_INDEXES,
        )

    monkeypatch.setattr(doctor, "DiagnosticProbes", make_noop_probes)

    results = doctor.run_diagnostics(RuntimeConfig())

    assert constructed == [True]
    assert _by_check(results)["neo4j_connectivity"]["ok"] is True


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


def test_doctor_cli_resolves_config_with_environment_overrides(
    monkeypatch, capsys
) -> None:
    """doctor must diagnose the same runtime that live commands act on: it
    resolves config with non-secret MEMORABLE_* process overrides honoured.
    """
    from unittest.mock import MagicMock

    from memorable.cli import main

    mock_load = MagicMock(return_value=RuntimeConfig())
    monkeypatch.setattr("memorable.cli.load_runtime_config", mock_load)
    monkeypatch.setattr("memorable.cli.run_diagnostics", lambda _config: [])

    main(["doctor", "--json"])

    assert mock_load.call_args.kwargs.get("include_environment_overrides") is True


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
