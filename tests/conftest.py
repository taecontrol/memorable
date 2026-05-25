"""Shared fixtures for Memorable tests."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from memorable.config import RuntimeConfig
from memorable.core.context import ApplicationContext


@pytest.fixture()
def cli_in_memory_context():
    """Patch CLI production wiring to use an in-memory ApplicationContext.

    CLI memory commands now build a production context (Neo4j-backed) at
    runtime. Tests that exercise CLI behavior without a real database
    should use this fixture to get an in-memory context instead.

    The fixture patches build_production_context and load_runtime_config
    in the cli module, and returns the shared ApplicationContext so tests
    can inspect persisted state if needed.

    Usage::

        def test_something(self, cli_in_memory_context, capsys):
            ctx = cli_in_memory_context
            main(["remember", "entity", "--space", "test", ...])
            # entity is stored in ctx.entity_repo
    """
    ctx = ApplicationContext()
    mock_driver = MagicMock()
    mock_driver.verify_connectivity.return_value = None

    with (
        patch("memorable.cli.build_production_context") as mock_build,
        patch("memorable.cli.load_runtime_config", return_value=RuntimeConfig()),
    ):
        mock_build.return_value = (ctx, mock_driver)
        yield ctx
