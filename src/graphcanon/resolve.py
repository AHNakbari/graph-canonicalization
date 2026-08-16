"""Entity resolution: occurrences -> canonical entities.

The policy and the measurements behind it are in docs/DESIGN_NOTE.md §1-2.
"""

from __future__ import annotations

import collections
from typing import Iterable, NamedTuple

from . import confidence as conf
from . import reasons
from .config import Config
from .ids import canonical_entity_id
from .loading import Occurrence
from .naming import is_one_token_person, is_person, token_count
from .unionfind import UnionFind

DECISION_NEW = "NEW_CANONICAL"
DECISION_MERGED = "MERGED"
DECISION_POSSIBLE_DUPLICATE = "POSSIBLE_DUPLICATE"

# (org, workspace, entity_type, normalized_name, event_or_empty). The fifth slot
# is the single-token Person rule made structural: the source event for names
# that may not travel between documents, empty for everything else. The first
# three are the isolation boundary and may never be dropped from the key.
BlockKey = tuple[str, str, str, str, str]


class CanonicalEntity(NamedTuple):
    canonical_entity_id: str
    canonical_name: str
    entity_type: str
    org_id: str
    workspace_id: str
    member_candidate_entity_ids: tuple[str, ...]
    source_event_ids: tuple[str, ...]
    chunk_ids: tuple[str, ...]
    aliases: tuple[str, ...]
    component_quality: dict


class Assignment(NamedTuple):
    candidate_entity_id: str
    canonical_entity_id: str
    decision: str
    confidence: float
    reason_codes: tuple[str, ...]


class AliasLink(NamedTuple):
    left_canonical_entity_id: str
    right_canonical_entity_id: str
    asserting_candidate_entity_ids: tuple[str, ...]
    supporting_source_event_ids: tuple[str, ...]


class Resolution(NamedTuple):
    entities: dict[str, CanonicalEntity]
    assignments: dict[str, Assignment]
    # (org, workspace, normalized_name) -> source_event_id -> member IDs, for
    # every single-token Person name spanning more than one document. Exactly
    # the population duplicates.py enumerates.
    unresolved_person_groups: dict[tuple[str, str, str], dict[str, tuple[str, ...]]]
    alias_links: tuple[AliasLink, ...]
    stats: dict


def make_key(
    org_id: str,
    workspace_id: str,
    entity_type: str,
    normalized_name: str,
    source_event_id: str,
    config: Config,
) -> BlockKey:
    locality = ""
    if config.one_token_person_scope == "source_event" and is_one_token_person(
        entity_type, normalized_name
    ):
        locality = source_event_id
    return (org_id, workspace_id, entity_type, normalized_name, locality)


def block_key(occurrence: Occurrence, config: Config) -> BlockKey:
    return make_key(
        occurrence.org_id,
        occurrence.workspace_id,
        occurrence.entity_type,
        occurrence.normalized_name,
        occurrence.source_event_id,
        config,
    )


def _alias_links_by_key(
    occurrences: Iterable[Occurrence],
    key_of: dict[str, BlockKey],
    config: Config,
) -> dict[tuple[BlockKey, BlockKey], tuple[list[str], set[str]]]:
    # An alias only produces an edge if its target actually exists in the same
    # scope and type. An alias naming something never extracted is not a
    # duplicate question, so it is dropped rather than made into a phantom pair.
    known: set[BlockKey] = set(key_of.values())
    links: dict[tuple[BlockKey, BlockKey], tuple[list[str], set[str]]] = {}
    for occ in occurrences:
        if not occ.aliases:
            continue
        own = key_of[occ.candidate_entity_id]
        for alias in occ.aliases:
            folded = alias.casefold()
            if folded == occ.normalized_name:
                continue
            target = make_key(
                occ.org_id,
                occ.workspace_id,
                occ.entity_type,
                folded,
                occ.source_event_id,
                config,
            )
            if target not in known:
                continue
            edge = (own, target) if own <= target else (target, own)
            asserters, events = links.setdefault(edge, ([], set()))
            asserters.append(occ.candidate_entity_id)
            events.add(occ.source_event_id)
    return links


def resolve(occurrences: Iterable[Occurrence], config: Config) -> Resolution:
    occurrences = list(occurrences)
    union = UnionFind()

    # --- pass 1: blocking -----------------------------------------------
    key_of: dict[str, BlockKey] = {}
    slot_members: dict[int, list[int]] = {}
    for index, occ in enumerate(occurrences):
        key = block_key(occ, config)
        key_of[occ.candidate_entity_id] = key
        slot_members.setdefault(union.slot(key), []).append(index)

    # --- pass 2: alias evidence -----------------------------------------
    alias_edges = _alias_links_by_key(occurrences, key_of, config)
    alias_merged_slots: set[int] = set()
    if config.merge_on_alias:
        for (left, right), (_asserters, events) in sorted(alias_edges.items()):
            if len(events) < config.alias_min_support:
                continue
            root = union.union(union.slot(left), union.slot(right))
            alias_merged_slots.add(root)

    # --- pass 3: components ---------------------------------------------
    components: dict[int, list[int]] = {}
    component_keys: dict[int, list[BlockKey]] = {}
    for slot, members in slot_members.items():
        root = union.find(slot)
        components.setdefault(root, []).extend(members)
        component_keys.setdefault(root, []).append(union.key(slot))  # type: ignore[arg-type]
    # Alias merging can move a root; re-resolve so the flags follow the root.
    alias_roots = {union.find(slot) for slot in alias_merged_slots}

    # --- pass 4: the unresolved single-token Person population ------------
    person_groups: dict[tuple[str, str, str], dict[str, list[str]]] = {}
    for occ in occurrences:
        if not is_one_token_person(occ.entity_type, occ.normalized_name):
            continue
        group = person_groups.setdefault(
            (occ.org_id, occ.workspace_id, occ.normalized_name), {}
        )
        group.setdefault(occ.source_event_id, []).append(occ.candidate_entity_id)
    unresolved_person_groups = {
        group_key: {
            event: tuple(sorted(members)) for event, members in sorted(events.items())
        }
        for group_key, events in sorted(person_groups.items())
        if len(events) > 1
    }
    unresolved_occurrences: set[str] = {
        member
        for events in unresolved_person_groups.values()
        for members in events.values()
        for member in members
    }

    # --- pass 5: canonical entities and assignments -----------------------
    entities: dict[str, CanonicalEntity] = {}
    assignments: dict[str, Assignment] = {}
    key_to_canonical: dict[BlockKey, str] = {}
    reason_cache: dict[tuple[str, ...], tuple[str, ...]] = {}
    stats: collections.Counter[str] = collections.Counter()

    for root, member_indexes in components.items():
        members = [occurrences[i] for i in member_indexes]
        first = members[0]
        # Lowest key, never the first-seen one: under alias merging a component
        # can hold several keys, and min() is what keeps the canonical ID
        # independent of input order.
        identity_name, identity_locality = min(
            (key[3], key[4]) for key in component_keys[root]
        )
        canonical_id = canonical_entity_id(
            first.org_id,
            first.workspace_id,
            first.entity_type,
            identity_name,
            identity_locality,
        )
        if canonical_id in entities:  # pragma: no cover - 1e-14 per FINDINGS
            raise RuntimeError(f"canonical ID collision on {identity_name!r}")

        member_ids = sorted(occ.candidate_entity_id for occ in members)
        events = sorted({occ.source_event_id for occ in members})
        chunks = sorted({occ.chunk_id for occ in members})
        aliases = sorted({alias for occ in members for alias in occ.aliases})

        # Ties broken lexicographically, so the chosen surface form cannot
        # depend on the order rows arrived in.
        surface_counts = collections.Counter(occ.name for occ in members)
        top = max(surface_counts.values())
        canonical_name = min(n for n, c in surface_counts.items() if c == top)

        merged_by_alias = root in alias_roots
        one_token_person = is_one_token_person(first.entity_type, first.normalized_name)
        partners = len(
            person_groups.get(
                (first.org_id, first.workspace_id, first.normalized_name), {}
            )
        )

        codes: list[str] = []
        if one_token_person and config.one_token_person_scope == "source_event":
            codes.append(reasons.ONE_TOKEN_PERSON_SOURCE_SCOPED)
        codes.append(
            reasons.EXACT_NAME_IN_SCOPE if len(members) > 1 else reasons.SINGLETON_NAME
        )
        if merged_by_alias:
            codes.append(reasons.SOURCE_LOCAL_ALIAS)

        if merged_by_alias:
            base_confidence = conf.ALIAS_MERGE
        elif len(members) == 1:
            base_confidence = conf.SINGLETON
        elif one_token_person:
            base_confidence = conf.SOURCE_LOCAL
        else:
            base_confidence = conf.EXACT_NAME

        entities[canonical_id] = CanonicalEntity(
            canonical_entity_id=canonical_id,
            canonical_name=canonical_name,
            entity_type=first.entity_type,
            org_id=first.org_id,
            workspace_id=first.workspace_id,
            member_candidate_entity_ids=tuple(member_ids),
            source_event_ids=tuple(events),
            chunk_ids=tuple(chunks),
            aliases=tuple(aliases),
            component_quality={
                "member_count": len(member_ids),
                "source_event_count": len(events),
                "chunk_count": len(chunks),
                "name_token_count": token_count(first.normalized_name),
                "evidence_tier": codes[0],
                "source_scoped": bool(one_token_person),
                "unresolved_partner_components": max(0, partners - 1)
                if one_token_person
                else 0,
                "mean_extraction_confidence": round(
                    sum(occ.confidence for occ in members) / len(members), 4
                ),
            },
        )
        for key in component_keys[root]:
            key_to_canonical[key] = canonical_id

        for occ in members:
            occ_codes = codes
            decision = DECISION_MERGED if len(members) > 1 else DECISION_NEW
            if occ.candidate_entity_id in unresolved_occurrences:
                # Membership in this component is certain; what is open is
                # whether the component is the same person as a same-named one
                # in another document. Marking the assignment keeps that
                # visible from the row, not only from possible_duplicates.jsonl.
                decision = DECISION_POSSIBLE_DUPLICATE
                occ_codes = codes + [reasons.ONE_TOKEN_PERSON_UNRESOLVED_CROSS_SOURCE]
            frozen = tuple(occ_codes)
            frozen = reason_cache.setdefault(frozen, frozen)
            assignments[occ.candidate_entity_id] = Assignment(
                candidate_entity_id=occ.candidate_entity_id,
                canonical_entity_id=canonical_id,
                decision=decision,
                confidence=base_confidence,
                reason_codes=frozen,
            )
            stats[f"decision_{decision}"] += 1

    # --- alias links, expressed between canonical entities -----------------
    links: list[AliasLink] = []
    for (left_key, right_key), (asserters, events) in alias_edges.items():
        left = key_to_canonical[left_key]
        right = key_to_canonical[right_key]
        if left == right:
            stats["alias_links_within_component"] += 1
            continue
        low, high = (left, right) if left <= right else (right, left)
        links.append(
            AliasLink(
                left_canonical_entity_id=low,
                right_canonical_entity_id=high,
                asserting_candidate_entity_ids=tuple(sorted(set(asserters))),
                supporting_source_event_ids=tuple(sorted(events)),
            )
        )
    links.sort()

    summary = dict(stats)
    summary.update(
        {
            "occurrences": len(occurrences),
            "canonical_entities": len(entities),
            "blocking_keys": len(union),
            "alias_assertions_resolvable": len(alias_edges),
            "alias_links_between_components": len(links),
            "alias_merges_applied": len(alias_roots),
            "one_token_person_unresolved_groups": len(unresolved_person_groups),
            "one_token_person_unresolved_occurrences": len(unresolved_occurrences),
        }
    )
    return Resolution(
        entities=entities,
        assignments=assignments,
        unresolved_person_groups=unresolved_person_groups,
        alias_links=tuple(links),
        stats=summary,
    )


def verify_invariants(
    resolution: Resolution, occurrences: Iterable[Occurrence]
) -> dict[str, int]:
    """Re-derive the acceptance invariants from the finished result.

    Every boundary below is recomputed from the occurrences, never read back
    from the resolver's own bookkeeping. Keep it that way: reusing resolve()'s
    intermediate state here would let a bug in the resolver silence its own
    alarm, which is the whole reason this function exists.
    """
    by_id = {occ.candidate_entity_id: occ for occ in occurrences}
    violations = collections.Counter()

    seen_members: set[str] = set()
    for entity in resolution.entities.values():
        scopes = {by_id[m].org_id for m in entity.member_candidate_entity_ids}
        workspaces = {by_id[m].workspace_id for m in entity.member_candidate_entity_ids}
        types = {by_id[m].entity_type for m in entity.member_candidate_entity_ids}
        if len(scopes) > 1:
            violations["cross_organization_components"] += 1
        if len(workspaces) > 1:
            violations["cross_workspace_components"] += 1
        if len(types) > 1:
            violations["cross_type_components"] += 1
        if scopes != {entity.org_id} or workspaces != {entity.workspace_id}:
            violations["declared_scope_mismatch"] += 1
        if types != {entity.entity_type}:
            violations["declared_type_mismatch"] += 1

        duplicates = len(entity.member_candidate_entity_ids) - len(
            set(entity.member_candidate_entity_ids)
        )
        violations["duplicate_members"] += duplicates
        overlap = seen_members & set(entity.member_candidate_entity_ids)
        violations["members_in_multiple_components"] += len(overlap)
        seen_members.update(entity.member_candidate_entity_ids)

        if not entity.source_event_ids or not entity.chunk_ids:
            violations["entities_without_provenance"] += 1

        # Mirrors the one check tools/validate_submission.py fails outright on.
        if is_person(entity.entity_type) and len(entity.member_candidate_entity_ids) > 1:
            all_one_token = all(
                token_count(by_id[m].normalized_name) == 1
                for m in entity.member_candidate_entity_ids
            )
            spans_sources = len(entity.source_event_ids) > 1
            if all_one_token and spans_sources:
                codes = set()
                for member in entity.member_candidate_entity_ids:
                    codes.update(resolution.assignments[member].reason_codes)
                if not codes & reasons.CORROBORATING_CODES:
                    violations["prohibited_one_token_person_components"] += 1

    if seen_members != set(by_id):
        violations["membership_coverage_gap"] = len(set(by_id) - seen_members)
    if set(resolution.assignments) != set(by_id):
        violations["assignment_coverage_gap"] = len(set(by_id) - set(resolution.assignments))
    referenced = {a.canonical_entity_id for a in resolution.assignments.values()}
    if referenced != set(resolution.entities):
        violations["orphan_canonical_entities"] = len(referenced ^ set(resolution.entities))
    for assignment in resolution.assignments.values():
        if not assignment.reason_codes:
            violations["assignments_without_reason"] += 1

    return {k: v for k, v in violations.items() if v}
