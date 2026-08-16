"""Name-shape rules.

Checked against tools/validate_submission.py's own regex, never a restatement
of it: if our token count drifts from theirs we either lose merges we were
entitled to or emit components their validator rejects outright.
"""

from __future__ import annotations

import pytest

from graphcanon.naming import (
    is_one_token_person,
    is_person,
    normalized_name,
    token_count,
    tokens,
)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("quill-fa1308d761", 1),  # an internal hyphen does not split a token
        ("quill-fa1308d761 orin-9ac6abe97a", 2),
        ("organization-9593a10ac8d8", 1),
        ("date-2030-02-16", 1),
        ("amount-usd-1200.00", 2),  # the '.' does split
        ("o'brien-aabbccddee", 1),  # an apostrophe does not
        ("", 0),
        ("   ", 0),
    ],
)
def test_token_count(name: str, expected: int) -> None:
    assert token_count(name) == expected


def test_token_count_matches_the_acceptance_validator(validate_submission_tool) -> None:
    """Our tokenizer must agree with tools/validate_submission.py exactly."""
    samples = [
        "quill-fa1308d761",
        "quill-fa1308d761 orin-9ac6abe97a",
        "organization-9593a10ac8d8",
        "date-2030-02-16",
        "amount-usd-1200.00",
        "o'brien-aabbccddee",
        "person-aabbccddeeff",
        "a b c d e",
        "",
    ]
    for sample in samples:
        assert tokens(sample) == validate_submission_tool.TOKEN_RE.findall(sample), sample


@pytest.mark.parametrize("entity_type", ["Person", "person", "PERSON"])
def test_person_check_is_case_insensitive(entity_type: str) -> None:
    # The validator compares with casefold(); a case-sensitive check here would
    # let a prohibited component through.
    assert is_person(entity_type)


def test_one_token_person_is_the_only_restricted_shape() -> None:
    assert is_one_token_person("Person", "quill-fa1308d761")
    assert not is_one_token_person("Person", "quill-fa1308d761 orin-9ac6abe97a")
    assert not is_one_token_person("LegalEntity", "organization-9593a10ac8d8")
    assert not is_one_token_person("Place", "riverbend-5d55861dfa")


def test_normalized_name_falls_back_to_name() -> None:
    assert normalized_name({"normalized_name": "a", "name": "B"}) == "a"
    assert normalized_name({"name": "B"}) == "B"  # same fallback the validator uses
    assert normalized_name({"normalized_name": "", "name": "B"}) == "B"
    assert normalized_name({}) == ""
