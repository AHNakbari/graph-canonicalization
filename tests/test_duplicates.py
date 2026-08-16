"""Unresolved-pair enumeration."""

from __future__ import annotations

import json

import pytest

from graphcanon import reasons
from graphcanon.config import Config
from graphcanon.duplicates import DuplicateEnumerator
from graphcanon.loading import iter_occurrences, load_scopes
from graphcanon.resolve import resolve


@pytest.fixture(scope="module")
def resolution(mini_input):
    scopes = load_scopes(mini_input)
    return resolve(list(iter_occurrences(mini_input, scopes)), Config())


def rows_for(resolution, config):
    enumerator = DuplicateEnumerator(resolution, config)
    rows = [json.loads(line) for line in enumerator.lines()]
    return rows, enumerator


def test_every_cross_document_pair_is_emitted(resolution):
    rows, enumerator = rows_for(resolution, Config())
    pairwise = [r for r in rows if reasons.ONE_TOKEN_PERSON_CROSS_SOURCE in r["reason_codes"]]
    evidence = {tuple(r["evidence_candidate_entity_ids"]) for r in pairwise}
    assert evidence == {("cent_p001", "cent_p003"), ("cent_p002", "cent_p003")}
    assert enumerator.stats["unresolved_pairs_total"] == 2
    assert enumerator.stats["unresolved_pair_coverage"] == 1.0


def test_pairwise_rows_carry_exactly_two_evidence_ids(resolution):
    """The supplied scorer only reads rows with exactly two - see FINDINGS §6."""
    rows, _ = rows_for(resolution, Config())
    for row in rows:
        if reasons.GROUP_LEVEL_AMBIGUITY in row["reason_codes"]:
            continue
        assert len(set(row["evidence_candidate_entity_ids"])) == 2


def test_rows_are_valid_against_the_schema_shape(resolution):
    rows, _ = rows_for(resolution, Config())
    for row in rows:
        assert row["left_canonical_entity_id"] != row["right_canonical_entity_id"]
        assert 0.0 <= row["confidence"] <= 1.0
        assert row["reason_codes"]
        assert len(set(row["evidence_candidate_entity_ids"])) >= 2


def test_confidence_decays_with_how_common_the_name_is(resolution):
    rows, _ = rows_for(resolution, Config())
    pairwise = [r for r in rows if reasons.ONE_TOKEN_PERSON_CROSS_SOURCE in r["reason_codes"]]
    assert all(r["confidence"] == 0.5 for r in pairwise)


def test_alias_questions_are_recorded_at_group_level(resolution):
    rows, _ = rows_for(resolution, Config())
    alias_rows = [
        r for r in rows if reasons.ALIAS_ASSERTED_UNCORROBORATED in r["reason_codes"]
    ]
    assert len(alias_rows) == 1
    row = alias_rows[0]
    assert "cent_a001" in row["evidence_candidate_entity_ids"]
    assert reasons.GROUP_LEVEL_AMBIGUITY in row["reason_codes"]


def test_a_budget_truncates_and_says_so(resolution):
    rows, enumerator = rows_for(resolution, Config(possible_duplicate_pair_budget=1))
    pairwise = [
        r
        for r in rows
        if reasons.ONE_TOKEN_PERSON_CROSS_SOURCE in r["reason_codes"]
        and reasons.GROUP_LEVEL_AMBIGUITY not in r["reason_codes"]
    ]
    assert pairwise == []  # the group needs 2 rows and the budget allows 1
    assert enumerator.stats["truncated_groups"] == 1
    assert enumerator.stats["unresolved_pair_coverage"] < 1.0


def test_a_truncated_group_still_states_its_open_question(resolution):
    rows, _ = rows_for(resolution, Config(possible_duplicate_pair_budget=1))
    group_rows = [
        r
        for r in rows
        if reasons.ONE_TOKEN_PERSON_CROSS_SOURCE in r["reason_codes"]
        and reasons.GROUP_LEVEL_AMBIGUITY in r["reason_codes"]
    ]
    assert len(group_rows) == 1
    assert len(group_rows[0]["evidence_candidate_entity_ids"]) >= 2


def test_emission_order_is_stable(resolution):
    first, _ = rows_for(resolution, Config())
    second, _ = rows_for(resolution, Config())
    assert first == second


def test_watched_pairs_are_reported_from_what_was_actually_emitted(resolution):
    enumerator = DuplicateEnumerator(resolution, Config())
    enumerator.watch = {("cent_p001", "cent_p003"), ("cent_p001", "cent_never")}
    list(enumerator.lines())
    # Only the pair that really reached the file counts as answered.
    assert ("cent_p001", "cent_p003") in enumerator.emitted_watch_pairs()
    assert ("cent_p001", "cent_never") not in enumerator.emitted_watch_pairs()


def test_stats_are_only_final_after_consumption(resolution):
    enumerator = DuplicateEnumerator(resolution, Config())
    assert enumerator.stats == {}
    list(enumerator.lines())
    assert enumerator.stats["pairwise_rows"] == 2
