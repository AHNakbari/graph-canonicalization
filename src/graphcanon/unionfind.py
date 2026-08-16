"""Disjoint-set union over blocking keys."""

from __future__ import annotations

from typing import Hashable, Iterator


class UnionFind:
    __slots__ = ("_slot", "_parent", "_keys")

    def __init__(self) -> None:
        self._slot: dict[Hashable, int] = {}
        self._parent: list[int] = []
        self._keys: list[Hashable] = []

    def __len__(self) -> int:
        return len(self._parent)

    def slot(self, key: Hashable) -> int:
        index = self._slot.get(key)
        if index is None:
            index = len(self._parent)
            self._slot[key] = index
            self._parent.append(index)
            self._keys.append(key)
        return index

    def find(self, index: int) -> int:
        parent = self._parent
        root = index
        while parent[root] != root:
            root = parent[root]
        while parent[index] != root:  # path compression
            parent[index], index = root, parent[index]
        return root

    def union(self, left: int, right: int) -> int:
        # The lower slot index always wins. Do not switch to union-by-rank or
        # union-by-size: the root would then depend on call order, and the
        # shuffled-input determinism test relies on it not doing so.
        left_root, right_root = self.find(left), self.find(right)
        if left_root == right_root:
            return left_root
        low, high = (left_root, right_root) if left_root < right_root else (right_root, left_root)
        self._parent[high] = low
        return low

    def key(self, index: int) -> Hashable:
        return self._keys[index]

    def root_key(self, index: int) -> Hashable:
        return self._keys[self.find(index)]

    def components(self) -> dict[int, list[int]]:
        groups: dict[int, list[int]] = {}
        for index in range(len(self._parent)):
            groups.setdefault(self.find(index), []).append(index)
        return groups

    def items(self) -> Iterator[tuple[Hashable, int]]:
        for index, key in enumerate(self._keys):
            yield key, self.find(index)
