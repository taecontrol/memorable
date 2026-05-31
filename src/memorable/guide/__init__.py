from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files
from typing import Literal, cast, get_args

# The guide is delivered as a tool because MCP clients reliably discover tools,
# while resources and prompts are client- or user-driven and weaker for self-help.

GuideTopicName = Literal[
    "overview",
    "writing",
    "retrieval",
    "temporal",
    "profiles",
    "recipes",
    "reference",
]


@dataclass(frozen=True, slots=True)
class GuideTopic:
    name: GuideTopicName
    summary: str


_TOPICS = (
    GuideTopic("overview", "What Memorable is, when to use it, and non-goals."),
    GuideTopic("writing", "How to choose record types and connect memory."),
    GuideTopic("retrieval", "How to choose search, review, and truth tools."),
    GuideTopic("temporal", "How memory changes without erasing history."),
    GuideTopic("profiles", "How MemoryProfiles declare valid project types."),
    GuideTopic("recipes", "Short workflows that chain tools for common goals."),
    GuideTopic("reference", "Terse list of every Memorable MCP tool."),
)
_TOPIC_NAMES = frozenset(get_args(GuideTopicName))


def topics() -> tuple[GuideTopic, ...]:
    return _TOPICS


def render(topic: GuideTopicName | None = None) -> str:
    if topic is None:
        return _render_index()

    if topic not in _TOPIC_NAMES:
        raise ValueError(f"Unknown guide topic '{topic}'.")

    return _read_topic_markdown(cast(GuideTopicName, topic))


def _render_index() -> str:
    lines = ["# Memorable Guide", ""]
    lines.extend(f"- `{topic.name}`: {topic.summary}" for topic in _TOPICS)
    return "\n".join(lines) + "\n"


def _read_topic_markdown(topic: GuideTopicName) -> str:
    resource = files("memorable.guide").joinpath("topics", f"{topic}.md")
    return resource.read_text(encoding="utf-8").strip() + "\n"
