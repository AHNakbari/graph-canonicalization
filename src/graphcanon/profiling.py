"""Input profiling."""

from __future__ import annotations

import collections
from pathlib import Path
from typing import Any

from .config import Config
from .loading import iter_facts, iter_occurrences, load_scopes
from .naming import is_one_token_person, is_person, token_count


def profile_input(config: Config) -> dict[str, Any]:
    scopes = load_scopes(config.input_dir)

    occurrences = 0
    by_type: collections.Counter[str] = collections.Counter()
    name_keys: set[tuple[str, str, str, str]] = set()
    events: set[str] = set()
    chunks: set[str] = set()
    with_aliases = 0
    person_token_counts: collections.Counter[int] = collections.Counter()
    one_token_person_occurrences = 0
    one_token_person_names: set[str] = set()
    one_token_person_components: set[tuple[str, str]] = set()

    for occ in iter_occurrences(config.input_dir, scopes):
        occurrences += 1
        by_type[occ.entity_type] += 1
        name_keys.add((occ.org_id, occ.workspace_id, occ.entity_type, occ.normalized_name))
        events.add(occ.source_event_id)
        chunks.add(occ.chunk_id)
        if occ.aliases:
            with_aliases += 1
        if is_person(occ.entity_type):
            person_token_counts[token_count(occ.normalized_name)] += 1
        if is_one_token_person(occ.entity_type, occ.normalized_name):
            one_token_person_occurrences += 1
            one_token_person_names.add(occ.normalized_name)
            one_token_person_components.add((occ.normalized_name, occ.source_event_id))

    facts = 0
    predicates: collections.Counter[str] = collections.Counter()
    facts_without_object_entity = 0
    for fact in iter_facts(config.input_dir):
        facts += 1
        predicates[fact.predicate] += 1
        if fact.object_candidate_id is None:
            facts_without_object_entity += 1

    distinct_scopes = {(s.org_id, s.workspace_id) for s in scopes.values()}
    return {
        "occurrences": occurrences,
        "facts": facts,
        "ledger_rows": len(scopes),
        "distinct_scopes": len(distinct_scopes),
        "distinct_organizations": len({s.org_id for s in scopes.values()}),
        "distinct_workspaces": len({s.workspace_id for s in scopes.values()}),
        "source_events_referenced_by_occurrences": len(events),
        "chunks_referenced_by_occurrences": len(chunks),
        "distinct_scope_type_name_keys": len(name_keys),
        "repetition_ratio": round(1 - len(name_keys) / occurrences, 4) if occurrences else 0.0,
        "occurrences_by_type": dict(sorted(by_type.items())),
        "occurrences_with_aliases": with_aliases,
        "person_name_token_counts": dict(sorted(person_token_counts.items())),
        "one_token_person_occurrences": one_token_person_occurrences,
        "one_token_person_distinct_names": len(one_token_person_names),
        "one_token_person_source_scoped_components": len(one_token_person_components),
        "distinct_predicates": len(predicates),
        "facts_without_object_entity": facts_without_object_entity,
        "top_predicates": dict(predicates.most_common(15)),
    }


def profile_paths(input_dir: Path) -> dict[str, str]:
    return {"input_dir": str(input_dir.resolve())}
