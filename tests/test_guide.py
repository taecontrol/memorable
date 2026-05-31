from __future__ import annotations

from memorable.guide import render, topics

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


def test_authored_topic_renders_non_empty_content() -> None:
    assert render("overview").strip()
