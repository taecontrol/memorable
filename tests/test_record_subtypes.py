from __future__ import annotations


def _profile_with_records():
    from memorable.core.profile import load_profile_from_yaml

    return load_profile_from_yaml(
        """\
version: 1
space:
  name: memorable
  description: test profile
records:
  - name: Episode
    extends: Observation
  - name: ArchitectureDecision
    extends: Decision
"""
    )


def test_declared_observation_subtype_is_validated() -> None:
    from memorable.core.record_subtypes import validate_record_subtype

    profile = _profile_with_records()

    assert (
        validate_record_subtype(
            profile=profile,
            kernel_kind="observation",
            candidate="Episode",
        )
        == "Episode"
    )


def test_omitted_record_subtype_is_plain_kernel_record() -> None:
    from memorable.core.record_subtypes import validate_record_subtype

    profile = _profile_with_records()

    assert (
        validate_record_subtype(
            profile=profile,
            kernel_kind="observation",
            candidate=None,
        )
        is None
    )


def test_undeclared_record_subtype_names_declared_alternatives() -> None:
    import pytest

    from memorable.core.application import UndeclaredTypeError
    from memorable.core.record_subtypes import validate_record_subtype

    profile = _profile_with_records()

    with pytest.raises(UndeclaredTypeError) as error:
        validate_record_subtype(
            profile=profile,
            kernel_kind="observation",
            candidate="Pattern",
        )

    message = str(error.value)
    assert "Record Subtype 'Pattern' is not declared" in message
    assert "MemoryProfile" in message
    assert "Episode" in message


def test_record_subtype_extends_must_match_kernel_kind() -> None:
    import pytest

    from memorable.core.application import UndeclaredTypeError
    from memorable.core.record_subtypes import validate_record_subtype

    profile = _profile_with_records()

    with pytest.raises(UndeclaredTypeError) as error:
        validate_record_subtype(
            profile=profile,
            kernel_kind="observation",
            candidate="ArchitectureDecision",
        )

    message = str(error.value)
    assert (
        "Record Subtype 'ArchitectureDecision' extends Decision, not Observation"
        in message
    )
    assert "Declared Observation Record Subtypes" in message
    assert "Episode" in message
