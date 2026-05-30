"""Tests for Minimal MemoryProfile scaffold generation."""

from __future__ import annotations


def test_minimal_profile_scaffold_loads_as_empty_profile() -> None:
    """Generated scaffold YAML parses as a valid Minimal MemoryProfile."""
    from memorable.core.profile import load_profile_from_yaml
    from memorable.core.profile_scaffold import render_minimal_profile_scaffold

    yaml_text = render_minimal_profile_scaffold(
        "memorable", description="Agent memory system design", version=1
    )

    profile = load_profile_from_yaml(yaml_text)

    assert profile.version == 1
    assert profile.space.name == "memorable"
    assert profile.space.description == "Agent memory system design"
    assert profile.entities == ()
    assert profile.relations == ()
    assert profile.records == ()


def test_minimal_profile_scaffold_contains_guidance_without_write_policy() -> None:
    """Scaffold text gives commented examples without shipping dead policy config."""
    from memorable.core.profile import load_profile_from_yaml
    from memorable.core.profile_scaffold import render_minimal_profile_scaffold

    yaml_text = render_minimal_profile_scaffold("training-log", version=1)
    profile = load_profile_from_yaml(yaml_text)

    assert "version: 1" in yaml_text
    assert "space:" in yaml_text
    assert 'name: "training-log"' in yaml_text
    assert 'description: ""' in yaml_text
    assert profile.space.description == ""
    assert "entities: []" in yaml_text
    assert "relations: []" in yaml_text
    assert "records: []" in yaml_text
    assert "#   - name: Person" in yaml_text
    assert "#   - name: supports" in yaml_text
    assert "#   - name: ProjectDecision" in yaml_text
    assert "#     extends: Decision" in yaml_text
    assert "write_policy" not in yaml_text
