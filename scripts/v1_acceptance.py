#!/usr/bin/env python3
"""Run the V1 clean-machine acceptance flow against public surfaces only."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shlex
import subprocess
import sys
import uuid
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

SOURCE = "source:v1-acceptance"
DECISION_ID = "decision:v1-storage"
OBSERVATION_ID = "observation:v1-doctor"
TASK_ID = "task:v1-review"
ENTITY_TYPE = "Trail"
ENTITY_A_ID = "entity:aurora-ridge"
ENTITY_B_ID = "entity:basalt-falls"
RELATION_TYPE = "connects-to"
RELATION_ID = "relation:aurora-basalt"

DECISION_STATEMENT = "Use Neo4j as the V1 acceptance storage runtime."
OBSERVATION_STATEMENT = "Doctor passes after init on a clean MemorySpace."
TASK_TITLE = "Review V1 acceptance records through MCP list_records."
ENTITY_A_NAME = "Aurora Ridge"
ENTITY_B_NAME = "Basalt Falls"
RELATION_STATEMENT = "Aurora Ridge connects to Basalt Falls."


class AcceptanceFailure(AssertionError):
    """Raised when an observable acceptance assertion fails."""


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        with _workspace(args.workspace, args.keep_workspace) as workspace:
            _run_flow(args, workspace)
    except AcceptanceFailure as exc:
        print(f"acceptance failed: {exc}", file=sys.stderr)
        return 1
    except subprocess.TimeoutExpired as exc:
        print(f"acceptance failed: command timed out: {exc.cmd}", file=sys.stderr)
        return 1
    print("V1 acceptance flow complete")
    return 0


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the V1 clean-machine acceptance flow."
    )
    parser.add_argument(
        "--memorable-cmd",
        default="memorable",
        help="Command used to invoke the Memorable CLI.",
    )
    parser.add_argument(
        "--mcp-cmd",
        default="memorable-mcp",
        help="Command used to start the Memorable MCP server over stdio.",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help="Existing clean workspace to use instead of a temporary directory.",
    )
    parser.add_argument(
        "--keep-workspace",
        action="store_true",
        help="Do not delete the temporary workspace after the run.",
    )
    return parser.parse_args(argv)


class _workspace:
    def __init__(self, path: Path | None, keep: bool) -> None:
        self._provided = path
        self._keep = keep
        self._temp_path: Path | None = None

    def __enter__(self) -> Path:
        if self._provided is not None:
            self._provided.mkdir(parents=True, exist_ok=True)
            return self._provided.resolve()

        import tempfile

        self._temp_path = Path(tempfile.mkdtemp(prefix="memorable-v1-")).resolve()
        return self._temp_path

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self._keep or self._temp_path is None:
            return
        import shutil

        shutil.rmtree(self._temp_path)


def _run_flow(args: argparse.Namespace, workspace: Path) -> None:
    space = f"v1-acceptance-{uuid.uuid4().hex[:10]}"
    env = os.environ.copy()

    print("progress: initializing clean MemorySpace")
    init_payload = _run_cli_json(
        args.memorable_cmd,
        [
            "init",
            "--path",
            str(workspace),
            "--space",
            space,
            "--description",
            "V1 clean-machine acceptance flow",
        ],
        cwd=workspace,
        env=env,
    )
    _assert_subset(
        init_payload,
        {"space": space, "status": "initialized", "profile_version": 1},
    )

    profile_path = workspace / ".memorable" / "memory.yaml"
    scaffold = profile_path.read_text(encoding="utf-8")
    _assert("write_policy" not in scaffold, "Minimal scaffold contains write_policy")
    _assert(
        "entities: []" in scaffold,
        "Minimal scaffold does not declare entities: []",
    )
    _assert(
        "relations: []" in scaffold,
        "Minimal scaffold does not declare relations: []",
    )
    _assert("records: []" in scaffold, "Minimal scaffold does not declare records: []")

    print("progress: running doctor after init")
    doctor_payload = _run_cli_json(
        args.memorable_cmd,
        ["doctor", "--json"],
        cwd=workspace,
        env=env,
    )
    _assert(isinstance(doctor_payload, list), "doctor output is not a JSON list")
    failed_checks = [result for result in doctor_payload if not result.get("ok")]
    _assert(not failed_checks, f"doctor checks failed: {failed_checks}")
    check_names = {result["check"] for result in doctor_payload}
    _assert(
        {
            "neo4j_connectivity",
            "schema_constraints",
            "vector_index",
            "memory_profile_parses",
            "embedding_provider_embeds",
        }
        <= check_names,
        f"doctor checks missing from {sorted(check_names)}",
    )

    print("progress: remembering kernel records without profile declarations")
    decision = _run_cli_json(
        args.memorable_cmd,
        [
            "remember",
            "decision",
            "--id",
            DECISION_ID,
            "--statement",
            DECISION_STATEMENT,
            "--source",
            SOURCE,
            "--at",
            "2026-05-30T10:00:00Z",
        ],
        cwd=workspace,
        env=env,
    )
    _assert_subset(
        decision,
        {
            "decision_id": DECISION_ID,
            "record_kind": "decision",
            "statement": DECISION_STATEMENT,
            "space": space,
            "lifecycle_state": "current",
        },
    )

    observation = _run_cli_json(
        args.memorable_cmd,
        [
            "remember",
            "observation",
            "--id",
            OBSERVATION_ID,
            "--statement",
            OBSERVATION_STATEMENT,
            "--source",
            SOURCE,
            "--at",
            "2026-05-30T10:01:00Z",
        ],
        cwd=workspace,
        env=env,
    )
    _assert_subset(
        observation,
        {
            "observation_id": OBSERVATION_ID,
            "record_kind": "observation",
            "statement": OBSERVATION_STATEMENT,
            "space": space,
            "lifecycle_state": "current",
        },
    )

    task = _run_cli_json(
        args.memorable_cmd,
        [
            "remember",
            "task",
            "--id",
            TASK_ID,
            "--title",
            TASK_TITLE,
            "--source",
            SOURCE,
            "--at",
            "2026-05-30T10:02:00Z",
        ],
        cwd=workspace,
        env=env,
    )
    _assert_subset(
        task,
        {
            "task_id": TASK_ID,
            "record_kind": "task",
            "title": TASK_TITLE,
            "space": space,
            "lifecycle_state": "open",
        },
    )

    print("progress: evolving MemoryProfile with an Entity type")
    _write_profile(profile_path, space, include_relation=False)
    evolved_profile = profile_path.read_text(encoding="utf-8")
    _assert("write_policy" not in evolved_profile, "evolved profile has write_policy")

    entity_a = _remember_entity(
        args.memorable_cmd,
        workspace=workspace,
        env=env,
        entity_id=ENTITY_A_ID,
        name=ENTITY_A_NAME,
        at="2026-05-30T10:03:00Z",
    )
    _assert_subset(
        entity_a,
        {
            "entity_id": ENTITY_A_ID,
            "entity_type": ENTITY_TYPE,
            "name": ENTITY_A_NAME,
            "record_kind": "entity",
            "space": space,
        },
    )

    entity_b = _remember_entity(
        args.memorable_cmd,
        workspace=workspace,
        env=env,
        entity_id=ENTITY_B_ID,
        name=ENTITY_B_NAME,
        at="2026-05-30T10:04:00Z",
    )
    _assert_subset(
        entity_b,
        {
            "entity_id": ENTITY_B_ID,
            "entity_type": ENTITY_TYPE,
            "name": ENTITY_B_NAME,
            "record_kind": "entity",
            "space": space,
        },
    )

    print("progress: evolving MemoryProfile with a Relation type")
    _write_profile(profile_path, space, include_relation=True)
    relation = _run_cli_json(
        args.memorable_cmd,
        [
            "remember",
            "relation",
            "--id",
            RELATION_ID,
            "--source-entity-id",
            ENTITY_A_ID,
            "--target-entity-id",
            ENTITY_B_ID,
            "--relation-type",
            RELATION_TYPE,
            "--statement",
            RELATION_STATEMENT,
            "--source",
            SOURCE,
            "--at",
            "2026-05-30T10:05:00Z",
        ],
        cwd=workspace,
        env=env,
    )
    _assert_subset(
        relation,
        {
            "relation_id": RELATION_ID,
            "record_kind": "relation",
            "relation_type": RELATION_TYPE,
            "statement": RELATION_STATEMENT,
            "space": space,
            "lifecycle_state": "current",
        },
    )

    print("progress: searching remembered memory through CLI")
    search = _run_cli_json(
        args.memorable_cmd,
        ["search", "--query", "Aurora Ridge Basalt Falls acceptance storage"],
        cwd=workspace,
        env=env,
        timeout=300,
    )
    _assert_subset(
        search,
        {"query": "Aurora Ridge Basalt Falls acceptance storage", "space": space},
    )
    result_ids = {result["source_id"] for result in search.get("results", [])}
    _assert(DECISION_ID in result_ids, f"search missing {DECISION_ID}: {result_ids}")
    _assert(ENTITY_A_ID in result_ids, f"search missing {ENTITY_A_ID}: {result_ids}")
    _assert(ENTITY_B_ID in result_ids, f"search missing {ENTITY_B_ID}: {result_ids}")
    _assert(RELATION_ID in result_ids, f"search missing {RELATION_ID}: {result_ids}")

    print("progress: listing MemoryRecords through MCP")
    records_payload = asyncio.run(
        _call_mcp_tool(
            args.mcp_cmd,
            "memorable_list_records",
            {"space": space, "limit": 10},
            cwd=workspace,
            env=env,
        )
    )
    _assert_subset(records_payload, {"space": space})
    records = records_payload.get("records")
    _assert(isinstance(records, list), "list_records did not return records list")
    by_id = {record["id"]: record for record in records}
    _assert_record(
        by_id,
        DECISION_ID,
        type="decision",
        label=DECISION_STATEMENT,
        lifecycle_state="current",
    )
    _assert_record(
        by_id,
        OBSERVATION_ID,
        type="observation",
        label=OBSERVATION_STATEMENT,
        lifecycle_state="current",
    )
    _assert_record(
        by_id,
        TASK_ID,
        type="task",
        label=TASK_TITLE,
        lifecycle_state="open",
    )
    _assert_record(
        by_id,
        RELATION_ID,
        type="relation",
        label=RELATION_STATEMENT,
        lifecycle_state="current",
    )
    _assert(ENTITY_A_ID not in by_id, "list_records must exclude Entities")
    _assert(ENTITY_B_ID not in by_id, "list_records must exclude Entities")


def _run_cli_json(
    command: str,
    args: Sequence[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: int = 120,
) -> Any:
    completed = _run_command(command, args, cwd=cwd, env=env, timeout=timeout)
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise AcceptanceFailure(
            f"command did not emit JSON: {_display_command(command, args)}\n"
            f"stdout: {completed.stdout}\nstderr: {completed.stderr}"
        ) from exc


def _run_command(
    command: str,
    args: Sequence[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    argv = [*shlex.split(command), *args]
    completed = subprocess.run(
        argv,
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if completed.returncode != 0:
        display_command = _display_command(command, args)
        raise AcceptanceFailure(
            f"command failed ({completed.returncode}): {display_command}\n"
            f"stdout: {completed.stdout}\nstderr: {completed.stderr}"
        )
    return completed


async def _call_mcp_tool(
    command: str,
    tool_name: str,
    arguments: dict[str, object],
    *,
    cwd: Path,
    env: dict[str, str],
) -> dict[str, object]:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    command_parts = shlex.split(command)
    server_params = StdioServerParameters(
        command=command_parts[0],
        args=command_parts[1:],
        cwd=str(cwd),
        env=env,
    )

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments)

    if result.isError:
        raise AcceptanceFailure(f"MCP tool {tool_name} returned an error: {result}")

    if result.structuredContent is not None:
        payload = result.structuredContent
    else:
        _assert(result.content, f"MCP tool {tool_name} returned no content")
        payload = json.loads(result.content[0].text)
    _assert(isinstance(payload, dict), f"MCP tool {tool_name} returned non-object")
    if "error" in payload:
        raise AcceptanceFailure(f"MCP tool {tool_name} returned error: {payload}")
    return payload


def _remember_entity(
    command: str,
    *,
    workspace: Path,
    env: dict[str, str],
    entity_id: str,
    name: str,
    at: str,
) -> dict[str, object]:
    payload = _run_cli_json(
        command,
        [
            "remember",
            "entity",
            "--id",
            entity_id,
            "--type",
            ENTITY_TYPE,
            "--name",
            name,
            "--source",
            SOURCE,
            "--at",
            at,
        ],
        cwd=workspace,
        env=env,
    )
    _assert(isinstance(payload, dict), "remember entity output is not an object")
    return payload


def _write_profile(profile_path: Path, space: str, *, include_relation: bool) -> None:
    relation_yaml = "\n".join(_relation_lines(include_relation))
    profile_path.write_text(
        f"""version: 1

space:
  name: "{space}"
  description: "V1 clean-machine acceptance flow"

entities:
  - name: Trail

relations: {relation_yaml}

records: []
""",
        encoding="utf-8",
    )


def _relation_lines(include_relation: bool) -> Iterator[str]:
    if not include_relation:
        yield "[]"
        return
    yield ""
    yield "  - name: connects-to"


def _assert_record(
    by_id: dict[str, dict[str, object]],
    record_id: str,
    **expected: str,
) -> None:
    _assert(record_id in by_id, f"list_records missing {record_id}: {by_id}")
    _assert_subset(by_id[record_id], expected)


def _assert_subset(actual: object, expected: dict[str, object]) -> None:
    _assert(isinstance(actual, dict), f"expected JSON object, got {actual!r}")
    missing = {
        key: expected_value
        for key, expected_value in expected.items()
        if actual.get(key) != expected_value
    }
    _assert(not missing, f"payload {actual!r} did not match {missing!r}")


def _assert(condition: object, message: str) -> None:
    if not condition:
        raise AcceptanceFailure(message)


def _display_command(command: str, args: Sequence[str]) -> str:
    return " ".join(shlex.quote(part) for part in [*shlex.split(command), *args])


if __name__ == "__main__":
    raise SystemExit(main())
