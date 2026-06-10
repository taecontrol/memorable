from __future__ import annotations

from datetime import UTC, datetime

import pytest

from memorable.cli import main
from memorable.config import (
    EmbeddingSettings,
    RuntimeConfig,
    SQLiteSettings,
    StorageSettings,
)
from memorable.core.models import Provenance, Relation
from memorable.retrieval.models import EmbeddingRecord
from memorable.storage.production import build_production_context


class WrongDimensionEmbeddingProvider:
    provider_name = "test-provider"
    model_name = "test-model"

    def embed(self, text: str) -> list[float]:
        return [1.0, 0.0]


def _embedding_record(*, source_id: str, source_kind: str) -> EmbeddingRecord:
    now = datetime(2026, 6, 8, 12, 0, tzinfo=UTC)
    return EmbeddingRecord(
        source_id=source_id,
        source_kind=source_kind,
        space="test-space",
        indexable_text="orphan candidate",
        vector=[1.0, 0.0, 0.0],
        provider_name="test-provider",
        model_name="test-model",
        dimensions=3,
        indexable_text_hash="hash:orphan",
        indexable_text_version="test-version",
        created_at=now,
        updated_at=now,
    )


def _provenance(*, record_id: str, record_kind: str) -> Provenance:
    at = datetime(2026, 6, 8, 12, 0, tzinfo=UTC)
    return Provenance(
        record_id=record_id,
        record_kind=record_kind,
        source_id="source:test",
        episode_id="episode:test",
        writer="agent:memorable",
        reason="test canonical failure rollback",
        creation_time=at,
        validity_time=at,
    )


def test_sqlite_atomic_write_rolls_back_embedding_when_canonical_write_fails(
    tmp_path,
) -> None:
    config = RuntimeConfig(
        storage=StorageSettings(backend="sqlite"),
        sqlite=SQLiteSettings(path=str(tmp_path / "memory.db")),
    )
    ctx, resource = build_production_context(config)
    try:
        relation = Relation(
            id="relation:missing-endpoints",
            source_entity_id="entity:missing-source",
            target_entity_id="entity:missing-target",
            relation_type="depends-on",
            statement="Missing source depends on missing target",
            space="test-space",
            validity_time=datetime(2026, 6, 8, 12, 0, tzinfo=UTC),
            invalidation_time=None,
            lifecycle_state="current",
            supersedes=None,
            superseded_by=None,
        )

        with pytest.raises(ValueError):
            with ctx.atomic_write():
                ctx.retrieval_index.store(
                    _embedding_record(
                        source_id=relation.id,
                        source_kind="Relation",
                    )
                )
                ctx.relation_repo.save(
                    relation,
                    _provenance(record_id=relation.id, record_kind="relation"),
                )

        assert ctx.retrieval_index.records(space="test-space") == []
    finally:
        resource.close()


def test_sqlite_cli_rolls_back_record_when_embedding_store_fails(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    from unittest.mock import patch

    monkeypatch.chdir(tmp_path)
    config = RuntimeConfig(
        storage=StorageSettings(backend="sqlite"),
        sqlite=SQLiteSettings(path=str(tmp_path / "memory.db")),
        embeddings=EmbeddingSettings(provider="fake", dimensions=3),
        base_path=tmp_path,
    )

    with (
        patch("memorable.cli.load_runtime_config", return_value=config),
        patch(
            "memorable.retrieval.embeddings.build_embedding_provider",
            return_value=WrongDimensionEmbeddingProvider(),
        ),
    ):
        assert (
            main(
                [
                    "remember",
                    "decision",
                    "--space",
                    "test-space",
                    "--id",
                    "decision:rollback-on-index-failure",
                    "--statement",
                    "SQLite rolls back record when Embedding store fails",
                    "--source",
                    "source:test",
                    "--at",
                    "2026-06-08T12:00:00Z",
                ]
            )
            == 1
        )
        remember_output = capsys.readouterr()

        assert (
            main(
                [
                    "truth",
                    "current",
                    "--space",
                    "test-space",
                    "--id",
                    "decision:rollback-on-index-failure",
                ]
            )
            == 1
        )
        truth_output = capsys.readouterr()

    assert "Canonical memory was rolled back" in remember_output.err
    assert "Embedding vector length" in remember_output.err
    assert "No Decision found" in truth_output.err


def test_sqlite_mcp_rolls_back_record_when_embedding_store_fails(
    tmp_path,
    monkeypatch,
) -> None:
    from unittest.mock import patch

    from memorable.core.context import default_context
    from memorable.mcp.server import (
        current_truth_tool,
        remember_decision_tool,
        set_mcp_context,
    )

    monkeypatch.chdir(tmp_path)
    config = RuntimeConfig(
        storage=StorageSettings(backend="sqlite"),
        sqlite=SQLiteSettings(path=str(tmp_path / "memory.db")),
        embeddings=EmbeddingSettings(provider="fake", dimensions=3),
        base_path=tmp_path,
    )
    ctx, resource = build_production_context(config)
    set_mcp_context(ctx)

    try:
        with (
            patch("memorable.mcp.server.load_runtime_config", return_value=config),
            patch(
                "memorable.retrieval.embeddings.build_embedding_provider",
                return_value=WrongDimensionEmbeddingProvider(),
            ),
        ):
            result = remember_decision_tool(
                space="test-space",
                decision_id="decision:mcp-rollback-on-index-failure",
                statement="SQLite MCP rolls back record on Embedding store failure",
                source="source:test",
                at="2026-06-08T12:00:00Z",
            )

        current = current_truth_tool(
            space="test-space",
            record_id="decision:mcp-rollback-on-index-failure",
        )

        assert result["canonical_memory_written"] is False
        assert result["canonical_memory_rolled_back"] is True
        assert "Canonical memory was rolled back" in str(result["error"])
        assert "Embedding vector length" in str(result["error"])
        assert "error" in current
        assert "No Decision found" in str(current["error"])
    finally:
        set_mcp_context(default_context)
        resource.close()
