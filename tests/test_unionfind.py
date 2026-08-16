"""Union-find behaviour, with an emphasis on order independence.

Scenario 8 requires shuffled input not to change canonical semantics. The
property has to hold in the structure itself - sorting output afterwards would
hide a real difference rather than prevent one.
"""

from __future__ import annotations

import random

from graphcanon.unionfind import UnionFind


def test_slots_are_stable_and_first_seen() -> None:
    uf = UnionFind()
    assert uf.slot("a") == 0
    assert uf.slot("b") == 1
    assert uf.slot("a") == 0
    assert len(uf) == 2


def test_union_is_symmetric_and_transitive() -> None:
    uf = UnionFind()
    a, b, c = uf.slot("a"), uf.slot("b"), uf.slot("c")
    uf.union(b, a)
    uf.union(c, b)
    assert uf.find(a) == uf.find(b) == uf.find(c)


def test_root_is_always_the_lowest_slot() -> None:
    uf = UnionFind()
    slots = [uf.slot(ch) for ch in "abcd"]
    uf.union(slots[3], slots[1])
    uf.union(slots[2], slots[0])
    uf.union(slots[3], slots[2])
    assert all(uf.find(s) == slots[0] for s in slots)


def test_components_are_independent_of_union_order() -> None:
    edges = [("a", "b"), ("c", "d"), ("b", "c"), ("e", "f")]
    rng = random.Random(20260816)
    signatures = set()
    for _ in range(25):
        shuffled = edges[:]
        rng.shuffle(shuffled)
        uf = UnionFind()
        keys = sorted({k for edge in shuffled for k in edge})
        rng.shuffle(keys)
        for key in keys:
            uf.slot(key)
        for left, right in shuffled:
            uf.union(uf.slot(left), uf.slot(right))

        grouped = {}
        for key in keys:
            grouped.setdefault(uf.root_key(uf.slot(key)), set()).add(key)
        signatures.add(frozenset(frozenset(v) for v in grouped.values()))

    assert len(signatures) == 1
    assert signatures.pop() == frozenset(
        {frozenset({"a", "b", "c", "d"}), frozenset({"e", "f"})}
    )


def test_components_maps_roots_to_ascending_members() -> None:
    uf = UnionFind()
    for ch in "abcde":
        uf.slot(ch)
    uf.union(uf.slot("a"), uf.slot("c"))
    uf.union(uf.slot("b"), uf.slot("e"))
    components = uf.components()
    assert sorted(len(v) for v in components.values()) == [1, 2, 2]
    for members in components.values():
        assert members == sorted(members)
