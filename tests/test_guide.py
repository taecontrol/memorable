from __future__ import annotations

import asyncio
import re

import pytest

from memorable.guide import render, topics

REFERENCE_TOOL_PATTERN = re.compile(r"^- `(memorable_[a-z0-9_]+)`: ", re.MULTILINE)
WRITABLE_RECORD_TYPES_PATTERN = re.compile(
    r"^Writable Record Types: (?P<types>.+)\.$",
    re.MULTILINE,
)

EXPECTED_TOPIC_NAMES = (
    "overview",
    "writing",
    "retrieval",
    "temporal",
    "profiles",
    "recipes",
    "reference",
)


def test_index_lists_every_guide_topic_with_summary() -> None:
    rendered = render()
    summaries = topics()

    assert tuple(topic.name for topic in summaries) == EXPECTED_TOPIC_NAMES
    assert all(topic.summary for topic in summaries)
    for topic_name in EXPECTED_TOPIC_NAMES:
        assert f"- `{topic_name}`:" in rendered


@pytest.mark.parametrize(
    "topic_name",
    (
        "overview",
        "writing",
        "retrieval",
        "temporal",
        "profiles",
        "recipes",
        "reference",
    ),
)
def test_authored_topic_renders_non_empty_content(topic_name: str) -> None:
    rendered = render(topic_name)

    assert rendered.strip()
    assert "This guide topic is not authored yet." not in rendered


def test_reference_topic_names_every_registered_tool() -> None:
    from memorable.mcp.server import mcp_server

    live_tool_names = {tool.name for tool in asyncio.run(mcp_server.list_tools())}
    documented_tool_names = set(REFERENCE_TOOL_PATTERN.findall(render("reference")))

    assert documented_tool_names == live_tool_names


def test_guide_documents_current_writable_record_types() -> None:
    match = WRITABLE_RECORD_TYPES_PATTERN.search(render("reference"))
    assert match is not None

    documented_types = tuple(
        record_type.strip() for record_type in match.group("types").split(",")
    )
    assert documented_types == ("Decision", "Observation", "Task")
