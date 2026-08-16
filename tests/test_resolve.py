"""Resolution policy.

The real dataset has one organization and one workspace, so the isolation cases
below are the only place those two boundaries are ever exercised.
"""

from __future__ import annotations

import pytest

from graphcanon import reasons
from graphcanon.config import Config
from graphcanon.loading import iter_occurrences, load_scopes
from graphcanon.naming import token_count
from graphcanon.resolve import (
    DECISION_MERGED,
    DECISION_NEW,
    DECISION_POSSIBLE_DUPLICATE,
    resolve,
    verify_invariants,
)


@pytest.fixture(scope="module")
def occurrences(mini_input):
    return list(iter_occurrences(mini_input, load_scopes(mini_input)))


@pytest.fixture(scope="module")
def resolution(occurrences):
    return resolve(occurrences, Config())


def canonical_of(resolution, candidate_id: str) -> str:
    return resolution.assignments[candidate_id].canonical_entity_id


# --- coverage ----------------------------------------------------------------


def test_every_occurrence_is_assigned_exactly_once(resolution, occurrences):
    assert set(resolution.assignments) == {o.candidate_entity_id for o in occurrences}


def test_members_partition_the_input(resolution, occurrences):
    members = [
        m
        for entity in resolution.entities.values()
        for m in entity.member_candidate_entity_ids
    ]
    assert len(members) == len(set(members)) == len(occurrences)
    assert set(members) == {o.candidate_entity_id for o in occurrences}


def test_no_canonical_entity_is_unreferenced(resolution):
    referenced = {a.canonical_entity_id for a in resolution.assignments.values()}
    assert referenced == set(resolution.entities)


def test_every_assignment_carries_a_reason(resolution):
    assert all(a.reason_codes for a in resolution.assignments.values())
    known = reasons.ENTITY_CODES
    for assignment in resolution.assignments.values():
        assert set(assignment.reason_codes) <= known


def test_the_mini_fixture_resolves_to_ten_entities(resolution):
    assert len(resolution.entities) == 10


# --- isolation ---------------------------------------------------------------


def test_organization_isolation(resolution):
    assert canonical_of(resolution, "cent_e001") != canonical_of(resolution, "cent_e003")


def test_workspace_isolation(resolution):
    assert canonical_of(resolution, "cent_e001") != canonical_of(resolution, "cent_e004")


def test_type_isolation(resolution):
    assert canonical_of(resolution, "cent_t001") != canonical_of(resolution, "cent_t002")


def test_declared_scope_matches_members(resolution, occurrences):
    by_id = {o.candidate_entity_id: o for o in occurrences}
    for entity in resolution.entities.values():
        for member in entity.member_candidate_entity_ids:
            assert by_id[member].org_id == entity.org_id
            assert by_id[member].workspace_id == entity.workspace_id
            assert by_id[member].entity_type == entity.entity_type


# --- the single-token Person rule --------------------------------------------


def test_single_token_person_merges_inside_one_document(resolution):
    assert canonical_of(resolution, "cent_p001") == canonical_of(resolution, "cent_p002")


def test_single_token_person_does_not_merge_across_documents(resolution):
    assert canonical_of(resolution, "cent_p001") != canonical_of(resolution, "cent_p003")


def test_multi_token_person_merges_across_documents(resolution):
    assert canonical_of(resolution, "cent_p004") == canonical_of(resolution, "cent_p005")


def test_a_given_name_is_not_absorbed_into_a_full_name(resolution):
    assert canonical_of(resolution, "cent_p001") != canonical_of(resolution, "cent_p004")


def test_high_entropy_non_person_names_merge_across_documents(resolution):
    assert canonical_of(resolution, "cent_e001") == canonical_of(resolution, "cent_e002")


def test_unresolved_persons_are_flagged_on_the_assignment(resolution):
    for candidate in ("cent_p001", "cent_p002", "cent_p003"):
        assignment = resolution.assignments[candidate]
        assert assignment.decision == DECISION_POSSIBLE_DUPLICATE
        assert reasons.ONE_TOKEN_PERSON_UNRESOLVED_CROSS_SOURCE in assignment.reason_codes


def test_decisions_reflect_what_happened(resolution):
    assert resolution.assignments["cent_p004"].decision == DECISION_MERGED
    assert resolution.assignments["cent_pl001"].decision == DECISION_NEW


def test_unresolved_groups_hold_exactly_the_open_population(resolution):
    groups = resolution.unresolved_person_groups
    assert len(groups) == 1
    (events,) = groups.values()
    assert events == {
        "event_alpha": ("cent_p001", "cent_p002"),
        "event_beta": ("cent_p003",),
    }


# --- alias evidence ----------------------------------------------------------


def test_alias_assertions_do_not_merge_by_default(resolution):
    assert canonical_of(resolution, "cent_a001") != canonical_of(resolution, "cent_e001")


def test_alias_assertions_are_recorded_as_open_questions(resolution):
    assert len(resolution.alias_links) == 1
    link = resolution.alias_links[0]
    assert "cent_a001" in link.asserting_candidate_entity_ids
    assert {link.left_canonical_entity_id, link.right_canonical_entity_id} == {
        canonical_of(resolution, "cent_a001"),
        canonical_of(resolution, "cent_e001"),
    }


def test_alias_merging_is_available_and_changes_the_result(occurrences):
    merged = resolve(occurrences, Config(merge_on_alias=True, alias_min_support=1))
    assert merged.assignments["cent_a001"].canonical_entity_id == (
        merged.assignments["cent_e001"].canonical_entity_id
    )
    assert reasons.SOURCE_LOCAL_ALIAS in merged.assignments["cent_a001"].reason_codes
    assert verify_invariants(merged, occurrences) == {}


def test_alias_support_threshold_is_honoured(occurrences):
    guarded = resolve(occurrences, Config(merge_on_alias=True, alias_min_support=2))
    assert guarded.assignments["cent_a001"].canonical_entity_id != (
        guarded.assignments["cent_e001"].canonical_entity_id
    )


# --- provenance and naming ---------------------------------------------------


def test_components_retain_every_contributing_reference(resolution):
    entity = resolution.entities[canonical_of(resolution, "cent_p001")]
    assert entity.member_candidate_entity_ids == ("cent_p001", "cent_p002")
    assert entity.source_event_ids == ("event_alpha",)
    assert entity.chunk_ids == ("chunk_a1", "chunk_a2")


def test_canonical_name_is_the_surface_form(resolution):
    entity = resolution.entities[canonical_of(resolution, "cent_e001")]
    assert entity.canonical_name == "Organization-CCCCCCCCCCCC"


def test_component_quality_is_populated(resolution):
    entity = resolution.entities[canonical_of(resolution, "cent_p001")]
    quality = entity.component_quality
    assert quality["member_count"] == 2
    assert quality["source_event_count"] == 1
    assert quality["source_scoped"] is True
    assert quality["unresolved_partner_components"] == 1
    assert quality["name_token_count"] == token_count("quill-aaaaaaaaaa")


# --- invariants --------------------------------------------------------------


def test_invariant_check_is_clean(resolution, occurrences):
    assert verify_invariants(resolution, occurrences) == {}


def test_invariant_check_catches_a_corrupted_component(resolution, occurrences):
    entities = dict(resolution.entities)
    victim = entities[canonical_of(resolution, "cent_e001")]
    entities[victim.canonical_entity_id] = victim._replace(
        member_candidate_entity_ids=victim.member_candidate_entity_ids + ("cent_e003",)
    )
    broken = resolution._replace(entities=entities)
    violations = verify_invariants(broken, occurrences)
    assert violations.get("cross_organization_components") == 1
    assert violations.get("cross_workspace_components") == 1
    assert violations.get("members_in_multiple_components") == 1


def test_global_person_scope_is_rejected_by_the_acceptance_rule(occurrences):
    loose = resolve(occurrences, Config(one_token_person_scope="global"))
    assert loose.assignments["cent_p001"].canonical_entity_id == (
        loose.assignments["cent_p003"].canonical_entity_id
    )
    violations = verify_invariants(loose, occurrences)
    assert violations.get("prohibited_one_token_person_components") == 1
