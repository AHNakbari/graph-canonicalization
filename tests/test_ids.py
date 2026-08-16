"""Content-addressed identifiers."""

from __future__ import annotations

from graphcanon.ids import canonical_edge_id, canonical_entity_id


def test_entity_id_is_a_pure_function_of_its_identity() -> None:
    first = canonical_entity_id("org_a", "ws_a", "Person", "quill-aaaa")
    second = canonical_entity_id("org_a", "ws_a", "Person", "quill-aaaa")
    assert first == second
    assert first.startswith("canon_")


def test_scope_and_type_are_part_of_identity() -> None:
    base = canonical_entity_id("org_a", "ws_a", "LegalEntity", "organization-cccc")
    assert base != canonical_entity_id("org_b", "ws_a", "LegalEntity", "organization-cccc")
    assert base != canonical_entity_id("org_a", "ws_b", "LegalEntity", "organization-cccc")
    assert base != canonical_entity_id("org_a", "ws_a", "Topic", "organization-cccc")


def test_field_boundaries_cannot_be_forged() -> None:
    # Without a separator, ("ab","c") and ("a","bc") would hash alike and two
    # different entities could collide into one canonical ID.
    assert canonical_entity_id("org", "ws", "ab", "c") != canonical_entity_id(
        "org", "ws", "a", "bc"
    )


def test_edge_id_keys_on_subject_predicate_object() -> None:
    edge = canonical_edge_id("canon_a", "WorksAt", "canon_b")
    assert edge == canonical_edge_id("canon_a", "WorksAt", "canon_b")
    assert edge.startswith("cedge_")
    assert edge != canonical_edge_id("canon_b", "WorksAt", "canon_a")  # direction matters
    assert edge != canonical_edge_id("canon_a", "LivesIn", "canon_b")


def test_edge_id_distinguishes_literal_objects() -> None:
    assert canonical_edge_id("canon_a", "HasValue", None, "amount-usd-10.00") != (
        canonical_edge_id("canon_a", "HasValue", None, "amount-usd-20.00")
    )


def test_ids_are_hex_and_fixed_width() -> None:
    entity = canonical_entity_id("org", "ws", "Person", "n")
    edge = canonical_edge_id("canon_a", "P", "canon_b")
    assert len(entity) == len("canon_") + 20
    assert len(edge) == len("cedge_") + 20
    assert set(entity.removeprefix("canon_")) <= set("0123456789abcdef")
