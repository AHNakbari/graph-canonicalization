"""Fact projection and edge consolidation."""

from __future__ import annotations

import pytest

from graphcanon import reasons
from graphcanon.config import Config
from graphcanon.loading import iter_facts, iter_occurrences, load_scopes
from graphcanon.projection import (
    DISPOSITION_DROPPED,
    DISPOSITION_PROJECTED,
    project,
    verify_invariants,
)
from graphcanon.resolve import resolve


@pytest.fixture(scope="module")
def parts(mini_input):
    scopes = load_scopes(mini_input)
    occurrences = list(iter_occurrences(mini_input, scopes))
    facts = list(iter_facts(mini_input))
    resolution = resolve(occurrences, Config())
    return resolution, project(facts, resolution, Config())


def test_every_fact_gets_exactly_one_disposition(parts, mini_input):
    _resolution, projection = parts
    facts = {f.candidate_fact_id for f in iter_facts(mini_input)}
    assert set(projection.assignments) == facts
    assert len(projection.assignments) == 6


def test_facts_sharing_a_triple_consolidate(parts):
    _resolution, projection = parts
    first = projection.assignments["cfact_f001"]
    second = projection.assignments["cfact_f002"]
    assert first.disposition == DISPOSITION_PROJECTED
    assert first.canonical_edge_id == second.canonical_edge_id


def test_consolidation_keeps_every_contributing_reference(parts):
    _resolution, projection = parts
    edge = projection.edges[projection.assignments["cfact_f001"].canonical_edge_id]
    # Both facts, and crucially both chunks - the second fact's chunk is the
    # one a careless consolidation drops.
    assert edge.source_candidate_fact_ids == ("cfact_f001", "cfact_f002")
    assert edge.chunk_ids == ("chunk_a1", "chunk_a2")
    assert edge.source_event_ids == ("event_alpha",)
    assert edge.contributing_fact_count == 2
    assert edge.confidence == 0.9  # max across contributors
    assert edge.confidence_mean == 0.85


def test_a_different_subject_stays_a_different_edge(parts):
    _resolution, projection = parts
    assert (
        projection.assignments["cfact_f003"].canonical_edge_id
        != projection.assignments["cfact_f001"].canonical_edge_id
    )


def test_self_loops_are_rejected_with_a_reason(parts):
    _resolution, projection = parts
    dropped = projection.assignments["cfact_f004"]
    assert dropped.disposition == DISPOSITION_DROPPED
    assert dropped.canonical_edge_id is None
    assert dropped.reason_codes == (reasons.SELF_LOOP_AFTER_CANONICALIZATION,)


def test_cross_scope_endpoints_are_rejected_rather_than_the_boundary(parts):
    _resolution, projection = parts
    dropped = projection.assignments["cfact_f006"]
    assert dropped.disposition == DISPOSITION_DROPPED
    assert dropped.reason_codes == (reasons.CROSS_SCOPE_ENDPOINTS,)


def test_no_dangling_edge_survives_a_rejection(parts):
    resolution, projection = parts
    for edge in projection.edges.values():
        assert edge.subject_canonical_entity_id in resolution.entities
        assert (
            edge.object_canonical_entity_id is None
            or edge.object_canonical_entity_id in resolution.entities
        )
    assert len(projection.edges) == 3


def test_every_rejection_carries_a_valid_reason(parts):
    _resolution, projection = parts
    for assignment in projection.assignments.values():
        assert assignment.reason_codes
        if assignment.disposition == DISPOSITION_DROPPED:
            assert set(assignment.reason_codes) & reasons.VALID_REJECTION_CODES


def test_rejected_facts_are_counted_by_reason(parts):
    _resolution, projection = parts
    assert projection.rejected_by_reason == {
        reasons.CROSS_SCOPE_ENDPOINTS: 1,
        reasons.SELF_LOOP_AFTER_CANONICALIZATION: 1,
    }


def test_invariants_are_clean(parts):
    resolution, projection = parts
    assert verify_invariants(projection, resolution) == {}


def test_an_unresolved_endpoint_is_rejected_not_invented(parts, mini_input):
    resolution, _projection = parts
    facts = list(iter_facts(mini_input))
    orphan = facts[0]._replace(
        candidate_fact_id="cfact_orphan", subject_candidate_id="cent_never_extracted"
    )
    projection = project(facts + [orphan], resolution, Config())
    assignment = projection.assignments["cfact_orphan"]
    assert assignment.disposition == DISPOSITION_DROPPED
    assert assignment.reason_codes == (reasons.UNRESOLVED_SUBJECT,)
    assert verify_invariants(projection, resolution) == {}


def test_a_missing_predicate_is_rejected(parts, mini_input):
    resolution, _projection = parts
    facts = list(iter_facts(mini_input))
    blank = facts[0]._replace(candidate_fact_id="cfact_blank", predicate="")
    projection = project(facts + [blank], resolution, Config())
    assert projection.assignments["cfact_blank"].reason_codes == (
        reasons.MISSING_PREDICATE,
    )


def test_a_literal_object_becomes_a_valued_edge(parts, mini_input):
    resolution, _projection = parts
    facts = list(iter_facts(mini_input))
    literal = facts[0]._replace(
        candidate_fact_id="cfact_literal",
        object_candidate_id=None,
        object_value="Amount-USD-1200.00",
        predicate="HasValue",
    )
    projection = project(facts + [literal], resolution, Config())
    assignment = projection.assignments["cfact_literal"]
    assert assignment.disposition == DISPOSITION_PROJECTED
    edge = projection.edges[assignment.canonical_edge_id]
    assert edge.object_canonical_entity_id is None
    # The schema requires an endpoint or a value; the row must carry the value.
    assert edge.as_row()["object_value"] == "Amount-USD-1200.00"
    assert verify_invariants(projection, resolution) == {}


def test_keeping_self_loops_is_possible_and_visible(parts, mini_input):
    resolution, _projection = parts
    facts = list(iter_facts(mini_input))
    kept = project(facts, resolution, Config(drop_self_loops=False))
    assert kept.assignments["cfact_f004"].disposition == DISPOSITION_PROJECTED
    assert verify_invariants(kept, resolution).get("self_loop_edges") == 1
