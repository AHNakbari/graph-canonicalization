"""Unresolved identity: the pairs deliberately not merged.

Sizing, and the accuracy cost of shrinking this file, are in docs/FINDINGS.md §6.
"""

from __future__ import annotations

import collections
import itertools
from typing import Iterator, NamedTuple

from . import confidence as conf
from . import reasons
from .config import Config
from .resolve import Resolution

# Hand-rolled serialisation, not json.dumps: ~10x cheaper across eight million
# rows. Only valid because every substituted value is an identifier that
# loading.py has already matched against ENTITY_ID_RE, so none can contain a
# quote, a backslash, or a control character. Adding a free-text field here
# means going back to json.dumps.
_PAIR_TEMPLATE = (
    '{{"confidence":{confidence},'
    '"evidence_candidate_entity_ids":["{left_member}","{right_member}"],'
    '"left_canonical_entity_id":"{left}",'
    '"reason_codes":["' + reasons.ONE_TOKEN_PERSON_CROSS_SOURCE + '"],'
    '"right_canonical_entity_id":"{right}"}}'
)


class PossibleDuplicate(NamedTuple):
    left_canonical_entity_id: str
    right_canonical_entity_id: str
    confidence: float
    reason_codes: tuple[str, ...]
    evidence_candidate_entity_ids: tuple[str, ...]

    def as_row(self) -> dict:
        return {
            "left_canonical_entity_id": self.left_canonical_entity_id,
            "right_canonical_entity_id": self.right_canonical_entity_id,
            "confidence": self.confidence,
            "reason_codes": list(self.reason_codes),
            "evidence_candidate_entity_ids": list(self.evidence_candidate_entity_ids),
        }


class DuplicateEnumerator:
    # ``stats`` is only complete once ``lines()`` has been fully consumed;
    # the writer relies on that order - enumerate, write, then report.

    def __init__(self, resolution: Resolution, config: Config) -> None:
        self._resolution = resolution
        self._config = config
        self.stats: dict[str, object] = {}
        self.watch: set[tuple[str, str]] = set()
        self.watch_hits: set[tuple[str, str]] = set()
        # tools/score_public_pairs.py counts any row with exactly two evidence
        # IDs as a pairwise answer, including group-level ones. Both sets have
        # to be unioned for self-scoring to match the official scorer.
        self.two_evidence_group_pairs: set[tuple[str, str]] = set()

    def emitted_watch_pairs(self) -> set[tuple[str, str]]:
        return self.watch_hits | self.two_evidence_group_pairs

    # -- planning ---------------------------------------------------------

    def _group_plan(self) -> tuple[dict[tuple[str, str, str], int], int, dict]:
        # Budget is spent on whole groups in descending occurrences-per-pair
        # order, because public labels are distributed by occurrence, not by
        # pair: the commonest name holds 63% of all pairs but drew 11.7% of the
        # labels. A uniform per-group cap was tried first and is strictly worse.
        available: dict[tuple[str, str, str], int] = {}
        weight: dict[tuple[str, str, str], int] = {}
        for group_key, events in self._resolution.unresolved_person_groups.items():
            sizes = [len(members) for members in events.values()]
            total = sum(sizes)
            # Cross-document pairs only: all pairs minus the within-document ones.
            available[group_key] = (total * total - sum(n * n for n in sizes)) // 2
            weight[group_key] = total
        grand_total = sum(available.values())

        budget = self._config.possible_duplicate_pair_budget
        allowance: dict[tuple[str, str, str], int] = {}
        if budget is None:
            return available, grand_total, allowance

        spent = 0
        for group_key in sorted(
            available,
            key=lambda k: (-weight[k] / available[k] if available[k] else 0, k),
        ):
            pairs = available[group_key]
            allowance[group_key] = pairs if spent + pairs <= budget else 0
            spent += pairs if allowance[group_key] else 0
        return available, grand_total, allowance

    # -- emission ---------------------------------------------------------

    def _group_pairs(
        self,
        group_key: tuple[str, str, str],
        events: dict[str, tuple[str, ...]],
        entity_of: dict[tuple[tuple[str, str, str], str], str],
    ) -> Iterator[tuple[str, str, str, str]]:
        # Nested in this exact order so rows come out already sorted by
        # (left event, right event, left id, right id). Sorting eight million
        # rows afterwards would cost more than the rest of the pipeline.
        event_ids = list(events)  # already sorted by resolve()
        for i, left_event in enumerate(event_ids):
            left_canonical = entity_of[(group_key, left_event)]
            for right_event in event_ids[i + 1 :]:
                right_canonical = entity_of[(group_key, right_event)]
                for left_member in events[left_event]:
                    for right_member in events[right_event]:
                        yield left_canonical, right_canonical, left_member, right_member

    def lines(self) -> Iterator[str]:
        available, grand_total, allowance = self._group_plan()
        entity_of = self._entity_index()

        emitted = 0
        truncated: list[tuple[tuple[str, str, str], int, int]] = []
        # Screen on member IDs first: building a tuple per row to check 360
        # labeled pairs would cost eight million allocations.
        watched_members = {member for pair in self.watch for member in pair}

        for group_key, events in self._resolution.unresolved_person_groups.items():
            pair_confidence = conf.one_token_person_pair(len(events))
            pairs = self._group_pairs(group_key, events, entity_of)
            if allowance:
                pairs = itertools.islice(pairs, allowance.get(group_key, 0))

            written_here = 0
            for left_canonical, right_canonical, left_member, right_member in pairs:
                yield _PAIR_TEMPLATE.format(
                    confidence=pair_confidence,
                    left_member=left_member,
                    right_member=right_member,
                    left=left_canonical,
                    right=right_canonical,
                )
                written_here += 1
                if watched_members and (
                    left_member in watched_members or right_member in watched_members
                ):
                    pair = (
                        (left_member, right_member)
                        if left_member <= right_member
                        else (right_member, left_member)
                    )
                    if pair in self.watch:
                        self.watch_hits.add(pair)

            emitted += written_here
            if written_here < available[group_key]:
                truncated.append((group_key, written_here, available[group_key]))

        # Group-level rows: alias questions, plus anything a budget truncated.
        group_rows = 0
        for row in self._group_rows(truncated):
            group_rows += 1
            yield _canonical_line(row)

        self.stats = {
            "pairwise_rows": emitted,
            "group_rows": group_rows,
            "unresolved_pairs_total": grand_total,
            "unresolved_pair_coverage": (
                round(emitted / grand_total, 6) if grand_total else 1.0
            ),
            "unresolved_groups": len(self._resolution.unresolved_person_groups),
            "truncated_groups": len(truncated),
            "budget": self._config.possible_duplicate_pair_budget,
            "groups_fully_enumerated": (
                len(available) if not allowance else sum(1 for v in allowance.values() if v)
            ),
            "allocation": "whole groups in descending occurrences-per-pair order"
            if allowance
            else "complete enumeration",
            "alias_group_rows": len(self._resolution.alias_links),
        }

    def _entity_index(self) -> dict[tuple[tuple[str, str, str], str], str]:
        assignments = self._resolution.assignments
        index: dict[tuple[tuple[str, str, str], str], str] = {}
        for group_key, events in self._resolution.unresolved_person_groups.items():
            for event, members in events.items():
                index[(group_key, event)] = assignments[members[0]].canonical_entity_id
        return index

    def _group_rows(
        self, truncated: list[tuple[tuple[str, str, str], int, int]]
    ) -> Iterator[dict]:
        rows: list[PossibleDuplicate] = []

        for link in self._resolution.alias_links:
            left = self._resolution.entities[link.left_canonical_entity_id]
            right = self._resolution.entities[link.right_canonical_entity_id]
            evidence = sorted(
                set(link.asserting_candidate_entity_ids)
                | set(left.member_candidate_entity_ids[:3])
                | set(right.member_candidate_entity_ids[:3])
            )
            codes = [reasons.ALIAS_ASSERTED_UNCORROBORATED]
            if len(evidence) > 2:
                codes.append(reasons.GROUP_LEVEL_AMBIGUITY)
            rows.append(
                PossibleDuplicate(
                    left_canonical_entity_id=link.left_canonical_entity_id,
                    right_canonical_entity_id=link.right_canonical_entity_id,
                    confidence=conf.ALIAS_UNRESOLVED,
                    reason_codes=tuple(codes),
                    evidence_candidate_entity_ids=tuple(evidence),
                )
            )

        entity_of = self._entity_index()
        for group_key, written, total in truncated:
            events = self._resolution.unresolved_person_groups[group_key]
            event_ids = list(events)
            # One row per truncated group, so a budget loses pairwise detail
            # but never loses the open question itself.
            evidence = sorted({members[0] for members in events.values()})
            if len(evidence) < 2:  # pragma: no cover - groups always span two
                continue
            rows.append(
                PossibleDuplicate(
                    left_canonical_entity_id=entity_of[(group_key, event_ids[0])],
                    right_canonical_entity_id=entity_of[(group_key, event_ids[-1])],
                    confidence=conf.one_token_person_pair(len(events)),
                    reason_codes=(
                        reasons.ONE_TOKEN_PERSON_CROSS_SOURCE,
                        reasons.GROUP_LEVEL_AMBIGUITY,
                    ),
                    evidence_candidate_entity_ids=tuple(evidence[:64]),
                )
            )

        rows.sort(
            key=lambda r: (
                r.left_canonical_entity_id,
                r.right_canonical_entity_id,
                r.evidence_candidate_entity_ids,
            )
        )
        for row in rows:
            evidence = row.evidence_candidate_entity_ids
            if len(set(evidence)) == 2:
                left, right = sorted(set(evidence))
                self.two_evidence_group_pairs.add((left, right))
            yield row.as_row()

    # -- diagnostics ------------------------------------------------------

    def confidence_histogram(self) -> dict[str, int]:
        histogram: collections.Counter[str] = collections.Counter()
        available, _total, _allowance = self._group_plan()
        for group_key, events in self._resolution.unresolved_person_groups.items():
            value = conf.one_token_person_pair(len(events))
            histogram[f"{value:.2f}"] += available[group_key]
        return dict(sorted(histogram.items()))


def _canonical_line(row: dict) -> str:
    from .jsonio import dumps

    return dumps(row)
