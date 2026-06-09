from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "v1_acceptance.py"
_SPEC = importlib.util.spec_from_file_location("v1_acceptance", _SCRIPT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
v1_acceptance = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(v1_acceptance)
assert isinstance(v1_acceptance, ModuleType)


def test_v1_acceptance_flow_explicitly_selects_neo4j_backend(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The real-Neo4j acceptance flow must not inherit SQLite defaults."""
    monkeypatch.delenv("MEMORABLE_STORAGE_BACKEND", raising=False)
    monkeypatch.setenv("MEMORABLE_NEO4J_URI", "bolt://acceptance-neo4j:7687")

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    expected_space: str | None = None
    observed_cli_backends: list[str | None] = []
    observed_mcp_backends: list[str | None] = []

    def fake_run_cli_json(
        command: str,
        args: list[str],
        *,
        cwd: Path,
        env: dict[str, str],
        timeout: int = 120,
    ) -> object:
        del command, timeout
        nonlocal expected_space
        observed_cli_backends.append(env.get("MEMORABLE_STORAGE_BACKEND"))

        if args[0] == "init":
            expected_space = args[args.index("--space") + 1]
            memory_dir = cwd / ".memorable"
            memory_dir.mkdir(parents=True, exist_ok=True)
            (memory_dir / "memory.yaml").write_text(
                f'''version: 1

space:
  name: "{expected_space}"
  description: "V1 clean-machine acceptance flow"

entities: []
relations: []
records: []
''',
                encoding="utf-8",
            )
            return {
                "space": expected_space,
                "status": "initialized",
                "profile_version": 1,
            }

        assert expected_space is not None
        if args == ["doctor", "--json"]:
            if env.get("MEMORABLE_STORAGE_BACKEND") == "neo4j":
                return [
                    {"check": "storage_backend", "ok": True},
                    {"check": "neo4j_connectivity", "ok": True},
                    {"check": "schema_constraints", "ok": True},
                    {"check": "vector_index", "ok": True},
                    {"check": "memory_profile_parses", "ok": True},
                    {"check": "embedding_provider_embeds", "ok": True},
                ]
            return [
                {"check": "storage_backend", "ok": True},
                {"check": "sqlite_path", "ok": True},
                {"check": "memory_profile_parses", "ok": True},
                {"check": "embedding_provider_embeds", "ok": True},
            ]

        if args[:2] == ["remember", "decision"]:
            return {
                "decision_id": v1_acceptance.DECISION_ID,
                "record_kind": "decision",
                "statement": v1_acceptance.DECISION_STATEMENT,
                "space": expected_space,
                "lifecycle_state": "current",
            }
        if args[:2] == ["remember", "observation"]:
            return {
                "observation_id": v1_acceptance.OBSERVATION_ID,
                "record_kind": "observation",
                "statement": v1_acceptance.OBSERVATION_STATEMENT,
                "space": expected_space,
                "lifecycle_state": "current",
            }
        if args[:2] == ["remember", "task"]:
            return {
                "task_id": v1_acceptance.TASK_ID,
                "record_kind": "task",
                "title": v1_acceptance.TASK_TITLE,
                "space": expected_space,
                "lifecycle_state": "open",
            }
        if args[:2] == ["remember", "entity"]:
            entity_id = args[args.index("--id") + 1]
            name = args[args.index("--name") + 1]
            return {
                "entity_id": entity_id,
                "entity_type": v1_acceptance.ENTITY_TYPE,
                "name": name,
                "record_kind": "entity",
                "space": expected_space,
            }
        if args[:2] == ["remember", "relation"]:
            return {
                "relation_id": v1_acceptance.RELATION_ID,
                "record_kind": "relation",
                "relation_type": v1_acceptance.RELATION_TYPE,
                "statement": v1_acceptance.RELATION_STATEMENT,
                "space": expected_space,
                "lifecycle_state": "current",
            }
        if args[0] == "search":
            return {
                "query": "Aurora Ridge Basalt Falls acceptance storage",
                "space": expected_space,
                "results": [
                    {"source_id": v1_acceptance.DECISION_ID},
                    {"source_id": v1_acceptance.ENTITY_A_ID},
                    {"source_id": v1_acceptance.ENTITY_B_ID},
                    {"source_id": v1_acceptance.RELATION_ID},
                ],
            }
        raise AssertionError(f"unexpected CLI args: {args}")

    async def fake_call_mcp_tool(
        command: str,
        tool_name: str,
        arguments: dict[str, object],
        *,
        cwd: Path,
        env: dict[str, str],
    ) -> dict[str, object]:
        del command, cwd
        observed_mcp_backends.append(env.get("MEMORABLE_STORAGE_BACKEND"))
        assert tool_name == "memorable_list_records"
        assert arguments["space"] == expected_space
        return {
            "space": expected_space,
            "records": [
                {
                    "id": v1_acceptance.DECISION_ID,
                    "type": "decision",
                    "label": v1_acceptance.DECISION_STATEMENT,
                    "lifecycle_state": "current",
                },
                {
                    "id": v1_acceptance.OBSERVATION_ID,
                    "type": "observation",
                    "label": v1_acceptance.OBSERVATION_STATEMENT,
                    "lifecycle_state": "current",
                },
                {
                    "id": v1_acceptance.TASK_ID,
                    "type": "task",
                    "label": v1_acceptance.TASK_TITLE,
                    "lifecycle_state": "open",
                },
                {
                    "id": v1_acceptance.RELATION_ID,
                    "type": "relation",
                    "label": v1_acceptance.RELATION_STATEMENT,
                    "lifecycle_state": "current",
                },
            ],
        }

    monkeypatch.setattr(v1_acceptance, "_run_cli_json", fake_run_cli_json)
    monkeypatch.setattr(v1_acceptance, "_call_mcp_tool", fake_call_mcp_tool)

    args = SimpleNamespace(memorable_cmd="fake memorable", mcp_cmd="fake mcp")

    v1_acceptance._run_flow(args, workspace)

    assert observed_cli_backends
    assert set(observed_cli_backends) == {"neo4j"}
    assert observed_mcp_backends == ["neo4j"]
